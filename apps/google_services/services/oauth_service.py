import logging
import secrets
from datetime import timezone as datetime_timezone

import requests

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from apps.google_services.models import GmailAccount


logger = logging.getLogger(__name__)


class GoogleOAuthService:

    TOKEN_URI = "https://oauth2.googleapis.com/token"
    REVOKE_URI = "https://oauth2.googleapis.com/revoke"
    USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    REQUEST_TIMEOUT = 10
    OAUTH_STATE_TTL = 600
    OAUTH_STATE_KEY = "gmail_oauth_state:{user_id}"

    @staticmethod
    def _get_client_config():
        return {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": GoogleOAuthService.TOKEN_URI,
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        }

    @classmethod
    def _get_flow(cls, state=None):
        return Flow.from_client_config(
            cls._get_client_config(),
            scopes=settings.GOOGLE_GMAIL_SCOPES,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
            state=state,
        )

    @classmethod
    def store_oauth_state(cls, user_id, state):
        cache.set(
            cls.OAUTH_STATE_KEY.format(user_id=user_id),
            state,
            timeout=cls.OAUTH_STATE_TTL,
        )

    @classmethod
    def validate_oauth_state(cls, user_id, state):
        key = cls.OAUTH_STATE_KEY.format(user_id=user_id)
        stored_state = cache.get(key)
        cache.delete(key)

        if not stored_state or not state:
            return False

        return secrets.compare_digest(str(stored_state), str(state))

    @classmethod
    def get_authorization_url(cls, state=None):
        flow = cls._get_flow(state=state)

        auth_url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        return auth_url, returned_state

    @classmethod
    def _get_user_email(cls, access_token):
        response = requests.get(
            cls.USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=cls.REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        email = response.json().get("email")

        if not email:
            raise ValueError("Unable to retrieve Google account email.")

        return email

    @staticmethod
    def _get_token_expiry(credentials):
        expiry = credentials.expiry

        if expiry and timezone.is_naive(expiry):
            expiry = timezone.make_aware(
                expiry,
                datetime_timezone.utc,
            )

        return expiry

    @classmethod
    def exchange_code_for_tokens(cls, code, user, state):
        flow = cls._get_flow(state=state)
        flow.fetch_token(code=code)

        credentials = flow.credentials

        email_address = cls._get_user_email(credentials.token)

        existing_account = GmailAccount.objects.filter(
            user=user,
        ).first()

        refresh_token = (
            credentials.refresh_token
            or (
                existing_account.refresh_token
                if existing_account
                else None
            )
        )

        account, _ = GmailAccount.objects.update_or_create(
            user=user,
            defaults={
                "email_address": email_address,
                "access_token": credentials.token,
                "refresh_token": refresh_token,
                "token_expiry": cls._get_token_expiry(credentials),
                "scopes": credentials.scopes or settings.GOOGLE_GMAIL_SCOPES,
                "is_active": True,
            },
        )

        return account

    @classmethod
    def get_valid_credentials(cls, account):
        if not account.is_active:
            raise ValueError("Gmail account is inactive.")

        credentials = Credentials(
            token=account.access_token,
            refresh_token=account.refresh_token,
            token_uri=cls.TOKEN_URI,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            scopes=account.scopes or settings.GOOGLE_GMAIL_SCOPES,
        )

        if not credentials.valid:
            if not credentials.refresh_token:
                raise ValueError(
                    "Access token expired and no refresh token available."
                )

            try:
                credentials.refresh(Request())

            except RefreshError as exc:
                raise ValueError(
                    "Google token refresh failed. Reconnect your Gmail account."
                ) from exc

            account.access_token = credentials.token
            account.token_expiry = cls._get_token_expiry(credentials)

            account.save(
                update_fields=[
                    "access_token",
                    "token_expiry",
                    "updated_at",
                ]
            )

        return credentials

    @classmethod
    def revoke_account_tokens(cls, account):
        token = account.refresh_token or account.access_token

        if not token:
            return

        try:
            requests.post(
                cls.REVOKE_URI,
                params={"token": token},
                headers={
                    "content-type": "application/x-www-form-urlencoded",
                },
                timeout=cls.REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            logger.warning(
                "Failed to revoke Google tokens for account_id=%s",
                account.pk,
                exc_info=True,
            )
