from django.contrib import admin

from .models import GmailAccount


@admin.register(GmailAccount)
class GmailAccountAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "email_address",
        "is_active",
        "token_expiry",
        "last_synced_at",
        "created_at",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    search_fields = (
        "email_address",
        "user__username",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = ("-id",)