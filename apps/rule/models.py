
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _




class EmailRule(models.Model):

    class GroupPredicate(models.TextChoices):

        ALL = "ALL", "All conditions must match (AND)"
        ANY = "ANY", "At least one condition must match (OR)"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_rules",
    )

    name = models.CharField(_("Name"), max_length=200)
    description = models.TextField(_("Description"), blank=True, default="")

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

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="rule_user_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.group_predicate})"



class RuleCondition(models.Model):

    class FieldType(models.TextChoices):
        FROM            = "FROM", "From"
        TO              = "TO", "To"
        SUBJECT         = "SUBJECT", "Subject"
        BODY            = "BODY", "Message Body"
        RECEIVED_DATE   = "RECEIVED_DATE", "Received Date/Time"

    class PredicateType(models.TextChoices):
        CONTAINS        = "CONTAINS", "Contains"
        NOT_CONTAINS    = "NOT_CONTAINS", "Does not contain"
        EQUALS          = "EQUALS", "Equals"
        NOT_EQUALS      = "NOT_EQUALS", "Does not equal"
        LESS_THAN       = "LESS_THAN", "Less than"
        GREATER_THAN    = "GREATER_THAN", "Greater than"

    class DateUnit(models.TextChoices):

        DAYS    = "DAYS", "Days"
        MONTHS  = "MONTHS", "Months"

    rule = models.ForeignKey(
        EmailRule,
        on_delete=models.CASCADE,
        related_name="conditions",
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

    value = models.TextField(_("Value"),blank=True, default="")

    unit = models.CharField(
        _("Unit"),
        max_length=10,
        choices=DateUnit.choices,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(
                fields=["rule", "field"],
                name="condition_rule_field_idx",
            ),
        ]

    def clean(self):
        super().clean()

        date_field = self.field == self.FieldType.RECEIVED_DATE
        date_predicate = self.predicate in {
            self.PredicateType.LESS_THAN,
            self.PredicateType.GREATER_THAN,
        }

        if date_field:
            if not date_predicate:
                raise ValidationError({
                    "predicate": "Date fields require LESS_THAN or GREATER_THAN."
                })

            if not self.unit:
                raise ValidationError({
                    "unit": "Date conditions require a date unit."
                })

            try:
                amount = float(self.value)
                if amount <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError({
                    "value": "Enter a positive numeric date duration."
                })

        elif self.predicate in {
            self.PredicateType.CONTAINS,
            self.PredicateType.NOT_CONTAINS,
            self.PredicateType.EQUALS,
            self.PredicateType.NOT_EQUALS,
        }:
            if self.unit:
                raise ValidationError({
                    "unit": "String conditions must not have a date unit."
                })

        else:
            raise ValidationError({
                "predicate": "Unsupported predicate for this field."
            })

    def __str__(self):
        return f"{self.field} {self.predicate} {self.value}"



class RuleAction(models.Model):

    class ActionType(models.TextChoices):
        MARK_AS_READ = "MARK_AS_READ", "Mark as read"
        MARK_AS_UNREAD = "MARK_AS_UNREAD", "Mark as unread"
        MOVE_MESSAGE = "MOVE_MESSAGE", "Move message"

    rule = models.ForeignKey(
        EmailRule,
        on_delete=models.CASCADE,
        related_name="actions",
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

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(
                fields=["rule", "action_type"],
                name="action_rule_type_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.action_type == self.ActionType.MOVE_MESSAGE
            and not self.destination_label_id.strip()
        ):
            raise ValidationError({
                "destination_label_id": (
                    "Destination label ID is required for MOVE_MESSAGE."
                )
            })

    def __str__(self):
        return f"{self.action_type} - {self.rule.name}"
