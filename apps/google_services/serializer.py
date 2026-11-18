
from rest_framework import serializers

from apps.google_services.models import GmailAccount


class GmailAccountSerializer(serializers.ModelSerializer):

    class Meta:
        model = GmailAccount

        fields = (
            "id",
            "email_address",
            "last_synced_at",
            "is_active",
            "created_at",
        )

        read_only_fields = fields
