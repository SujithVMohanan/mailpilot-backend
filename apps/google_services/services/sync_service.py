
import base64
import logging

from datetime import datetime, timezone as datetime_timezone
from email.utils import parsedate_to_datetime

from django.db import transaction
from django.utils import timezone

from apps.google_services.models import (
    GmailAccount
    , Email
)

from apps.google_services.services.gmail_client import GmailClient


logger = logging.getLogger(__name__)


class EmailSyncService:
    DEFAULT_MAX_RESULTS = 50
    MAX_RESULTS_LIMIT   = 100

    def __init__(self, account: GmailAccount):
        self.account = account
        self.client = GmailClient(account)

    @staticmethod
    def _extract_header(headers, header_name):
        header_name = header_name.lower()

        for header in headers:
            if header.get("name", "").lower() == header_name:
                return header.get("value", "")

        return ""

    @staticmethod
    def _decode_body(encoded_data, charset="utf-8"):
        if not encoded_data:
            return ""

        try:
            padded_data = encoded_data + "=" * (-len(encoded_data) % 4)

            decoded_data = base64.urlsafe_b64decode(
                padded_data,
            )

            return decoded_data.decode(
                charset or "utf-8",
                errors="replace",
            )

        except (ValueError, UnicodeError):
            logger.warning("Unable to decode an email MIME body.")
            return ""

    @classmethod
    def _extract_body(cls, payload):
        body_text = []
        body_html = []

        def parse_part(part):
            mime_type = part.get("mimeType", "").lower()
            filename = part.get("filename", "")

            # Skip file attachments.
            if filename:
                return

            body = part.get("body", {})
            encoded_data = body.get("data")

            if encoded_data:
                content = cls._decode_body(encoded_data)

                if mime_type == "text/plain":
                    body_text.append(content)

                elif mime_type == "text/html":
                    body_html.append(content)

            for child_part in part.get("parts", []):
                parse_part(child_part)

        parse_part(payload)

        return (
            "\n".join(filter(None, body_text)).strip(),
            "\n".join(filter(None, body_html)).strip(),
        )

    @staticmethod
    def _parse_received_date(date_string, internal_date_ms):
        if date_string:
            try:
                received_datetime = parsedate_to_datetime(
                    date_string,
                )

                if timezone.is_naive(received_datetime):
                    received_datetime = timezone.make_aware(
                        received_datetime,
                        datetime_timezone.utc,
                    )

                return received_datetime

            except (TypeError, ValueError, OverflowError):
                logger.warning(
                    "Unable to parse email Date header: %s",
                    date_string,
                )

        if internal_date_ms:
            try:
                return datetime.fromtimestamp(
                    int(internal_date_ms) / 1000,
                    tz=datetime_timezone.utc,
                )

            except (TypeError, ValueError, OverflowError, OSError):
                logger.warning(
                    "Unable to parse Gmail internalDate: %s",
                    internal_date_ms,
                )

        return timezone.now()

    @classmethod
    def _build_email_data(cls, account, message):
        payload = message.get("payload", {})
        headers = payload.get("headers", [])

        sender = cls._extract_header(headers, "From")
        recipient = cls._extract_header(headers, "To")
        subject = cls._extract_header(headers, "Subject")
        date_string = cls._extract_header(headers, "Date")

        received_datetime = cls._parse_received_date(
            date_string,
            message.get("internalDate"),
        )

        body_text, body_html = cls._extract_body(payload)

        label_ids = message.get("labelIds", [])

        return {
            "account": account,
            "gmail_message_id": message["id"],
            "thread_id": message.get("threadId", ""),
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "snippet": message.get("snippet", ""),
            "body_text": body_text or message.get("snippet", ""),
            "body_html": body_html,
            "received_datetime": received_datetime,
            "is_read": "UNREAD" not in label_ids,
            "label_ids": label_ids,
        }

    def _save_message(self, message):
        email_data = self._build_email_data(
            self.account,
            message,
        )

        gmail_message_id = email_data.pop("gmail_message_id")

        with transaction.atomic():
            _, created = Email.objects.update_or_create(
                account=self.account,
                gmail_message_id=gmail_message_id,
                defaults=email_data,
            )

        return created

    def sync_inbox(
        self,
        max_results=DEFAULT_MAX_RESULTS,
        page_token=None,
    ):
        max_results = max(
            1,
            min(int(max_results), self.MAX_RESULTS_LIMIT),
        )

        messages, next_page_token = self.client.list_inbox_messages(
            max_results=max_results,
            page_token=page_token,
        )

        new_count = 0
        updated_count = 0
        failed_count = 0

        for message_summary in messages:
            message_id = message_summary.get("id")

            if not message_id:
                failed_count += 1
                continue

            try:
                message_detail = self.client.get_message_detail(
                    message_id,
                )

                created = self._save_message(message_detail)

                if created:
                    new_count += 1
                else:
                    updated_count += 1

            except Exception:
                failed_count += 1

                logger.exception(
                    "Email synchronization failed for "
                    "account_id=%s, message_id=%s",
                    self.account.pk,
                    message_id,
                )

        self.account.last_synced_at = timezone.now()

        self.account.save(
            update_fields=[
                "last_synced_at",
                "updated_at",
            ],
        )

        return {
            "synced_count": new_count + updated_count,
            "new_count": new_count,
            "updated_count": updated_count,
            "failed_count": failed_count,
            "next_page_token": next_page_token,
        }
