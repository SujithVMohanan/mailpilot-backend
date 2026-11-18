import logging

from django.db import transaction
from django.utils import timezone

from apps.google_services.models import GmailAccount
from apps.rule.models import EmailRule, RuleExecution


logger = logging.getLogger(__name__)

IN_PROGRESS_STATUSES = (
    RuleExecution.ExecutionStatus.PENDING,
    RuleExecution.ExecutionStatus.RUNNING,
)


class RuleExecutionInProgress(Exception):
    def __init__(self, executions):
        self.executions = executions


class RuleExecutionQueueError(Exception):
    pass


def _validate_gmail_account(user):
    if not GmailAccount.objects.filter(
        user=user,
        is_active=True,
    ).exists():
        raise RuntimeError("No active Gmail account is connected.")


def _mark_enqueue_failed(execution_ids):
    RuleExecution.objects.filter(
        pk__in=execution_ids,
        status=RuleExecution.ExecutionStatus.PENDING,
    ).update(
        status=RuleExecution.ExecutionStatus.FAILED,
        completed_at=timezone.now(),
    )


def queue_rule_execution(user, rule_id):
    _validate_gmail_account(user)

    with transaction.atomic():
        rule = EmailRule.objects.select_for_update().filter(
            pk=rule_id,
            user=user,
        ).first()
        if not rule:
            return None

        existing = list(
            RuleExecution.objects.filter(
                user=user,
                rule=rule,
                status__in=IN_PROGRESS_STATUSES,
            ).order_by("-started_at")
        )
        if existing:
            raise RuleExecutionInProgress(existing)

        execution = RuleExecution.objects.create(
            user=user,
            rule=rule,
            rule_name_snapshot=rule.name,
            status=RuleExecution.ExecutionStatus.PENDING,
        )

    try:
        from apps.rule.tasks import execute_rule_execution

        execute_rule_execution.delay(execution.pk)
    except Exception:
        _mark_enqueue_failed([execution.pk])
        logger.exception(
            "Unable to queue rule execution. execution_id=%s",
            execution.pk,
        )
        raise RuleExecutionQueueError(
            "Unable to queue rule execution.",
        ) from None

    return execution


def queue_all_active_rule_executions(user):
    _validate_gmail_account(user)

    with transaction.atomic():
        rules = list(
            EmailRule.objects.select_for_update().filter(
                user=user,
                is_active=True,
            ).order_by("id")
        )
        existing = list(
            RuleExecution.objects.filter(
                user=user,
                rule__in=rules,
                status__in=IN_PROGRESS_STATUSES,
            ).order_by("-started_at")
        )
        if existing:
            raise RuleExecutionInProgress(existing)

        executions = RuleExecution.objects.bulk_create(
            [
                RuleExecution(
                    user=user,
                    rule=rule,
                    rule_name_snapshot=rule.name,
                    status=RuleExecution.ExecutionStatus.PENDING,
                )
                for rule in rules
            ]
        )

    if not executions:
        return []

    execution_ids = [execution.pk for execution in executions]
    try:
        from apps.rule.tasks import execute_rule_executions

        execute_rule_executions.delay(execution_ids)
    except Exception:
        _mark_enqueue_failed(execution_ids)
        logger.exception(
            "Unable to queue bulk rule executions for user_id=%s",
            user.pk,
        )
        raise RuleExecutionQueueError(
            "Unable to queue rule executions.",
        ) from None

    return executions
