import logging
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from apps.google_services.models import GmailAccount
from apps.google_services.services.oauth_service import GoogleOAuthService


logger = logging.getLogger(__name__)


class GmailClient:

    SERVICE_NAME = "gmail"
    SERVICE_VERSION = "v1"
    USER_ID = "me"
    RETRY_ATTEMPTS = 3
    RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, account: GmailAccount):
        self.account = account

        credentials = GoogleOAuthService.get_valid_credentials(
            account,
        )

        self.service = build(
            self.SERVICE_NAME,
            self.SERVICE_VERSION,
            credentials=credentials,
            cache_discovery=False,
        )

    def _execute(self, request):
        delay = 1

        for attempt in range(1, self.RETRY_ATTEMPTS + 1):
            try:
                return request.execute()
            except HttpError as exc:
                status_code = int(getattr(exc.resp, "status", 0) or 0)
                retryable = status_code in self.RETRY_STATUSES

                if retryable and attempt < self.RETRY_ATTEMPTS:
                    logger.warning(
                        "Retrying Gmail API call. account_id=%s status=%s attempt=%s",
                        self.account.pk,
                        status_code,
                        attempt,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue

                raise

    def list_inbox_messages(
        self,
        max_results=50,
        page_token=None,
    ):
        try:
            response = self._execute(
                self.service.users()
                .messages()
                .list(
                    userId=self.USER_ID,
                    labelIds=["INBOX"],
                    maxResults=max_results,
                    pageToken=page_token,
                )
            )

            return (
                response.get("messages", []),
                response.get("nextPageToken"),
            )

        except HttpError:
            logger.exception(
                "Failed to list Gmail messages for account_id=%s",
                self.account.pk,
            )
            raise

    def get_message_detail(self, message_id):
        try:
            return self._execute(
                self.service.users()
                .messages()
                .get(
                    userId=self.USER_ID,
                    id=message_id,
                    format="full",
                )
            )

        except HttpError:
            logger.exception(
                "Failed to retrieve Gmail message_id=%s",
                message_id,
            )
            raise

    def list_labels(self):
        try:
            response = self._execute(
                self.service.users()
                .labels()
                .list(userId=self.USER_ID)
            )

            return response.get("labels", [])

        except HttpError:
            logger.exception(
                "Failed to retrieve Gmail labels for account_id=%s",
                self.account.pk,
            )
            raise

    def modify_message_labels(
        self,
        message_id,
        add_label_ids=None,
        remove_label_ids=None,
    ):
        payload = {
            "addLabelIds": add_label_ids or [],
            "removeLabelIds": remove_label_ids or [],
        }

        try:
            return self._execute(
                self.service.users()
                .messages()
                .modify(
                    userId=self.USER_ID,
                    id=message_id,
                    body=payload,
                )
            )

        except HttpError:
            logger.exception(
                "Failed to modify labels for message_id=%s",
                message_id,
            )
            raise
