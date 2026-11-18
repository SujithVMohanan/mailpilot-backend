
from datetime import timedelta

from django.utils import timezone

from apps.rule.models import EmailRule, RuleCondition




class RuleEvaluationEngine:
    

    STRING_PREDICATES = {
        RuleCondition.PredicateType.CONTAINS,
        RuleCondition.PredicateType.NOT_CONTAINS,
        RuleCondition.PredicateType.EQUALS,
        RuleCondition.PredicateType.NOT_EQUALS,
    }

    DATE_PREDICATES = {
        RuleCondition.PredicateType.LESS_THAN,
        RuleCondition.PredicateType.GREATER_THAN,
    }

    @staticmethod
    def normalize(value):
        return str(value or "").strip().casefold()

    @classmethod
    def evaluate_string_predicate(
        cls,
        field_value,
        predicate,
        target_value,
    ):
        actual = cls.normalize(field_value)
        target = cls.normalize(target_value)

        if predicate == RuleCondition.PredicateType.CONTAINS:
            return bool(target) and target in actual

        if predicate == RuleCondition.PredicateType.NOT_CONTAINS:
            return target not in actual

        if predicate == RuleCondition.PredicateType.EQUALS:
            return actual == target

        if predicate == RuleCondition.PredicateType.NOT_EQUALS:
            return actual != target

        raise ValueError(
            f"Unsupported string predicate: {predicate}"
        )

    @staticmethod
    def get_date_duration(value, unit):
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise ValueError("Date duration must be numeric.")

        if amount <= 0:
            raise ValueError("Date duration must be positive.")

        if unit == RuleCondition.DateUnit.MONTHS:
            return timedelta(days=amount * 30)

        if unit == RuleCondition.DateUnit.DAYS:
            return timedelta(days=amount)

        raise ValueError(f"Unsupported date unit: {unit}")

    @classmethod
    def evaluate_date_predicate(
        cls,
        received_dt,
        predicate,
        value,
        unit,
        now_dt=None,
    ):
        if received_dt is None:
            return False

        now_dt = now_dt or timezone.now()

        duration = cls.get_date_duration(value, unit)
        age = now_dt - received_dt

        if predicate == RuleCondition.PredicateType.LESS_THAN:
            # Email received within the specified duration.
            return age < duration

        if predicate == RuleCondition.PredicateType.GREATER_THAN:
            # Email received earlier than the specified duration.
            return age > duration

        raise ValueError(
            f"Unsupported date predicate: {predicate}"
        )

    @classmethod
    def get_email_field_value(cls, email, field):
        field_mapping = {
            RuleCondition.FieldType.FROM: "sender",
            RuleCondition.FieldType.TO: "recipient",
            RuleCondition.FieldType.SUBJECT: "subject",
            RuleCondition.FieldType.BODY: "body_text",
            RuleCondition.FieldType.RECEIVED_DATE: "received_datetime",
        }

        attribute = field_mapping.get(field)

        if attribute is None:
            raise ValueError(f"Unsupported email field: {field}")

        value = getattr(email, attribute, None)

        if field == RuleCondition.FieldType.BODY:
            return value or getattr(email, "snippet", "") or ""

        return value

    @classmethod
    def evaluate_condition(cls, condition, email, now_dt=None):
        field_value = cls.get_email_field_value(
            email,
            condition.field,
        )

        if condition.field == RuleCondition.FieldType.RECEIVED_DATE:
            return cls.evaluate_date_predicate(
                received_dt=field_value,
                predicate=condition.predicate,
                value=condition.value,
                unit=condition.unit or RuleCondition.DateUnit.DAYS,
                now_dt=now_dt,
            )

        if condition.predicate not in cls.STRING_PREDICATES:
            raise ValueError(
                f"Unsupported predicate for field {condition.field}: "
                f"{condition.predicate}"
            )

        return cls.evaluate_string_predicate(
            field_value=field_value,
            predicate=condition.predicate,
            target_value=condition.value,
        )

    @classmethod
    def evaluate_rule(cls, rule, email, now_dt=None):
        """
        Evaluate all conditions belonging to a rule.

        ALL = every condition must match.
        ANY = at least one condition must match.

        Rules without conditions never match.
        """

        if not rule.is_active:
            return False

        conditions = list(rule.conditions.all())

        if not conditions:
            return False

        evaluator = lambda condition: cls.evaluate_condition(
            condition,
            email,
            now_dt=now_dt,
        )

        if rule.group_predicate == EmailRule.GroupPredicate.ALL:
            return all(map(evaluator, conditions))

        if rule.group_predicate == EmailRule.GroupPredicate.ANY:
            return any(map(evaluator, conditions))

        raise ValueError(
            f"Unsupported group predicate: {rule.group_predicate}"
        )
