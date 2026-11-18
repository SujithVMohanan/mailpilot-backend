from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.rule.models import EmailRule, RuleAction, RuleCondition

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds standard sample email automation rules demonstrating ALL and ANY logic"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            help="Email address of the user to assign seeded rules to.",
        )

    def handle(self, *args, **options):
        target_email = options.get("email")

        if target_email:
            user = User.objects.filter(email=target_email).first()
            if not user:
                self.stdout.write(
                    self.style.ERROR(f"User with email '{target_email}' does not exist.")
                )
                return
        else:
            user = User.objects.first()
            if not user:
                self.stdout.write(
                    self.style.ERROR("No users found in database. Please register a user first.")
                )
                return

        self.stdout.write(f"Seeding sample automation rules for user: {user.email}")

        # ── Rule 1: Important Invoices (Match ALL / AND) ────────────────────
        rule1, created1 = EmailRule.objects.get_or_create(
            user=user,
            name="Important Invoices & Receipts",
            defaults={
                "description": "Automatically marks emails with invoices or receipts as read",
                "group_predicate": EmailRule.GroupPredicate.ALL,
                "is_active": True,
            },
        )
        if created1:
            RuleCondition.objects.create(
                rule=rule1,
                field=RuleCondition.FieldType.SUBJECT,
                predicate=RuleCondition.PredicateType.CONTAINS,
                value="Invoice",
            )
            RuleCondition.objects.create(
                rule=rule1,
                field=RuleCondition.FieldType.BODY,
                predicate=RuleCondition.PredicateType.CONTAINS,
                value="Payment",
            )
            RuleAction.objects.create(
                rule=rule1,
                action_type=RuleAction.ActionType.MARK_AS_READ,
            )
            self.stdout.write(self.style.SUCCESS(f"  + Created: '{rule1.name}' (Match ALL)"))
        else:
            self.stdout.write(f"  - Already exists: '{rule1.name}'")

        # ── Rule 2: Urgent Alerts (Match ANY / OR) ──────────────────────────
        rule2, created2 = EmailRule.objects.get_or_create(
            user=user,
            name="Urgent Alerts & Outages",
            defaults={
                "description": "Flags critical operational alerts as unread",
                "group_predicate": EmailRule.GroupPredicate.ANY,
                "is_active": True,
            },
        )
        if created2:
            RuleCondition.objects.create(
                rule=rule2,
                field=RuleCondition.FieldType.SUBJECT,
                predicate=RuleCondition.PredicateType.CONTAINS,
                value="Urgent",
            )
            RuleCondition.objects.create(
                rule=rule2,
                field=RuleCondition.FieldType.SUBJECT,
                predicate=RuleCondition.PredicateType.CONTAINS,
                value="Critical",
            )
            RuleCondition.objects.create(
                rule=rule2,
                field=RuleCondition.FieldType.BODY,
                predicate=RuleCondition.PredicateType.CONTAINS,
                value="Incident",
            )
            RuleAction.objects.create(
                rule=rule2,
                action_type=RuleAction.ActionType.MARK_AS_UNREAD,
            )
            self.stdout.write(self.style.SUCCESS(f"  + Created: '{rule2.name}' (Match ANY)"))
        else:
            self.stdout.write(f"  - Already exists: '{rule2.name}'")

        # ── Rule 3: Old Email Cleanup (Date Predicate) ──────────────────────
        rule3, created3 = EmailRule.objects.get_or_create(
            user=user,
            name="Archive Newsletters Older than 30 Days",
            defaults={
                "description": "Auto-marks newsletters older than 30 days as read",
                "group_predicate": EmailRule.GroupPredicate.ALL,
                "is_active": True,
            },
        )
        if created3:
            RuleCondition.objects.create(
                rule=rule3,
                field=RuleCondition.FieldType.SUBJECT,
                predicate=RuleCondition.PredicateType.CONTAINS,
                value="Newsletter",
            )
            RuleCondition.objects.create(
                rule=rule3,
                field=RuleCondition.FieldType.RECEIVED_DATE,
                predicate=RuleCondition.PredicateType.GREATER_THAN,
                value="30",
                unit=RuleCondition.DateUnit.DAYS,
            )
            RuleAction.objects.create(
                rule=rule3,
                action_type=RuleAction.ActionType.MARK_AS_READ,
            )
            self.stdout.write(self.style.SUCCESS(f"  + Created: '{rule3.name}' (Date predicate)"))
        else:
            self.stdout.write(f"  - Already exists: '{rule3.name}'")

        self.stdout.write(self.style.SUCCESS("\nSample rules seeding completed successfully!"))
