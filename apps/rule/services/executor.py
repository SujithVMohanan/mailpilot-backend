import logging

from django.db import IntegrityError
from django.utils import timezone

from apps.google_services.models import Email, GmailAccount
from apps.google_services.services.gmail_client import GmailClient
from apps.rule.models import (
    EmailRule,
    RuleAction,
    RuleExecution,
    RuleExecutionLog,
    RuleProcessedEmail,
)
from apps.rule.services.engine import RuleEvaluationEngine


logger = logging.getLogger(__name__)


class RuleExecutionOrchestrator:
    """
    Conflict and re-run policy:

    - Active rules run in ascending id order (oldest first).
    - Every matching rule is applied; later rules may override earlier ones.
    - Mark as read vs unread: the last successful action wins.
    - Multiple move actions: the last destination wins; INBOX is still removed.
    - Disabled rules are skipped. Edited rules use the current conditions.
    - The same rule does not process the same email twice after a successful
      or redundant (already applied) run. Failed actions remain retryable.
    """

    LOG_BATCH_SIZE = 500

    def __init__(self, user):
        self.user = user

        self.account = GmailAccount.objects.filter(
            user=user,
            is_active=True,
        ).first()

        self.gmail_client = (
            GmailClient(self.account)
            if self.account
            else None
        )

    def execute_rule(
        self,
        rule: EmailRule,
        emails_queryset=None,
        execution: RuleExecution | None = None,
    ) -> RuleExecution:
        self._validate_account()
        self._validate_rule(rule)

        emails_queryset = self._get_emails_queryset(emails_queryset)
        actions = list(rule.actions.all().order_by("id"))
        processed_email_ids = set(
            RuleProcessedEmail.objects.filter(
                rule=rule,
                email__account=self.account,
            ).values_list("email_id", flat=True)
        )

        if execution is None:
            execution = self._create_execution(rule)

        succeeded = 0
        failed = 0
        evaluated = 0
        matched = 0

        pending_logs = []
        pending_processed = []

        try:
            self._mark_execution_running(execution)

            for email in emails_queryset.iterator(chunk_size=500):
                evaluated += 1

                if email.pk in processed_email_ids:
                    continue

                if not RuleEvaluationEngine.evaluate_rule(
                    rule,
                    email,
                    now_dt=timezone.now(),
                ):
                    continue

                matched += 1

                email_failed = False
                email_completed = False

                for action in actions:
                    try:
                        if self._is_action_redundant(email, action):
                            pending_logs.append(
                                self._build_log(
                                    execution=execution,
                                    email=email,
                                    action=action,
                                    status=RuleExecutionLog.LogStatus.SKIPPED,
                                )
                            )
                            email_completed = True
                            continue

                        self._apply_action(email, action)

                        succeeded += 1
                        email_completed = True

                        pending_logs.append(
                            self._build_log(
                                execution=execution,
                                email=email,
                                action=action,
                                status=RuleExecutionLog.LogStatus.SUCCESS,
                            )
                        )

                    except Exception as exc:
                        failed += 1
                        email_failed = True

                        logger.exception(
                            "Rule action failed. "
                            "Execution ID: %s, Email ID: %s, Action ID: %s",
                            execution.pk,
                            email.pk,
                            action.pk,
                        )

                        pending_logs.append(
                            self._build_log(
                                execution=execution,
                                email=email,
                                action=action,
                                status=RuleExecutionLog.LogStatus.FAILED,
                                error_message=str(exc),
                            )
                        )

                    if len(pending_logs) >= self.LOG_BATCH_SIZE:
                        self._save_logs(pending_logs)
                        pending_logs.clear()

                if email_completed and not email_failed:
                    pending_processed.append(
                        RuleProcessedEmail(
                            rule=rule,
                            email=email,
                        )
                    )
                    processed_email_ids.add(email.pk)

            status = self._get_execution_status(
                succeeded=succeeded,
                failed=failed,
            )

            self._complete_execution(
                execution=execution,
                evaluated=evaluated,
                matched=matched,
                succeeded=succeeded,
                failed=failed,
                status=status,
            )

        except Exception:
            logger.exception(
                "Rule execution failed. Execution ID: %s",
                execution.pk,
            )

            self._complete_execution(
                execution=execution,
                evaluated=evaluated,
                matched=matched,
                succeeded=succeeded,
                failed=failed,
                status=RuleExecution.ExecutionStatus.FAILED,
            )

            raise

        finally:
            if pending_logs:
                self._save_logs(pending_logs)

            if pending_processed:
                self._save_processed(pending_processed)

        return execution

    def execute_all_active_rules(self) -> list[RuleExecution]:
        self._validate_account()

        emails_queryset = Email.objects.filter(
            account=self.account,
        ).order_by("id")

        active_rules = (
            EmailRule.objects.filter(
                user=self.user,
                is_active=True,
            )
            .prefetch_related("conditions", "actions")
            .order_by("id")
        )

        executions = []

        for rule in active_rules:
            try:
                execution = self.execute_rule(
                    rule,
                    emails_queryset=emails_queryset,
                )
                executions.append(execution)

            except Exception:
                logger.exception(
                    "Failed to execute rule. Rule ID: %s",
                    rule.pk,
                )

        return executions

    def _validate_account(self) -> None:
        if not self.account or not self.gmail_client:
            raise RuntimeError(
                "No active Gmail account is connected."
            )

    def _validate_rule(self, rule: EmailRule) -> None:
        if rule.user_id != self.user.pk:
            raise PermissionError(
                "You do not have permission to execute this rule."
            )

    def _get_emails_queryset(self, emails_queryset=None):
        if emails_queryset is None:
            emails_queryset = Email.objects.all()

        return emails_queryset.filter(
            account=self.account,
        ).order_by("id")

    def _create_execution(self, rule: EmailRule) -> RuleExecution:
        return RuleExecution.objects.create(
            user=self.user,
            rule=rule,
            rule_name_snapshot=rule.name,
            total_evaluated=0,
            total_matched=0,
            actions_succeeded=0,
            actions_failed=0,
            status=RuleExecution.ExecutionStatus.PENDING,
        )

    def _mark_execution_running(
        self,
        execution: RuleExecution,
    ) -> None:
        execution.status = RuleExecution.ExecutionStatus.RUNNING

        execution.save(
            update_fields=["status"],
        )

    def _complete_execution(
        self,
        execution: RuleExecution,
        *,
        evaluated: int,
        matched: int,
        succeeded: int,
        failed: int,
        status: str,
    ) -> None:
        execution.total_evaluated = evaluated
        execution.total_matched = matched
        execution.actions_succeeded = succeeded
        execution.actions_failed = failed
        execution.status = status
        execution.completed_at = timezone.now()

        execution.save(
            update_fields=[
                "total_evaluated",
                "total_matched",
                "actions_succeeded",
                "actions_failed",
                "status",
                "completed_at",
            ],
        )

    @staticmethod
    def _get_execution_status(
        *,
        succeeded: int,
        failed: int,
    ) -> str:
        if failed and succeeded:
            return RuleExecution.ExecutionStatus.PARTIAL_SUCCESS

        if failed:
            return RuleExecution.ExecutionStatus.FAILED

        return RuleExecution.ExecutionStatus.SUCCESS

    def _is_action_redundant(
        self,
        email: Email,
        action: RuleAction,
    ) -> bool:
        if action.action_type == RuleAction.ActionType.MARK_AS_READ:
            return email.is_read

        if action.action_type == RuleAction.ActionType.MARK_AS_UNREAD:
            return not email.is_read

        if action.action_type == RuleAction.ActionType.MOVE_MESSAGE:
            if not action.destination_label_id:
                raise ValueError(
                    "Destination label is required for MOVE_MESSAGE."
                )

            labels = set(email.label_ids or [])

            return (
                action.destination_label_id in labels
                and "INBOX" not in labels
            )

        return False

    def _apply_action(
        self,
        email: Email,
        action: RuleAction,
    ) -> None:
        add_labels, remove_labels = self._get_label_changes(action)

        self.gmail_client.modify_message_labels(
            message_id=email.gmail_message_id,
            add_label_ids=add_labels,
            remove_label_ids=remove_labels,
        )

        self._update_local_email_state(
            email=email,
            add_labels=add_labels,
            remove_labels=remove_labels,
        )

    def _get_label_changes(
        self,
        action: RuleAction,
    ) -> tuple[list[str], list[str]]:
        action_type = action.action_type

        if action_type == RuleAction.ActionType.MARK_AS_READ:
            return [], ["UNREAD"]

        if action_type == RuleAction.ActionType.MARK_AS_UNREAD:
            return ["UNREAD"], []

        if action_type == RuleAction.ActionType.MOVE_MESSAGE:
            if not action.destination_label_id:
                raise ValueError(
                    "Destination label is required for MOVE_MESSAGE."
                )

            return (
                [action.destination_label_id],
                ["INBOX"],
            )

        raise ValueError(
            f"Unsupported rule action: {action_type}"
        )

    @staticmethod
    def _update_local_email_state(
        email: Email,
        *,
        add_labels: list[str],
        remove_labels: list[str],
    ) -> None:
        labels = set(email.label_ids or [])

        labels.update(add_labels)
        labels.difference_update(remove_labels)

        email.label_ids = sorted(labels)
        email.is_read = "UNREAD" not in labels

        email.save(
            update_fields=[
                "label_ids",
                "is_read",
                "updated_at",
            ],
        )

    @staticmethod
    def _build_log(
        *,
        execution: RuleExecution,
        email: Email,
        action: RuleAction,
        status: str,
        error_message: str = "",
    ) -> RuleExecutionLog:
        return RuleExecutionLog(
            execution=execution,
            email=email,
            action_type=action.action_type,
            status=status,
            error_message=error_message[:2000],
        )

    @staticmethod
    def _save_logs(logs: list[RuleExecutionLog]) -> None:
        RuleExecutionLog.objects.bulk_create(
            logs,
            batch_size=500,
        )

    @staticmethod
    def _save_processed(rows: list[RuleProcessedEmail]) -> None:
        try:
            RuleProcessedEmail.objects.bulk_create(
                rows,
                batch_size=500,
                ignore_conflicts=True,
            )
        except IntegrityError:
            logger.warning(
                "Some processed-email rows already existed and were skipped."
            )
