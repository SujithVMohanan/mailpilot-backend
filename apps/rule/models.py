
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class EmailRule(models.Model):

    class GroupPredicate(models.TextChoices):
        ALL = "ALL", _("All conditions must match (AND)")
        ANY = "ANY", _("At least one condition must match (OR)")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_rules",
        verbose_name=_("User"),
    )

    name = models.CharField(
        _("Name"),
        max_length=200,
    )

    description = models.TextField(
        _("Description"),
        blank=True,
        default="",
    )

    is_active = models.BooleanField(
        _("Is Active"),
        default=True,
        db_index=True,
    )

    group_predicate = models.CharField(
        _("Group Predicate"),
        max_length=3,
        choices=GroupPredicate.choices,
        default=GroupPredicate.ALL,
    )

    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        _("Updated At"),
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Email Rule")
        verbose_name_plural = _("Email Rules")
        ordering = ("-created_at",)

        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="rule_user_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_group_predicate_display()})"


# ============================================================
# Rule Condition
# ============================================================

class RuleCondition(models.Model):

    class FieldType(models.TextChoices):
        FROM = "FROM", _("From")
        TO = "TO", _("To")
        SUBJECT = "SUBJECT", _("Subject")
        BODY = "BODY", _("Message Body")
        RECEIVED_DATE = "RECEIVED_DATE", _("Received Date/Time")

    class PredicateType(models.TextChoices):
        CONTAINS = "CONTAINS", _("Contains")
        NOT_CONTAINS = "NOT_CONTAINS", _("Does not contain")
        EQUALS = "EQUALS", _("Equals")
        NOT_EQUALS = "NOT_EQUALS", _("Does not equal")
        LESS_THAN = "LESS_THAN", _("Less than")
        GREATER_THAN = "GREATER_THAN", _("Greater than")

    class DateUnit(models.TextChoices):
        DAYS = "DAYS", _("Days")
        MONTHS = "MONTHS", _("Months")

    STRING_PREDICATES = {
        PredicateType.CONTAINS,
        PredicateType.NOT_CONTAINS,
        PredicateType.EQUALS,
        PredicateType.NOT_EQUALS,
    }

    DATE_PREDICATES = {
        PredicateType.LESS_THAN,
        PredicateType.GREATER_THAN,
    }

    rule = models.ForeignKey(
        EmailRule,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Rule"),
    )

    field = models.CharField(
        _("Field"),
        max_length=20,
        choices=FieldType.choices,
    )

    predicate = models.CharField(
        _("Predicate"),
        max_length=20,
        choices=PredicateType.choices,
    )

    value = models.TextField(
        _("Value"),
        blank=True,
        default="",
    )

    unit = models.CharField(
        _("Date Unit"),
        max_length=10,
        choices=DateUnit.choices,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Rule Condition")
        verbose_name_plural = _("Rule Conditions")
        ordering = ("id",)

        indexes = [
            models.Index(
                fields=["rule", "field"],
                name="condition_rule_field_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        is_date_field = self.field == self.FieldType.RECEIVED_DATE

        if is_date_field:

            if self.predicate not in self.DATE_PREDICATES:
                errors["predicate"] = _(
                    "Date fields support only LESS_THAN or GREATER_THAN."
                )

            if not self.unit:
                errors["unit"] = _(
                    "A date unit is required for date conditions."
                )

            elif self.unit not in self.DateUnit.values:
                errors["unit"] = _("Select a valid date unit.")

            try:
                amount = Decimal(self.value)

                if not amount.is_finite() or amount <= 0:
                    raise InvalidOperation

            except (InvalidOperation, TypeError, ValueError):
                errors["value"] = _(
                    "Enter a valid positive numeric date duration."
                )

        else:

            if self.predicate not in self.STRING_PREDICATES:
                errors["predicate"] = _(
                    "String fields support only CONTAINS, NOT_CONTAINS, "
                    "EQUALS or NOT_EQUALS."
                )

            if self.unit:
                errors["unit"] = _(
                    "Date units are not allowed for string conditions."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        unit = f" {self.get_unit_display()}" if self.unit else ""

        return (
            f"{self.get_field_display()} "
            f"{self.get_predicate_display()} "
            f"'{self.value}'{unit}"
        )


# ============================================================
# Rule Action
# ============================================================

class RuleAction(models.Model):

    class ActionType(models.TextChoices):
        MARK_AS_READ = "MARK_AS_READ", _("Mark as read")
        MARK_AS_UNREAD = "MARK_AS_UNREAD", _("Mark as unread")
        MOVE_MESSAGE = "MOVE_MESSAGE", _("Move message")

    rule = models.ForeignKey(
        EmailRule,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name=_("Rule"),
    )

    action_type = models.CharField(
        _("Action Type"),
        max_length=20,
        choices=ActionType.choices,
    )

    destination_label_id = models.CharField(
        _("Destination Label ID"),
        max_length=100,
        blank=True,
        default="",
    )

    destination_label_name = models.CharField(
        _("Destination Label Name"),
        max_length=200,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        _("Updated At"),
        auto_now=True,
    )

    class Meta:
        verbose_name = _("Rule Action")
        verbose_name_plural = _("Rule Actions")
        ordering = ("id",)

        indexes = [
            models.Index(
                fields=["rule", "action_type"],
                name="action_rule_type_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        is_move_action = self.action_type == self.ActionType.MOVE_MESSAGE

        if is_move_action:

            if not self.destination_label_id.strip():
                errors["destination_label_id"] = _(
                    "A destination label ID is required for MOVE_MESSAGE."
                )

        elif self.destination_label_id or self.destination_label_name:
            errors["destination_label_id"] = _(
                "Destination labels are only allowed for MOVE_MESSAGE."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        if self.action_type == self.ActionType.MOVE_MESSAGE:
            destination = (
                self.destination_label_name
                or self.destination_label_id
            )

            return str(
                _("Move message to label '%(label)s'")
                % {"label": destination}
            )

        return str(self.get_action_type_display())


# ============================================================
# Rule Execution
# ============================================================

class RuleExecution(models.Model):

    class ExecutionStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        RUNNING = "RUNNING", _("Running")
        SUCCESS = "SUCCESS", _("Success")
        PARTIAL_SUCCESS = "PARTIAL_SUCCESS", _("Partial Success")
        FAILED = "FAILED", _("Failed")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rule_executions",
        verbose_name=_("User"),
    )

    rule = models.ForeignKey(
        EmailRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="executions",
        verbose_name=_("Rule"),
    )

    rule_name_snapshot = models.CharField(
        _("Rule Name Snapshot"),
        max_length=200,
        blank=True,
        default="",
    )

    started_at = models.DateTimeField(
        _("Started At"),
        auto_now_add=True,
        db_index=True,
    )

    completed_at = models.DateTimeField(
        _("Completed At"),
        null=True,
        blank=True,
    )

    total_evaluated = models.PositiveIntegerField(
        _("Total Evaluated"),
        default=0,
    )

    total_matched = models.PositiveIntegerField(
        _("Total Matched"),
        default=0,
    )

    actions_succeeded = models.PositiveIntegerField(
        _("Actions Succeeded"),
        default=0,
    )

    actions_failed = models.PositiveIntegerField(
        _("Actions Failed"),
        default=0,
    )

    status = models.CharField(
        _("Execution Status"),
        max_length=20,
        choices=ExecutionStatus.choices,
        default=ExecutionStatus.PENDING,
    )

    class Meta:
        verbose_name = _("Rule Execution")
        verbose_name_plural = _("Rule Executions")
        ordering = ("-started_at",)

        indexes = [
            models.Index(
                fields=["user", "status"],
                name="execution_user_status_idx",
            ),
            models.Index(
                fields=["rule", "started_at"],
                name="execution_rule_date_idx",
            ),
        ]

    def __str__(self):
        rule_name = self.rule_name_snapshot or _("All Rules")

        return str(
            _("Execution #%(id)s - %(rule)s (%(status)s)")
            % {
                "id": self.pk,
                "rule": rule_name,
                "status": self.get_status_display(),
            }
        )


# ============================================================
# Rule Execution Log
# ============================================================

class RuleExecutionLog(models.Model):

    class LogStatus(models.TextChoices):
        SUCCESS = "SUCCESS", _("Success")
        FAILED = "FAILED", _("Failed")
        SKIPPED = "SKIPPED", _("Skipped")

    execution = models.ForeignKey(
        RuleExecution,
        on_delete=models.CASCADE,
        related_name="logs",
        verbose_name=_("Execution"),
    )

    email = models.ForeignKey(
        "google_services.Email",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execution_logs",
        verbose_name=_("Email"),
    )

    action_type = models.CharField(
        _("Action Type"),
        max_length=20,
        choices=RuleAction.ActionType.choices,
    )

    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=LogStatus.choices,
        default=LogStatus.SUCCESS,
    )

    error_message = models.TextField(
        _("Error Message"),
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        verbose_name = _("Rule Execution Log")
        verbose_name_plural = _("Rule Execution Logs")
        ordering = ("id",)

        indexes = [
            models.Index(
                fields=["execution", "status"],
                name="log_execution_status_idx",
            ),
            models.Index(
                fields=["email", "created_at"],
                name="log_email_date_idx",
            ),
        ]

    def __str__(self):
        return (
            f"Execution #{self.execution_id} | "
            f"Email {self.email_id or '-'} | "
            f"{self.get_action_type_display()} | "
            f"{self.get_status_display()}"
        )


class RuleProcessedEmail(models.Model):
    """Prevents the same rule from acting on the same email more than once."""

    rule = models.ForeignKey(
        EmailRule,
        on_delete=models.CASCADE,
        related_name="processed_emails",
        verbose_name=_("Rule"),
    )

    email = models.ForeignKey(
        "google_services.Email",
        on_delete=models.CASCADE,
        related_name="processed_rules",
        verbose_name=_("Email"),
    )

    processed_at = models.DateTimeField(
        _("Processed At"),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Processed Rule Email")
        verbose_name_plural = _("Processed Rule Emails")
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "email"],
                name="unique_rule_email_processed",
            ),
        ]

    def __str__(self):
        return f"Rule {self.rule_id} processed email {self.email_id}"
