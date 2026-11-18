
from rest_framework import serializers

from apps.google_services.models import Email



class EmailListSchema(serializers.ModelSerializer):

    class Meta:
        model = Email
        fields = (
            "id",
            "gmail_message_id",
            "sender",
            "recipient",
            "subject",
            "snippet",
            "received_datetime",
            "is_read",
            "label_ids",
        )
        read_only_fields = fields


class EmailDetailSchema(serializers.ModelSerializer):

    class Meta:
        model = Email
        fields = (
            "id",
            "gmail_message_id",
            "thread_id",
            "sender",
            "recipient",
            "subject",
            "snippet",
            "body_text",
            "body_html",
            "received_datetime",
            "is_read",
            "label_ids",
            "created_at",
        )
        read_only_fields = fields
