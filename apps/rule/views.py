import logging

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from apps.rule.models import EmailRule, RuleExecution
from apps.rule.serializers import (
    EmailRuleSerializer,
    RuleExecutionSerializer,
)
from apps.rule.services.execution_queue import (
    RuleExecutionInProgress,
    RuleExecutionQueueError,
    queue_all_active_rule_executions,
    queue_rule_execution,
)
from core.docs import swagger_auto_schema
from core.responses import ResponseInfo


logger = logging.getLogger(__name__)


class EmailRuleViewSet(viewsets.ModelViewSet):
    serializer_class = EmailRuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            EmailRule.objects.filter(
                user=self.request.user,
            )
            .prefetch_related(
                "conditions",
                "actions",
            )
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return ResponseInfo.ok(
            data=serializer.data,
            message="Rules retrieved successfully.",
        )

    def retrieve(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object())
        return ResponseInfo.ok(
            data=serializer.data,
            message="Rule retrieved successfully.",
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return ResponseInfo.created(
            data=serializer.data,
            message="Rule created successfully.",
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(
            self.get_object(),
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ResponseInfo.ok(
            data=serializer.data,
            message="Rule updated successfully.",
        )

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return ResponseInfo.ok(message="Rule deleted successfully.")

    @action(detail=True, methods=["post"], url_path="toggle")
    def toggle(self, request, pk=None):
        rule = self.get_object()
        rule.is_active = not rule.is_active
        rule.save(update_fields=["is_active", "updated_at"])
        serializer = self.get_serializer(rule)
        return ResponseInfo.ok(
            data=serializer.data,
            message=(
                "Rule enabled."
                if rule.is_active
                else "Rule disabled."
            ),
        )

    @swagger_auto_schema(tags=["Rules"])
    @action(detail=True, methods=["post"], url_path="execute")
    def execute(self, request, pk=None):
        rule = self.get_object()

        try:
            execution = queue_rule_execution(
                user=request.user,
                rule_id=rule.pk,
            )

            if execution is None:
                return ResponseInfo.not_found(
                    message="Rule not found.",
                    error_code="RULE_NOT_FOUND",
                )

            return ResponseInfo.accepted(
                data=RuleExecutionSerializer(execution).data,
                message="Rule execution queued successfully.",
            )

        except RuleExecutionInProgress as exc:
            return ResponseInfo.conflict(
                errors=RuleExecutionSerializer(
                    exc.executions,
                    many=True,
                ).data,
                message="This rule already has an execution queued or running.",
                error_code="RULE_EXECUTION_ALREADY_IN_PROGRESS",
            )

        except RuntimeError as exc:
            logger.warning(
                "Rule execution unavailable for user=%s rule=%s: %s",
                request.user.pk,
                rule.pk,
                exc,
            )

            return ResponseInfo.bad_request(
                message=str(exc),
            )

        except RuleExecutionQueueError:
            logger.exception(
                "Unable to queue rule execution. user=%s rule=%s",
                request.user.pk,
                rule.pk,
            )
            return ResponseInfo.server_error(
                message="Unable to queue rule execution.",
                error_code="RULE_EXECUTION_QUEUE_FAILED",
            )

        except Exception:
            logger.exception(
                "Unable to queue rule execution. user=%s rule=%s",
                request.user.pk,
                rule.pk,
            )

            return ResponseInfo.server_error(
                message="Unable to queue rule execution.",
                error_code="RULE_EXECUTION_QUEUE_FAILED",
            )

    @swagger_auto_schema(tags=["Rules"])
    @action(detail=False, methods=["post"], url_path="execute-all")
    def execute_all(self, request):
        try:
            executions = queue_all_active_rule_executions(
                user=request.user,
            )

            data = RuleExecutionSerializer(
                executions,
                many=True,
            ).data

            return ResponseInfo.accepted(
                data=data,
                message="Rule executions queued successfully.",
            )

        except RuleExecutionInProgress as exc:
            return ResponseInfo.conflict(
                errors=RuleExecutionSerializer(
                    exc.executions,
                    many=True,
                ).data,
                message=(
                    "One or more active rules already have executions "
                    "queued or running."
                ),
                error_code="RULE_EXECUTION_ALREADY_IN_PROGRESS",
            )

        except RuntimeError as exc:
            logger.warning(
                "Bulk rule execution unavailable for user=%s: %s",
                request.user.pk,
                exc,
            )

            return ResponseInfo.bad_request(
                message=str(exc),
            )

        except RuleExecutionQueueError:
            logger.exception(
                "Unable to queue bulk rule executions. user=%s",
                request.user.pk,
            )
            return ResponseInfo.server_error(
                message="Unable to queue rule executions.",
                error_code="RULE_EXECUTION_QUEUE_FAILED",
            )

        except Exception:
            logger.exception(
                "Unable to queue bulk rule executions. user=%s",
                request.user.pk,
            )

            return ResponseInfo.server_error(
                message="Unable to queue rule executions.",
                error_code="RULE_EXECUTION_QUEUE_FAILED",
            )


class RuleExecutionListView(ListAPIView):
    
    serializer_class   = RuleExecutionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            RuleExecution.objects.filter(
                user=self.request.user,
            )
            .select_related("rule")
            .prefetch_related("logs")
            .order_by("-started_at")
        )

        rule_id = self.request.query_params.get("rule")
        if rule_id:
            queryset = queryset.filter(rule_id=rule_id)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return ResponseInfo.ok(
            data=serializer.data,
            message="Execution history retrieved successfully.",
        )
