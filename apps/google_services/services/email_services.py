
from django.db.models import Count, Q

from apps.google_services.models import (
    Email,
    GmailAccount
)
from apps.rule.models import EmailRule, RuleExecution


class EmailQueryService:

    ALLOWED_ORDERINGS = {
        "received_datetime",
        "-received_datetime",
        "subject",
        "-subject",
    }

    @staticmethod
    def get_account(user):
        return GmailAccount.objects.filter(
            user=user,
            is_active=True,
        ).first()

    @classmethod
    def get_emails(cls, user, params):
        account = cls.get_account(user)

        if not account:
            return Email.objects.none()

        queryset = Email.objects.filter(account=account)

        search = params.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(subject__icontains=search)
                | Q(sender__icontains=search)
                | Q(recipient__icontains=search)
                | Q(snippet__icontains=search)
                | Q(body_text__icontains=search)
            )

        is_read = params.get("is_read")

        if is_read not in (None, ""):
            value = is_read.lower()

            if value not in {"true", "false", "1", "0"}:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({
                    "is_read": "Use true, false, 1 or 0."
                })

            queryset = queryset.filter(
                is_read=value in {"true", "1"}
            )

        ordering = params.get(
            "ordering",
            "-received_datetime",
        )

        if ordering not in cls.ALLOWED_ORDERINGS:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({
                "ordering": "Unsupported ordering field."
            })

        return queryset.order_by(ordering, "-id")


class DashboardService:
    """Generate dashboard statistics for the authenticated user."""

    @staticmethod
    def get_stats(user):
        account = EmailQueryService.get_account(user)

        total_emails = 0
        read_emails = 0
        unread_emails = 0

        if account:
            stats = Email.objects.filter(
                account=account
            ).aggregate(
                total=Count("id"),
                read=Count("id", filter=Q(is_read=True)),
                unread=Count("id", filter=Q(is_read=False)),
            )

            total_emails = stats["total"]
            read_emails = stats["read"]
            unread_emails = stats["unread"]

        rule_stats = EmailRule.objects.filter(user=user).aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
        )

        recent_executions = list(
            RuleExecution.objects.filter(user=user)
            .order_by("-started_at")
            .values(
                "id",
                "rule_id",
                "rule_name_snapshot",
                "status",
                "total_evaluated",
                "total_matched",
                "actions_succeeded",
                "actions_failed",
                "started_at",
                "completed_at",
            )[:10]
        )

        return {
            "account": {
                "connected": account is not None,
                "email_address": (
                    account.email_address if account else None
                ),
                "last_synced_at": (
                    account.last_synced_at if account else None
                ),
            },
            "total_emails": total_emails,
            "read_emails": read_emails,
            "unread_emails": unread_emails,
            "total_rules": rule_stats["total"],
            "active_rules": rule_stats["active"],
            "recent_executions": recent_executions,
        }
