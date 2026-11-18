import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.google_services.models import GmailAccount


logger = logging.getLogger(__name__)

GMAIL_SYNC_INTERVAL_MINUTES = 5
IN_PROGRESS_STATUSES = (
    GmailAccount.SyncStatus.QUEUED,
    GmailAccount.SyncStatus.RUNNING,
)


def enqueue_gmail_sync(
    account_id,
    *,
    trigger,
    max_results=50,
    page_token=None,
):
    with transaction.atomic():
        account = GmailAccount.objects.select_for_update().filter(
            pk=account_id,
            is_active=True,
        ).first()

        if not account:
            return None, "account_unavailable"

        if account.sync_status in IN_PROGRESS_STATUSES:
            return account, "already_in_progress"

        now = timezone.now()
        if trigger == GmailAccount.SyncTrigger.AUTOMATIC and (
            account.next_sync_at and account.next_sync_at > now
        ):
            return account, "not_due"

        account.sync_status = GmailAccount.SyncStatus.QUEUED
        account.sync_trigger = trigger
        account.sync_started_at = None
        account.sync_completed_at = None
        account.save(
            update_fields=[
                "sync_status",
                "sync_trigger",
                "sync_started_at",
                "sync_completed_at",
                "updated_at",
            ],
        )

        from apps.google_services.tasks import sync_gmail_for_account

        sync_gmail_for_account.delay(
            account.pk,
            max_results=max_results,
            page_token=page_token,
        )

        return account, "queued"


def enqueue_due_gmail_syncs():
    due_accounts = list(
        GmailAccount.objects.filter(
            is_active=True,
        ).filter(
            Q(next_sync_at__isnull=True)
            | Q(next_sync_at__lte=timezone.now()),
        ).exclude(
            sync_status__in=IN_PROGRESS_STATUSES,
        ).values_list("pk", flat=True)
    )

    queued_count = 0
    for account_id in due_accounts:
        try:
            _, outcome = enqueue_gmail_sync(
                account_id,
                trigger=GmailAccount.SyncTrigger.AUTOMATIC,
            )
        except Exception:
            logger.exception(
                "Unable to enqueue automatic Gmail sync for account_id=%s",
                account_id,
            )
            continue

        if outcome == "queued":
            queued_count += 1

    return {"queued_count": queued_count}


def get_sync_status_data(account):
    return {
        "sync_status": account.sync_status,
        "sync_trigger": account.sync_trigger or None,
        "sync_started_at": account.sync_started_at,
        "sync_completed_at": account.sync_completed_at,
        "last_successful_sync_at": account.last_successful_sync_at,
        "next_sync_at": account.next_sync_at,
        "is_syncing": account.sync_status in IN_PROGRESS_STATUSES,
    }


def complete_gmail_sync(account_id, *, successful):
    completed_at = timezone.now()
    with transaction.atomic():
        account = GmailAccount.objects.select_for_update().filter(
            pk=account_id,
        ).first()
        if not account or account.sync_status != GmailAccount.SyncStatus.RUNNING:
            return

        account.sync_status = (
            GmailAccount.SyncStatus.SUCCEEDED
            if successful
            else GmailAccount.SyncStatus.FAILED
        )
        account.sync_completed_at = completed_at
        account.next_sync_at = (
            completed_at + timedelta(minutes=GMAIL_SYNC_INTERVAL_MINUTES)
            if account.is_active
            else None
        )
        update_fields = [
            "sync_status",
            "sync_completed_at",
            "next_sync_at",
            "updated_at",
        ]
        if successful:
            account.last_successful_sync_at = completed_at
            account.last_synced_at = completed_at
            update_fields.extend(["last_successful_sync_at", "last_synced_at"])
        account.save(update_fields=update_fields)
