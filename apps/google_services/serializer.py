
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



class EmailSyncSerializer(serializers.Serializer):
    
    max_results = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=100,
    )

    page_token = serializers.CharField(
        required=False,
        allow_blank=False,
        allow_null=False,
    )
