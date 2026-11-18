import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.google_services.models import GmailAccount
from apps.google_services.services.sync_scheduler import (
    complete_gmail_sync,
    enqueue_due_gmail_syncs as enqueue_due_syncs,
)
from apps.google_services.services.sync_service import EmailSyncService


logger = logging.getLogger(__name__)


@shared_task
def enqueue_due_gmail_syncs():
    return enqueue_due_syncs()


@shared_task
def sync_gmail_for_account(account_id, max_results=50, page_token=None):
    with transaction.atomic():
        account = GmailAccount.objects.select_for_update().filter(
            pk=account_id,
            is_active=True,
        ).first()

        if not account:
            return {"status": "skipped", "reason": "account_unavailable"}

        if account.sync_status != GmailAccount.SyncStatus.QUEUED:
            return {"status": "skipped", "reason": "sync_not_queued"}

        account.sync_status = GmailAccount.SyncStatus.RUNNING
        account.sync_started_at = timezone.now()
        account.save(
            update_fields=[
                "sync_status",
                "sync_started_at",
                "updated_at",
            ],
        )

    try:
        result = EmailSyncService(account).sync_inbox(
            max_results=max_results,
            page_token=page_token,
        )
    except Exception:
        complete_gmail_sync(account_id, successful=False)
        logger.exception(
            "Gmail synchronization failed for account_id=%s",
            account_id,
        )
        raise

    successful = result["failed_count"] == 0
    complete_gmail_sync(account_id, successful=successful)
    logger.info(
        "Gmail sync completed for account_id=%s status=%s synced_count=%s",
        account_id,
        (
            GmailAccount.SyncStatus.SUCCEEDED
            if successful
            else GmailAccount.SyncStatus.FAILED
        ),
        result["synced_count"],
    )
    return {
        **result,
        "sync_status": (
            GmailAccount.SyncStatus.SUCCEEDED
            if successful
            else GmailAccount.SyncStatus.FAILED
        ),
    }
