
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _



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

    access_token = models.TextField(_("Access Token"),blank=True, null=True)
    refresh_token = models.TextField(
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
            self.token_expiry - timezone.timedelta(minutes=5)
        )
