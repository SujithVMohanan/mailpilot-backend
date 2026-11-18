
import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from apps.google_services.models import GmailAccount
from apps.google_services.services.oauth_service import GoogleOAuthService
from apps.google_services.services.oauth_service import GoogleOAuthService


logger = logging.getLogger(__name__)


class GmailClient:
    
    SERVICE_NAME    = "gmail"
    SERVICE_VERSION = "v1"
    USER_ID         = "me"

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

    def list_inbox_messages(
        self,
        max_results=50,
        page_token=None,
    ):
        try:
            response = (
                self.service.users()
                .messages()
                .list(
                    userId=self.USER_ID,
                    labelIds=["INBOX"],
                    maxResults=max_results,
                    pageToken=page_token,
                )
                .execute()
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
            return (
                self.service.users()
                .messages()
                .get(
                    userId=self.USER_ID,
                    id=message_id,
                    format="full",
                )
                .execute()
            )

        except HttpError:
            logger.exception(
                "Failed to retrieve Gmail message_id=%s",
                message_id,
            )
            raise

    def list_labels(self):
        try:
            response = (
                self.service.users()
                .labels()
                .list(userId=self.USER_ID)
                .execute()
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
            return (
                self.service.users()
                .messages()
                .modify(
                    userId=self.USER_ID,
                    id=message_id,
                    body=payload,
                )
                .execute()
            )

        except HttpError:
            logger.exception(
                "Failed to modify labels for message_id=%s",
                message_id,
            )
            raise
