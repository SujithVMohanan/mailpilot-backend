from django.contrib import admin

from apps.rule.models import (
    EmailRule,
    RuleAction,
    RuleCondition,
    RuleExecution,
    RuleExecutionLog,
    RuleProcessedEmail,
)


class RuleConditionInline(admin.TabularInline):
    model = RuleCondition
    extra = 0


class RuleActionInline(admin.TabularInline):
    model = RuleAction
    extra = 0


@admin.register(EmailRule)
class EmailRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "group_predicate", "is_active", "created_at")
    list_filter = ("is_active", "group_predicate")
    search_fields = ("name", "user__email")
    inlines = (RuleConditionInline, RuleActionInline)


@admin.register(RuleExecution)
class RuleExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "rule_name_snapshot",
        "status",
        "total_matched",
        "started_at",
    )
    list_filter = ("status",)


admin.site.register(RuleExecutionLog)
admin.site.register(RuleProcessedEmail)
