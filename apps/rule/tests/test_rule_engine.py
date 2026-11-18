from datetime import timedelta
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.rule.models import EmailRule, RuleCondition
from apps.rule.services.engine import RuleEvaluationEngine


User = get_user_model()


class RuleEngineTests(TestCase):

    def setUp(self):
        self.now = timezone.now()

        self.user = User.objects.create_user(
            email="rule_tester@example.com",
            password="test-password",
        )

        self.email = Mock(
            sender="client@example.com",
            recipient="admin@example.com",
            subject="Project Update Q4",
            body_text="The project delivery is scheduled for next week.",
            snippet="Project delivery update",
            received_datetime=self.now - timedelta(days=3),
        )

    # ---------------------------------------------------------
    # String predicates
    # ---------------------------------------------------------

    def test_contains_case_insensitive(self):
        result = RuleEvaluationEngine.evaluate_string_predicate(
            "Client@Example.com",
            "CONTAINS",
            "client@example.com",
        )

        self.assertTrue(result)

    def test_contains_returns_false_when_not_matching(self):
        result = RuleEvaluationEngine.evaluate_string_predicate(
            "other@example.com",
            "CONTAINS",
            "client@example.com",
        )

        self.assertFalse(result)

    def test_not_contains(self):
        self.assertTrue(
            RuleEvaluationEngine.evaluate_string_predicate(
                "other@example.com",
                "NOT_CONTAINS",
                "client",
            )
        )

    def test_equals(self):
        self.assertTrue(
            RuleEvaluationEngine.evaluate_string_predicate(
                " Project Update ",
                "EQUALS",
                "project update",
            )
        )

    def test_not_equals(self):
        self.assertTrue(
            RuleEvaluationEngine.evaluate_string_predicate(
                "Project Update",
                "NOT_EQUALS",
                "Invoice",
            )
        )

    def test_empty_contains_target_does_not_match(self):
        self.assertFalse(
            RuleEvaluationEngine.evaluate_string_predicate(
                "Hello",
                "CONTAINS",
                "",
            )
        )

    # ---------------------------------------------------------
    # Date predicates
    # ---------------------------------------------------------

    def test_date_less_than_seven_days(self):
        received = self.now - timedelta(days=3)

        self.assertTrue(
            RuleEvaluationEngine.evaluate_date_predicate(
                received,
                "LESS_THAN",
                "7",
                "DAYS",
                now_dt=self.now,
            )
        )

    def test_date_greater_than_seven_days(self):
        received = self.now - timedelta(days=10)

        self.assertTrue(
            RuleEvaluationEngine.evaluate_date_predicate(
                received,
                "GREATER_THAN",
                "7",
                "DAYS",
                now_dt=self.now,
            )
        )

    def test_date_missing_returns_false(self):
        self.assertFalse(
            RuleEvaluationEngine.evaluate_date_predicate(
                None,
                "LESS_THAN",
                "7",
                "DAYS",
                now_dt=self.now,
            )
        )

    def test_date_invalid_value_raises_error(self):
        with self.assertRaises(ValueError):
            RuleEvaluationEngine.evaluate_date_predicate(
                self.now,
                "LESS_THAN",
                "invalid",
                "DAYS",
                now_dt=self.now,
            )

    # ---------------------------------------------------------
    # Email field mapping
    # ---------------------------------------------------------

    def test_sender_condition(self):
        condition = Mock(
            field=RuleCondition.FieldType.FROM,
            predicate=RuleCondition.PredicateType.CONTAINS,
            value="client@example.com",
        )

        self.assertTrue(
            RuleEvaluationEngine.evaluate_condition(
                condition,
                self.email,
                now_dt=self.now,
            )
        )

    def test_subject_condition(self):
        condition = Mock(
            field=RuleCondition.FieldType.SUBJECT,
            predicate=RuleCondition.PredicateType.CONTAINS,
            value="project update",
        )

        self.assertTrue(
            RuleEvaluationEngine.evaluate_condition(
                condition,
                self.email,
                now_dt=self.now,
            )
        )

    def test_body_uses_snippet_as_fallback(self):
        email = Mock(
            sender="sender@example.com",
            recipient="admin@example.com",
            subject="Test",
            body_text="",
            snippet="Important invoice",
            received_datetime=self.now,
        )

        condition = Mock(
            field=RuleCondition.FieldType.BODY,
            predicate=RuleCondition.PredicateType.CONTAINS,
            value="invoice",
        )

        self.assertTrue(
            RuleEvaluationEngine.evaluate_condition(
                condition,
                email,
                now_dt=self.now,
            )
        )

    # ---------------------------------------------------------
    # Rule grouping
    # ---------------------------------------------------------

    def create_rule(self, predicate="ALL", is_active=True):
        return EmailRule.objects.create(
            user=self.user,
            name="Test Rule",
            group_predicate=predicate,
            is_active=is_active,
        )

    def create_condition(
        self,
        rule,
        field,
        value,
        predicate="CONTAINS",
        unit="",
    ):
        return RuleCondition.objects.create(
            rule=rule,
            field=field,
            predicate=predicate,
            value=value,
            unit=unit,
        )

    def test_all_conditions_must_match(self):
        rule = self.create_rule("ALL")

        self.create_condition(
            rule,
            RuleCondition.FieldType.FROM,
            "client@example.com",
        )

        self.create_condition(
            rule,
            RuleCondition.FieldType.SUBJECT,
            "project update",
        )

        self.assertTrue(
            RuleEvaluationEngine.evaluate_rule(
                rule,
                self.email,
                now_dt=self.now,
            )
        )

    def test_all_returns_false_when_one_condition_fails(self):
        rule = self.create_rule("ALL")

        self.create_condition(
            rule,
            RuleCondition.FieldType.FROM,
            "client@example.com",
        )

        self.create_condition(
            rule,
            RuleCondition.FieldType.SUBJECT,
            "invoice",
        )

        self.assertFalse(
            RuleEvaluationEngine.evaluate_rule(
                rule,
                self.email,
                now_dt=self.now,
            )
        )

    def test_any_condition_can_match(self):
        rule = self.create_rule("ANY")

        self.create_condition(
            rule,
            RuleCondition.FieldType.FROM,
            "unknown@example.com",
        )

        self.create_condition(
            rule,
            RuleCondition.FieldType.SUBJECT,
            "project update",
        )

        self.assertTrue(
            RuleEvaluationEngine.evaluate_rule(
                rule,
                self.email,
                now_dt=self.now,
            )
        )

    def test_inactive_rule_does_not_match(self):
        rule = self.create_rule(is_active=False)

        self.create_condition(
            rule,
            RuleCondition.FieldType.FROM,
            "client@example.com",
        )

        self.assertFalse(
            RuleEvaluationEngine.evaluate_rule(
                rule,
                self.email,
                now_dt=self.now,
            )
        )

    def test_rule_without_conditions_does_not_match(self):
        rule = self.create_rule()

        self.assertFalse(
            RuleEvaluationEngine.evaluate_rule(
                rule,
                self.email,
                now_dt=self.now,
            )
        )
