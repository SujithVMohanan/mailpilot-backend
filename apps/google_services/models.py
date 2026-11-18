
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.encryption.secret_fields import EncryptedTextField



class GmailAccount(models.Model):
    

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gmail_account",
    )

    email_address = models.EmailField(_("Email Address"),
        max_length=255,
        db_index=True,
    )

    access_token = EncryptedTextField(_("Access Token"), blank=True, null=True)
    refresh_token = EncryptedTextField(
        _("Refresh Token"),
        blank=True,
        null=True,
    )

    token_expiry = models.DateTimeField(_("Token Expiry"),
        blank=True,
        null=True,
    )

    scopes = models.JSONField(
        _("Scopes"),
        default=list,
        blank=True,
    )

    last_synced_at = models.DateTimeField(_("Last Synced At"),
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(_("Is Active"),
        default=True,
        db_index=True,
    )

    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)

    class Meta:
        db_table = "google_gmail_accounts"
        ordering = ["-id"]
        indexes = [
            models.Index(
                fields=["is_active", "token_expiry"],
                name="gmail_active_expiry_idx",
            ),
        ]

    def __str__(self):
        return f"{self.email_address} (User ID: {self.user_id})"

    @property
    def is_token_expired(self):
        if not self.token_expiry:
            return True

        return timezone.now() >= self.token_expiry

    @property
    def needs_token_refresh(self):
        if not self.token_expiry:
            return True

        return timezone.now() >= (
            self.token_expiry - timedelta(minutes=5)
        )



class Email(models.Model):
    
    account = models.ForeignKey(
        GmailAccount,
        on_delete=models.CASCADE,
        related_name="emails",
    )

    gmail_message_id = models.CharField(
        _("Gmail Message ID"),
        max_length=100,
    )
    thread_id = models.CharField(
        _("Thread ID"),
        max_length=100,
        blank=True,
        default="",
    )

    sender = models.CharField(
        _("Sender"),
        max_length=320,
        blank=True,
        default="",
    )
    recipient = models.TextField(
        _("Recipient"),
        blank=True,
        default="",
    )
    subject = models.TextField(
        _("Subject"),
        blank=True,
        default="",
    )
    snippet = models.TextField(
        _("Snippet"),
        blank=True,
        default="",
    )

    body_text = models.TextField(
        _("Text Body"),
        blank=True,
        default="",
    )
    body_html = models.TextField(
        _("HTML Body"),
        blank=True,
        default="",
    )

    received_datetime = models.DateTimeField(
        _("Received Date"),
        db_index=True,
    )

    is_read = models.BooleanField(
        _("Is Read"),
        default=False,
        db_index=True,
    )

    label_ids = models.JSONField(
        _("Label IDs"),
        default=list,
        blank=True,
    )

    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        _("Updated At"),
        auto_now=True,
    )

    class Meta:
        db_table = "emails"
        ordering = ["-received_datetime"]

        constraints = [
            models.UniqueConstraint(
                fields=["account", "gmail_message_id"],
                name="unique_account_gmail_message",
            ),
        ]

        indexes = [
            models.Index(
                fields=["account", "received_datetime"],
                name="email_account_date_idx",
            ),
            models.Index(
                fields=["account", "is_read"],
                name="email_account_read_idx",
            ),
        ]

    def __str__(self):
        return f"{self.subject[:40]} | From: {self.sender[:30]}"
