from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.google_services.models import Email, GmailAccount
from apps.rule.models import (
    EmailRule,
    RuleAction,
    RuleCondition,
    RuleExecutionLog,
    RuleProcessedEmail,
)
from apps.rule.services.executor import RuleExecutionOrchestrator


User = get_user_model()


class RuleExecutorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="test-password",
        )
        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address="owner@gmail.com",
            access_token="access",
            refresh_token="refresh",
            is_active=True,
        )
        self.email = Email.objects.create(
            account=self.account,
            gmail_message_id="msg-1",
            sender="client@example.com",
            recipient="owner@gmail.com",
            subject="Project Update",
            snippet="Hello",
            body_text="Hello",
            received_datetime=timezone.now() - timedelta(days=1),
            is_read=False,
            label_ids=["INBOX", "UNREAD"],
        )
        self.rule = EmailRule.objects.create(
            user=self.user,
            name="Important Client Emails",
            group_predicate=EmailRule.GroupPredicate.ALL,
            is_active=True,
        )
        RuleCondition.objects.create(
            rule=self.rule,
            field=RuleCondition.FieldType.FROM,
            predicate=RuleCondition.PredicateType.CONTAINS,
            value="client@example.com",
        )
        RuleAction.objects.create(
            rule=self.rule,
            action_type=RuleAction.ActionType.MARK_AS_READ,
        )

    @patch("apps.rule.services.executor.GmailClient")
    def test_successful_action_updates_local_state(self, client_cls):
        client_cls.return_value.modify_message_labels = Mock()

        execution = RuleExecutionOrchestrator(self.user).execute_rule(self.rule)

        self.email.refresh_from_db()
        self.assertTrue(self.email.is_read)
        self.assertEqual(execution.total_matched, 1)
        self.assertEqual(execution.actions_succeeded, 1)
        self.assertTrue(
            RuleProcessedEmail.objects.filter(
                rule=self.rule,
                email=self.email,
            ).exists()
        )

    @patch("apps.rule.services.executor.GmailClient")
    def test_gmail_failure_does_not_update_local_state(self, client_cls):
        client_cls.return_value.modify_message_labels.side_effect = RuntimeError(
            "Gmail API error"
        )

        execution = RuleExecutionOrchestrator(self.user).execute_rule(self.rule)

        self.email.refresh_from_db()
        self.assertFalse(self.email.is_read)
        self.assertEqual(execution.actions_failed, 1)
        self.assertFalse(
            RuleProcessedEmail.objects.filter(
                rule=self.rule,
                email=self.email,
            ).exists()
        )
        self.assertTrue(
            RuleExecutionLog.objects.filter(
                email=self.email,
                status=RuleExecutionLog.LogStatus.FAILED,
            ).exists()
        )

    @patch("apps.rule.services.executor.GmailClient")
    def test_duplicate_rule_email_is_skipped(self, client_cls):
        client_cls.return_value.modify_message_labels = Mock()
        orchestrator = RuleExecutionOrchestrator(self.user)

        orchestrator.execute_rule(self.rule)
        execution = orchestrator.execute_rule(self.rule)

        self.assertEqual(
            client_cls.return_value.modify_message_labels.call_count,
            1,
        )
        self.assertEqual(execution.total_matched, 0)
        self.assertEqual(execution.actions_succeeded, 0)
