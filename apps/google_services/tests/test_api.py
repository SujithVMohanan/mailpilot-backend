from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.google_services.models import Email, GmailAccount
from apps.google_services.services.sync_service import EmailSyncService
from apps.google_services.tasks import (
    enqueue_due_gmail_syncs,
    sync_gmail_for_account,
)
from apps.rule.models import EmailRule
from core.utils.tokens import issue_tokens


User = get_user_model()


class GmailApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="gmail-user@example.com",
            password="Gmail-user-password-4892!",
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="Other-user-password-4892!",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_tokens(self.user)['access']}"
        )

    def create_account(self, user=None, active=True, **overrides):
        values = {
            "user": user or self.user,
            "email_address": "owner@gmail.com",
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "is_active": active,
        }
        values.update(overrides)
        return GmailAccount.objects.create(**values)

    def create_email(self, account, **overrides):
        values = {
            "account": account,
            "gmail_message_id": "gmail-message-1",
            "thread_id": "gmail-thread-1",
            "sender": "sender@example.com",
            "recipient": "owner@gmail.com",
            "subject": "Project update",
            "snippet": "Update snippet",
            "body_text": "The project is on schedule.",
            "body_html": "<p>The project is on schedule.</p>",
            "received_datetime": timezone.now() - timedelta(hours=1),
            "last_synced_at": timezone.now() - timedelta(minutes=5),
            "is_read": False,
            "label_ids": ["INBOX", "UNREAD"],
        }
        values.update(overrides)
        return Email.objects.create(**values)

    def test_oauth_initiate_requires_authentication(self):
        self.client.credentials()
        response = self.client.get("/api/mail/oauth/initiate/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_swagger_schema_is_available_without_authentication(self):
        self.client.credentials()

        with self.assertNoLogs("drf_yasg.inspectors.base", level="ERROR"):
            response = self.client.get("/api/docs/json/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("apps.google_services.views.GoogleOAuthService.store_oauth_state")
    @patch("apps.google_services.views.GoogleOAuthService.get_authorization_url")
    def test_oauth_initiate_returns_authorization_url(self, get_url, store_state):
        get_url.return_value = ("https://accounts.google.test/auth", "state", "verifier")

        response = self.client.get("/api/mail/oauth/initiate/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["authorization_url"],
            "https://accounts.google.test/auth",
        )
        store_state.assert_called_once()

    def test_oauth_callback_requires_code_and_state(self):
        response = self.client.post(
            "/api/mail/oauth/callback/",
            {"code": "authorization-code"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("state", response.data["errors"])

    @patch("apps.google_services.views.GoogleOAuthService.validate_oauth_state")
    def test_oauth_callback_rejects_invalid_state(self, validate_state):
        validate_state.return_value = None

        response = self.client.post(
            "/api/mail/oauth/callback/",
            {"code": "authorization-code", "state": "invalid"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "INVALID_OAUTH_STATE")

    @patch("apps.google_services.views.GoogleOAuthService.exchange_code_for_tokens")
    @patch("apps.google_services.views.GoogleOAuthService.validate_oauth_state")
    def test_oauth_callback_connects_account(self, validate_state, exchange):
        account = self.create_account()
        validate_state.return_value = "code-verifier"
        exchange.return_value = account

        response = self.client.post(
            "/api/mail/oauth/callback/",
            {"code": "authorization-code", "state": "valid-state"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["email_address"], "owner@gmail.com")
        exchange.assert_called_once()

    @patch("apps.google_services.views.GoogleOAuthService.revoke_account_tokens")
    def test_disconnect_removes_connected_account(self, revoke):
        account = self.create_account()

        response = self.client.post("/api/mail/disconnect/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(GmailAccount.objects.filter(pk=account.pk).exists())
        revoke.assert_called_once()

    def test_disconnect_returns_not_found_without_account(self):
        response = self.client.post("/api/mail/disconnect/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("apps.google_services.views.GmailClient")
    def test_labels_returns_gmail_labels(self, client_class):
        self.create_account()
        client_class.return_value.list_labels.return_value = [
            {"id": "INBOX", "name": "Inbox"}
        ]

        response = self.client.get("/api/mail/labels/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["labels"],
            [{"id": "INBOX", "name": "Inbox"}],
        )

    def test_labels_returns_not_found_without_active_account(self):
        self.create_account(active=False)
        response = self.client.get("/api/mail/labels/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_sync_rejects_invalid_max_results(self):
        response = self.client.post(
            "/api/mail/sync/",
            {"max_results": 101},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sync_returns_not_found_without_active_account(self):
        response = self.client.post(
            "/api/mail/sync/",
            {"max_results": 20},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("apps.google_services.services.sync_service.GmailClient")
    def test_sync_records_each_email_sync_timestamp(self, gmail_client):
        account = self.create_account()
        sync_service = EmailSyncService(account)
        sync_started_at = timezone.now()

        sync_service._save_message(
            {
                "id": "synced-message",
                "payload": {"headers": []},
                "snippet": "Synced message",
            }
        )

        email = Email.objects.get(
            account=account,
            gmail_message_id="synced-message",
        )
        self.assertIsNotNone(email.last_synced_at)
        self.assertGreaterEqual(email.last_synced_at, sync_started_at)

    @patch("apps.google_services.tasks.sync_gmail_for_account.delay")
    def test_sync_now_queues_gmail_sync(self, enqueue):
        account = self.create_account()

        response = self.client.post(
            "/api/mail/sync/",
            {"max_results": 25},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["data"]["sync_status"], "QUEUED")
        self.assertEqual(response.data["data"]["sync_trigger"], "MANUAL")
        enqueue.assert_called_once_with(
            account.pk,
            max_results=25,
            page_token=None,
        )

    @patch("apps.google_services.tasks.sync_gmail_for_account.delay")
    def test_sync_now_rejects_automatic_sync_already_running(self, enqueue):
        account = self.create_account(
            sync_status=GmailAccount.SyncStatus.RUNNING,
            sync_trigger=GmailAccount.SyncTrigger.AUTOMATIC,
            sync_started_at=timezone.now(),
        )

        response = self.client.post("/api/mail/sync/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data["code"],
            "EMAIL_SYNC_ALREADY_IN_PROGRESS",
        )
        self.assertEqual(
            response.data["errors"]["sync_status"],
            GmailAccount.SyncStatus.RUNNING,
        )
        enqueue.assert_not_called()

    @patch("apps.google_services.tasks.sync_gmail_for_account.delay")
    def test_scheduler_enqueues_active_accounts_and_skips_running(self, enqueue):
        due_account = self.create_account()
        self.create_account(
            self.other_user,
            sync_status=GmailAccount.SyncStatus.RUNNING,
        )
        self.create_account(
            user=User.objects.create_user(email="queued@example.com"),
            sync_status=GmailAccount.SyncStatus.QUEUED,
            sync_trigger=GmailAccount.SyncTrigger.MANUAL,
        )
        self.create_account(
            active=False,
            user=User.objects.create_user(email="inactive@example.com"),
        )

        result = enqueue_due_gmail_syncs.run()

        self.assertEqual(result, {"queued_count": 1})
        enqueue.assert_called_once_with(
            due_account.pk,
            max_results=50,
            page_token=None,
        )
        due_account.refresh_from_db()
        self.assertEqual(due_account.sync_status, GmailAccount.SyncStatus.QUEUED)
        self.assertEqual(
            due_account.sync_trigger,
            GmailAccount.SyncTrigger.AUTOMATIC,
        )

    def test_sync_status_endpoint_returns_state_timestamps(self):
        started_at = timezone.now()
        account = self.create_account(
            sync_status=GmailAccount.SyncStatus.RUNNING,
            sync_trigger=GmailAccount.SyncTrigger.MANUAL,
            sync_started_at=started_at,
        )

        response = self.client.get("/api/v1/mail/sync/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["sync_status"],
            GmailAccount.SyncStatus.RUNNING,
        )
        self.assertEqual(
            response.data["data"]["sync_trigger"],
            GmailAccount.SyncTrigger.MANUAL,
        )
        self.assertTrue(response.data["data"]["is_syncing"])

    @patch("apps.google_services.tasks.EmailSyncService")
    def test_worker_updates_success_status_and_schedules_after_completion(
        self,
        sync_service_class,
    ):
        account = self.create_account(
            sync_status=GmailAccount.SyncStatus.QUEUED,
            sync_trigger=GmailAccount.SyncTrigger.MANUAL,
            last_successful_sync_at=timezone.now() - timedelta(days=1),
        )
        sync_service_class.return_value.sync_inbox.return_value = {
            "synced_count": 2,
            "new_count": 1,
            "updated_count": 1,
            "failed_count": 0,
            "next_page_token": None,
        }

        result = sync_gmail_for_account.run(account.pk)

        self.assertEqual(result["sync_status"], GmailAccount.SyncStatus.SUCCEEDED)
        account.refresh_from_db()
        self.assertEqual(account.sync_status, GmailAccount.SyncStatus.SUCCEEDED)
        self.assertIsNotNone(account.sync_started_at)
        self.assertIsNotNone(account.sync_completed_at)
        self.assertEqual(
            account.last_successful_sync_at,
            account.sync_completed_at,
        )
        self.assertEqual(account.last_synced_at, account.sync_completed_at)
        self.assertGreater(
            account.next_sync_at,
            account.sync_completed_at,
        )
        self.assertAlmostEqual(
            (account.next_sync_at - account.sync_completed_at).total_seconds(),
            300,
            delta=1,
        )

    @patch("apps.google_services.tasks.EmailSyncService")
    def test_worker_skips_duplicate_task_while_sync_is_running(
        self,
        sync_service_class,
    ):
        account = self.create_account(
            sync_status=GmailAccount.SyncStatus.RUNNING,
            sync_trigger=GmailAccount.SyncTrigger.AUTOMATIC,
            sync_started_at=timezone.now(),
        )

        result = sync_gmail_for_account.run(account.pk)

        self.assertEqual(result["reason"], "sync_not_queued")
        sync_service_class.assert_not_called()

    @patch("apps.google_services.tasks.EmailSyncService")
    def test_worker_records_failure_without_overwriting_last_success(
        self,
        sync_service_class,
    ):
        last_success = timezone.now() - timedelta(days=1)
        account = self.create_account(
            sync_status=GmailAccount.SyncStatus.QUEUED,
            last_successful_sync_at=last_success,
            last_synced_at=last_success,
        )
        sync_service_class.return_value.sync_inbox.side_effect = RuntimeError(
            "Gmail API unavailable",
        )

        with self.assertRaisesMessage(RuntimeError, "Gmail API unavailable"):
            sync_gmail_for_account.run(account.pk)

        account.refresh_from_db()
        self.assertEqual(account.sync_status, GmailAccount.SyncStatus.FAILED)
        self.assertIsNotNone(account.sync_started_at)
        self.assertIsNotNone(account.sync_completed_at)
        self.assertEqual(account.last_successful_sync_at, last_success)
        self.assertEqual(account.last_synced_at, last_success)
        self.assertGreater(account.next_sync_at, account.sync_completed_at)

    def test_email_list_is_authenticated_and_paginated(self):
        self.client.credentials()
        response = self.client.get("/api/mail/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_tokens(self.user)['access']}"
        )
        account = self.create_account()
        email = self.create_email(account)
        response = self.client.get("/api/mail/?page=1&limit=10")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["count"], 1)
        self.assertEqual(
            response.data["data"]["results"][0]["gmail_message_id"],
            "gmail-message-1",
        )
        self.assertEqual(
            parse_datetime(
                response.data["data"]["results"][0]["last_synced_at"],
            ),
            email.last_synced_at,
        )

    def test_email_list_filters_and_scopes_to_current_user(self):
        account = self.create_account()
        self.create_email(account)
        other_account = self.create_account(self.other_user)
        self.create_email(
            other_account,
            gmail_message_id="other-message",
            subject="Private message",
        )

        response = self.client.get(
            "/api/mail/?search=project&is_read=false&ordering=subject"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["subject"], "Project update")

    def test_email_list_rejects_unsupported_ordering(self):
        self.create_account()
        response = self.client.get("/api/mail/?ordering=sender")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_detail_returns_body_and_hides_other_users_email(self):
        account = self.create_account()
        email = self.create_email(account)
        response = self.client.get(f"/api/mail/{email.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["body_text"],
            "The project is on schedule.",
        )
        self.assertEqual(
            parse_datetime(response.data["data"]["last_synced_at"]),
            email.last_synced_at,
        )

        other_email = self.create_email(
            self.create_account(self.other_user),
            gmail_message_id="private-message",
        )
        response = self.client.get(f"/api/mail/{other_email.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_dashboard_stats_returns_email_counts_and_account_status(self):
        account = self.create_account()
        self.create_email(account, is_read=False)
        self.create_email(
            account,
            gmail_message_id="read-message",
            is_read=True,
        )
        EmailRule.objects.create(user=self.user, name="Rule")

        response = self.client.get("/api/mail/stats/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["account"]["connected"])
        self.assertEqual(response.data["data"]["total_emails"], 2)
        self.assertEqual(response.data["data"]["read_emails"], 1)
        self.assertEqual(response.data["data"]["unread_emails"], 1)
        self.assertEqual(response.data["data"]["total_rules"], 1)

    def test_dashboard_stats_requires_authentication(self):
        self.client.credentials()
        response = self.client.get("/api/mail/stats/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
