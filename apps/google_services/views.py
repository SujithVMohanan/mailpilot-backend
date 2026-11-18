
import logging
import secrets

from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from apps.google_services.serializer import GmailAccountSerializer
from apps.google_services.services.oauth_service import GoogleOAuthService
from core.responses import ResponseInfo

from apps.google_services.models import GmailAccount

logger = logging.getLogger(__name__)


class OAuthInitiateView(GenericAPIView):

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        state = secrets.token_urlsafe(32)

        request.session["google_oauth_state"] = state

        try:
            auth_url, _ = GoogleOAuthService.get_authorization_url(
                state=state,
            )

            return ResponseInfo.ok(
                data={"authorization_url": auth_url},
                message="Google authorization URL generated successfully.",
            )

        except Exception:
            logger.exception("Google OAuth initiation failed for user_id=%s", request.user.pk)

            return ResponseInfo.server_error(
                message="Unable to initiate Google authentication.",
                error_code="GOOGLE_OAUTH_INIT_FAILED",
            )


class OAuthCallbackView(GenericAPIView):

    serializer_class = GmailAccountSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        code = request.data.get("code")
        state = request.data.get("state")

        if not code or not state:
            return ResponseInfo.validation_error(
                errors={
                    "code": ["Authorization code is required."] if not code else [],
                    "state": ["OAuth state is required."] if not state else [],
                },
                message="Authorization code and state are required.",
            )

        stored_state = request.session.pop("google_oauth_state", None)

        if not stored_state or not secrets.compare_digest(stored_state, state):
            return ResponseInfo.bad_request(
                message="Invalid or expired OAuth state.",
                error_code="INVALID_OAUTH_STATE",
            )

        try:
            account = GoogleOAuthService.exchange_code_for_tokens(
                code=code,
                user=request.user,
                state=state,
            )

            serializer = self.get_serializer(account)

            return ResponseInfo.ok(
                data=serializer.data,
                message="Gmail account connected successfully.",
            )

        except Exception:
            logger.exception("Google OAuth callback failed for user_id=%s", request.user.pk)

            return ResponseInfo.bad_request(
                message="Google authentication failed. Please try again.",
                error_code="GOOGLE_OAUTH_CALLBACK_FAILED",
            )


class DisconnectGmailView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        account = GmailAccount.objects.filter(
            user=request.user,
        ).first()

        if not account:
            return ResponseInfo.not_found(
                message="No connected Gmail account found.",
                error_code="GMAIL_ACCOUNT_NOT_FOUND",
            )

        account.delete()

        return ResponseInfo.ok(
            message="Gmail account disconnected successfully.",
        )
