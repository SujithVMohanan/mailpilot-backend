from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.rule.models import (
    EmailRule,
    RuleAction,
    RuleCondition,
    RuleExecution,
    RuleExecutionLog,
)


class RuleConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleCondition
        fields = (
            "id",
            "field",
            "predicate",
            "value",
            "unit",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        condition = RuleCondition(**attrs)
        try:
            condition.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict or exc.messages
            ) from exc
        return attrs


class RuleActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleAction
        fields = (
            "id",
            "action_type",
            "destination_label_id",
            "destination_label_name",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        action = RuleAction(**attrs)
        try:
            action.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict or exc.messages
            ) from exc
        return attrs


class EmailRuleSerializer(serializers.ModelSerializer):
    conditions = RuleConditionSerializer(many=True, required=False)
    actions = RuleActionSerializer(many=True, required=False)

    class Meta:
        model = EmailRule
        fields = (
            "id",
            "name",
            "description",
            "is_active",
            "group_predicate",
            "conditions",
            "actions",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        is_create = self.instance is None
        conditions = attrs.get("conditions", serializers.empty)
        actions = attrs.get("actions", serializers.empty)

        if is_create or conditions is not serializers.empty:
            if not conditions:
                raise serializers.ValidationError(
                    {"conditions": "At least one condition is required."}
                )

        if is_create or actions is not serializers.empty:
            if not actions:
                raise serializers.ValidationError(
                    {"actions": "At least one action is required."}
                )

        return attrs

    @staticmethod
    def _replace_conditions(rule, conditions):
        rule.conditions.all().delete()
        RuleCondition.objects.bulk_create(
            [
                RuleCondition(rule=rule, **condition)
                for condition in conditions
            ]
        )

    @staticmethod
    def _replace_actions(rule, actions):
        rule.actions.all().delete()
        RuleAction.objects.bulk_create(
            [
                RuleAction(rule=rule, **action)
                for action in actions
            ]
        )

    def create(self, validated_data):
        conditions = validated_data.pop("conditions")
        actions = validated_data.pop("actions")

        with transaction.atomic():
            rule = EmailRule.objects.create(**validated_data)
            self._replace_conditions(rule, conditions)
            self._replace_actions(rule, actions)

        return rule

    def update(self, instance, validated_data):
        conditions = validated_data.pop("conditions", None)
        actions = validated_data.pop("actions", None)

        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)

            instance.save()

            if conditions is not None:
                self._replace_conditions(instance, conditions)

            if actions is not None:
                self._replace_actions(instance, actions)

        return instance


class RuleExecutionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleExecutionLog
        fields = (
            "id",
            "email",
            "action_type",
            "status",
            "error_message",
            "created_at",
        )
        read_only_fields = fields


class RuleExecutionSerializer(serializers.ModelSerializer):
    logs = RuleExecutionLogSerializer(many=True, read_only=True)

    class Meta:
        model = RuleExecution
        fields = (
            "id",
            "rule",
            "rule_name_snapshot",
            "started_at",
            "completed_at",
            "total_evaluated",
            "total_matched",
            "actions_succeeded",
            "actions_failed",
            "status",
            "logs",
        )
        read_only_fields = fields
