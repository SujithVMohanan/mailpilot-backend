from django.contrib import admin

from .models import Email, GmailAccount


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



    
@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "sender",
        "subject",
        "received_datetime",
        "is_read",
    )

    list_filter = (
        "is_read",
        "received_datetime",
    )

    search_fields = (
        "sender",
        "recipient",
        "subject",
        "gmail_message_id",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    ordering = (
        "-received_datetime",
    )

    list_per_page = 25