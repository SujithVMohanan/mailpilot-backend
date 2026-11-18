
import logging
import secrets

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.views import APIView
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    RetrieveAPIView,
)
from rest_framework.permissions import IsAuthenticated

from apps.google_services.models import Email, GmailAccount
from apps.google_services.schemas import (
    EmailDetailSchema,
    EmailListSchema,
)
from apps.google_services.serializer import (
    EmailSyncSerializer,
    GmailAccountSerializer,
)
from apps.google_services.services.email_services import (
    DashboardService,
    EmailQueryService,
)
from apps.google_services.services.gmail_client import GmailClient
from apps.google_services.services.oauth_service import GoogleOAuthService
from apps.google_services.services.sync_scheduler import (
    enqueue_gmail_sync,
    get_sync_status_data,
)
from core.responses import ResponseInfo

logger = logging.getLogger(__name__)



class OAuthInitiateView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        tags=["Gmail OAuth"],
        operation_summary="Initiate Google OAuth",
        operation_description=(
            "Generate a Google authorization URL to connect "
            "the authenticated user's Gmail account."
        ),
        responses={
            200: "Authorization URL generated successfully.",
            500: "Unable to initiate Google authentication.",
        },
    )
    def get(self, request, *args, **kwargs):
        state = secrets.token_urlsafe(32)

        try:
            auth_url, _, code_verifier = GoogleOAuthService.get_authorization_url(
                state=state,
            )
            GoogleOAuthService.store_oauth_state(
                request.user.pk,
                state,
                code_verifier,
            )

            return ResponseInfo.ok(
                data={"authorization_url": auth_url},
                message="Google authorization URL generated successfully.",
            )

        except Exception:
            logger.exception(
                "Google OAuth initiation failed for user_id=%s",
                request.user.pk,
            )

            return ResponseInfo.server_error(
                message="Unable to initiate Google authentication.",
                error_code="GOOGLE_OAUTH_INIT_FAILED",
            )


class OAuthCallbackView(GenericAPIView):
    serializer_class = GmailAccountSerializer
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        tags=["Gmail OAuth"],
        operation_summary="Complete Google OAuth",
        operation_description=(
            "Exchange the Google authorization code for tokens "
            "and connect the Gmail account."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["code", "state"],
            properties={
                "code": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="Google authorization code.",
                ),
                "state": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description="OAuth state received during initiation.",
                ),
            },
        ),
        responses={
            200: "Gmail account connected successfully.",
            400: "Invalid OAuth state or authentication failure.",
            500: "Unexpected server error.",
        },
    )
    def post(self, request, *args, **kwargs):
        code = request.data.get("code")
        state = request.data.get("state")

        if not code or not state:
            return ResponseInfo.validation_error(
                errors={
                    "code": (
                        ["Authorization code is required."]
                        if not code else []
                    ),
                    "state": (
                        ["OAuth state is required."]
                        if not state else []
                    ),
                },
                message="Authorization code and state are required.",
            )

        code_verifier = GoogleOAuthService.validate_oauth_state(
            request.user.pk,
            state,
        )

        if not code_verifier:
            return ResponseInfo.bad_request(
                message="Invalid or expired OAuth state.",
                error_code="INVALID_OAUTH_STATE",
            )

        try:
            account = GoogleOAuthService.exchange_code_for_tokens(
                code=code,
                user=request.user,
                state=state,
                code_verifier=code_verifier,
            )

            serializer = self.get_serializer(account)

            return ResponseInfo.ok(
                data=serializer.data,
                message="Gmail account connected successfully.",
            )

        except Exception as exc:
            logger.exception(
                "Google OAuth callback failed for user_id=%s: %s",
                request.user.pk,
                exc,
            )

            return ResponseInfo.bad_request(
                message=f"Google authentication failed: {str(exc)}",
                error_code="GOOGLE_OAUTH_CALLBACK_FAILED",
            )



class DisconnectGmailView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        tags=["Gmail Account"],
        operation_summary="Disconnect Gmail account",
        operation_description=(
            "Disconnect the Gmail account belonging to the authenticated user."
        ),
        responses={
            200: "Gmail account disconnected successfully.",
            404: "No connected Gmail account found.",
        },
    )
    def post(self, request, *args, **kwargs):
        account = GmailAccount.objects.filter(
            user=request.user,
        ).first()

        if not account:
            return ResponseInfo.not_found(
                message="No connected Gmail account found.",
                error_code="GMAIL_ACCOUNT_NOT_FOUND",
            )

        GoogleOAuthService.revoke_account_tokens(account)
        account.delete()

        return ResponseInfo.ok(
            message="Gmail account disconnected successfully.",
        )


class GmailLabelsView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        tags=["Gmail"],
        operation_summary="List Gmail labels",
        operation_description=(
            "Retrieve Gmail labels for the authenticated user's active account."
        ),
        responses={
            200: "Gmail labels retrieved successfully.",
            404: "No active Gmail account found.",
            500: "Unable to retrieve Gmail labels.",
        },
    )
    def get(self, request, *args, **kwargs):
        account = GmailAccount.objects.filter(
            user=request.user,
            is_active=True,
        ).first()

        if not account:
            return ResponseInfo.not_found(
                message="No active Gmail account found.",
                error_code="GMAIL_ACCOUNT_NOT_FOUND",
            )

        try:
            labels = GmailClient(account).list_labels()

            return ResponseInfo.ok(
                data={"labels": labels},
                message="Gmail labels retrieved successfully.",
            )

        except Exception:
            logger.exception(
                "Gmail label retrieval failed for user_id=%s",
                request.user.pk,
            )

            return ResponseInfo.server_error(
                message="Unable to retrieve Gmail labels.",
                error_code="GMAIL_LABELS_FAILED",
            )



class SyncEmailsView(GenericAPIView):
    serializer_class = EmailSyncSerializer
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        tags=["Gmail Emails"],
        operation_summary="Get Gmail synchronization status",
        operation_description=(
            "Return the authenticated user's Gmail synchronization status."
        ),
        responses={
            200: "Synchronization status retrieved successfully.",
            404: "No active Gmail account found.",
        },
    )
    def get(self, request, *args, **kwargs):
        account = GmailAccount.objects.filter(
            user=request.user,
            is_active=True,
        ).first()

        if not account:
            return ResponseInfo.not_found(
                message="No active Gmail account found.",
                error_code="GMAIL_ACCOUNT_NOT_FOUND",
            )

        return ResponseInfo.ok(
            data=get_sync_status_data(account),
            message="Gmail synchronization status retrieved successfully.",
        )

    @swagger_auto_schema(
        tags=["Gmail Emails"],
        operation_summary="Synchronize Gmail emails",
        operation_description=(
            "Queue an immediate Gmail synchronization for the connected "
            "account. The request returns while the sync runs in the "
            "background."
        ),
        request_body=EmailSyncSerializer,
        responses={
            202: "Email synchronization queued successfully.",
            409: "A synchronization is already queued or running.",
            400: "Invalid synchronization parameters.",
            404: "No active Gmail account found.",
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return ResponseInfo.validation_error(
                errors=serializer.errors,
                message="Invalid email synchronization parameters.",
            )

        account = GmailAccount.objects.filter(
            user=request.user,
            is_active=True,
        ).first()

        if not account:
            return ResponseInfo.not_found(
                message="No active Gmail account found.",
                error_code="GMAIL_ACCOUNT_NOT_FOUND",
            )

        try:
            account, outcome = enqueue_gmail_sync(
                account.pk,
                trigger=GmailAccount.SyncTrigger.MANUAL,
                max_results=serializer.validated_data["max_results"],
                page_token=serializer.validated_data.get("page_token"),
            )
        except Exception:
            logger.exception(
                "Unable to queue manual Gmail sync for account_id=%s",
                account.pk,
            )
            return ResponseInfo.server_error(
                message="Unable to queue Gmail synchronization.",
                error_code="EMAIL_SYNC_QUEUE_FAILED",
            )

        if outcome == "already_in_progress":
            return ResponseInfo.conflict(
                errors=get_sync_status_data(account),
                message="Gmail synchronization is already queued or running.",
                error_code="EMAIL_SYNC_ALREADY_IN_PROGRESS",
            )

        if outcome != "queued":
            return ResponseInfo.not_found(
                message="No active Gmail account found.",
                error_code="GMAIL_ACCOUNT_NOT_FOUND",
            )

        return ResponseInfo.accepted(
            data=get_sync_status_data(account),
            message="Gmail synchronization queued successfully.",
        )


class EmailListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmailListSchema

    @swagger_auto_schema(
        tags=["Gmail Emails"],
        operation_summary="List Gmail emails",
        operation_description=(
            "Retrieve paginated emails with search, read/unread filters "
            "and sorting."
        ),
        manual_parameters=[
            openapi.Parameter(
                "search",
                openapi.IN_QUERY,
                description="Search by subject, sender, recipient or email body.",
                type=openapi.TYPE_STRING,
            ),
            openapi.Parameter(
                "is_read",
                openapi.IN_QUERY,
                description="Filter emails by read status.",
                type=openapi.TYPE_BOOLEAN,
            ),
            openapi.Parameter(
                "ordering",
                openapi.IN_QUERY,
                description="Sort by received_datetime or subject. Prefix with - for descending.",
                type=openapi.TYPE_STRING,
                enum=[
                    "received_datetime",
                    "-received_datetime",
                    "subject",
                    "-subject",
                ],
            ),
            openapi.Parameter(
                "page",
                openapi.IN_QUERY,
                description="Page number.",
                type=openapi.TYPE_INTEGER,
            ),
            openapi.Parameter(
                "limit",
                openapi.IN_QUERY,
                description="Number of emails per page (maximum 100).",
                type=openapi.TYPE_INTEGER,
            ),
        ],
        responses={
            200: "Emails retrieved successfully.",
            401: "Authentication required.",
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Email.objects.none()

        return EmailQueryService.get_emails(
            user=self.request.user,
            params=self.request.query_params,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_data = self.get_paginated_response(
                serializer.data,
            ).data

            return ResponseInfo.ok(
                data=paginated_data["data"],
                message="Emails retrieved successfully.",
            )

        serializer = self.get_serializer(queryset, many=True)

        return ResponseInfo.ok(
            data=serializer.data,
            message="Emails retrieved successfully.",
        )



class EmailDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = EmailDetailSchema

    @swagger_auto_schema(
        tags=["Gmail Emails"],
        operation_summary="Retrieve email details",
        operation_description=(
            "Retrieve the complete details of an email, including its body."
        ),
        responses={
            200: EmailDetailSchema,
            404: "Email not found.",
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Email.objects.none()

        return EmailQueryService.get_emails(
            user=self.request.user,
            params={},
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return ResponseInfo.ok(
            data=serializer.data,
            message="Email details retrieved successfully.",
        )



class DashboardStatsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = None

    @swagger_auto_schema(
        tags=["Dashboard"],
        operation_summary="Get dashboard statistics",
        operation_description=(
            "Retrieve Gmail connection status, email counts, "
            "email rules and recent execution statistics."
        ),
        responses={
            200: "Dashboard statistics retrieved successfully.",
            401: "Authentication required.",
        },
    )
    def get(self, request, *args, **kwargs):
        data = DashboardService.get_stats(request.user)

        return ResponseInfo.ok(
            data=data,
            message="Dashboard statistics retrieved successfully.",
        )
