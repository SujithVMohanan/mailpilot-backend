
from django.db.models import Count, Q

from apps.google_services.models import (
    Email,
    GmailAccount
)


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

        rules = getattr(user, "email_rules", None)

        total_rules = rules.count() if rules is not None else 0

        active_rules = (
            rules.filter(is_active=True).count()
            if rules is not None
            else 0
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
            "total_rules": total_rules,
            "active_rules": active_rules,
            "recent_executions": [],
        }
