import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.rule.models import RuleExecution
from apps.rule.services.executor import RuleExecutionOrchestrator


logger = logging.getLogger(__name__)


def _claim_execution(execution_id):
    with transaction.atomic():
        execution = (
            RuleExecution.objects.select_for_update(of=("self",))
            .select_related("user", "rule")
            .filter(pk=execution_id)
            .first()
        )
        if (
            not execution
            or execution.status != RuleExecution.ExecutionStatus.PENDING
        ):
            return None

        if not execution.rule_id:
            execution.status = RuleExecution.ExecutionStatus.FAILED
            execution.completed_at = timezone.now()
            execution.save(update_fields=["status", "completed_at"])
            return None

        execution.status = RuleExecution.ExecutionStatus.RUNNING
        execution.save(update_fields=["status"])
        return execution


def _mark_execution_failed(execution_id):
    RuleExecution.objects.filter(
        pk=execution_id,
        status__in=(
            RuleExecution.ExecutionStatus.PENDING,
            RuleExecution.ExecutionStatus.RUNNING,
        ),
    ).update(
        status=RuleExecution.ExecutionStatus.FAILED,
        completed_at=timezone.now(),
    )


def _execute(execution_id):
    execution = _claim_execution(execution_id)
    if not execution:
        return None

    try:
        return RuleExecutionOrchestrator(
            user=execution.user,
        ).execute_rule(
            execution.rule,
            execution=execution,
        )
    except Exception:
        _mark_execution_failed(execution_id)
        logger.exception(
            "Queued rule execution failed. execution_id=%s",
            execution_id,
        )
        raise


@shared_task
def execute_rule_execution(execution_id):
    execution = _execute(execution_id)
    if execution is None:
        return {"status": "skipped", "reason": "execution_not_pending"}
    return {"execution_id": execution.pk, "status": execution.status}


@shared_task
def execute_rule_executions(execution_ids):
    results = []
    for execution_id in execution_ids:
        try:
            result = execute_rule_execution.run(execution_id)
        except Exception:
            logger.exception(
                "Bulk rule execution item failed. execution_id=%s",
                execution_id,
            )
            continue

        results.append(result)

    return results
