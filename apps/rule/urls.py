from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rule.views import EmailRuleViewSet, RuleExecutionListView


app_name = "rule"

router = DefaultRouter()
router.register(r"", EmailRuleViewSet, basename="email-rule")

urlpatterns = [
    path(
        "executions/",
        RuleExecutionListView.as_view(),
        name="rule-execution-list",
    ),
    path("", include(router.urls)),
]
