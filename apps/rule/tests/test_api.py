from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.rule.models import EmailRule, RuleExecution
from core.utils.tokens import issue_tokens


User = get_user_model()


class RuleApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="rules@example.com",
            password="Rules-password-4892!",
        )
        self.other_user = User.objects.create_user(
            email="other-rules@example.com",
            password="Other-rules-password-4892!",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_tokens(self.user)['access']}"
        )

    @staticmethod
    def rule_payload(name="Project messages"):
        return {
            "name": name,
            "description": "Handle project updates",
            "is_active": True,
            "group_predicate": "ALL",
            "conditions": [
                {
                    "field": "SUBJECT",
                    "predicate": "CONTAINS",
                    "value": "project",
                    "unit": "",
                }
            ],
            "actions": [
                {
                    "action_type": "MARK_AS_READ",
                    "destination_label_id": "",
                    "destination_label_name": "",
                }
            ],
        }

    def create_rule(self, user=None, name="Existing rule"):
        return EmailRule.objects.create(user=user or self.user, name=name)

    def test_rule_endpoints_require_authentication(self):
        self.client.credentials()
        response = self.client.get("/api/rules/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_rule_returns_nested_conditions_and_actions(self):
        response = self.client.post(
            "/api/rules/",
            self.rule_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "Project messages")
        self.assertEqual(len(response.data["data"]["conditions"]), 1)
        self.assertEqual(len(response.data["data"]["actions"]), 1)
        self.assertTrue(
            EmailRule.objects.filter(
                user=self.user,
                name="Project messages",
            ).exists()
        )

    def test_create_rule_requires_condition_and_action(self):
        payload = self.rule_payload()
        payload["conditions"] = []

        response = self.client.post("/api/rules/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("conditions", response.data["errors"])

    def test_create_rule_rejects_move_action_without_destination(self):
        payload = self.rule_payload()
        payload["actions"][0] = {
            "action_type": "MOVE_MESSAGE",
            "destination_label_id": "",
            "destination_label_name": "",
        }

        response = self.client.post("/api/rules/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("actions", response.data["errors"])

    def test_list_rules_only_returns_current_users_rules(self):
        own_rule = self.create_rule()
        self.create_rule(user=self.other_user, name="Other user's rule")

        response = self.client.get("/api/rules/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [item["id"] for item in response.data["data"]["results"]]
        self.assertEqual(result_ids, [own_rule.pk])

    def test_retrieve_rule_and_prevent_cross_user_access(self):
        own_rule = self.create_rule()
        other_rule = self.create_rule(user=self.other_user)

        response = self.client.get(f"/api/rules/{own_rule.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], own_rule.pk)

        response = self.client.get(f"/api/rules/{other_rule.pk}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_rule_and_replace_conditions(self):
        response = self.client.post(
            "/api/rules/",
            self.rule_payload(),
            format="json",
        )
        rule_id = response.data["data"]["id"]
        payload = self.rule_payload(name="Updated project rule")
        payload["conditions"][0]["value"] = "invoice"

        response = self.client.put(
            f"/api/rules/{rule_id}/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["name"], "Updated project rule")
        self.assertEqual(response.data["data"]["conditions"][0]["value"], "invoice")

    def test_partial_update_rule(self):
        rule = self.create_rule()
        response = self.client.patch(
            f"/api/rules/{rule.pk}/",
            {"name": "Renamed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["name"], "Renamed")

    def test_delete_rule(self):
        rule = self.create_rule()
        response = self.client.delete(f"/api/rules/{rule.pk}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(EmailRule.objects.filter(pk=rule.pk).exists())

    def test_toggle_rule_changes_active_state(self):
        rule = self.create_rule()
        response = self.client.post(f"/api/rules/{rule.pk}/toggle/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    @patch("apps.rule.views.RuleExecutionOrchestrator")
    def test_execute_rule_returns_execution(self, orchestrator_class):
        rule = self.create_rule()
        execution = RuleExecution.objects.create(
            user=self.user,
            rule=rule,
            rule_name_snapshot=rule.name,
            status=RuleExecution.ExecutionStatus.SUCCESS,
        )
        orchestrator_class.return_value.execute_rule.return_value = execution

        response = self.client.post(f"/api/rules/{rule.pk}/execute/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], execution.pk)

    @patch("apps.rule.views.RuleExecutionOrchestrator")
    def test_execute_rule_returns_bad_request_when_unavailable(self, orchestrator_class):
        rule = self.create_rule()
        orchestrator_class.return_value.execute_rule.side_effect = RuntimeError(
            "Gmail account is not connected."
        )

        response = self.client.post(f"/api/rules/{rule.pk}/execute/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("apps.rule.views.RuleExecutionOrchestrator")
    def test_execute_all_returns_execution_list(self, orchestrator_class):
        rule = self.create_rule()
        execution = RuleExecution.objects.create(
            user=self.user,
            rule=rule,
            rule_name_snapshot=rule.name,
            status=RuleExecution.ExecutionStatus.SUCCESS,
        )
        orchestrator_class.return_value.execute_all_active_rules.return_value = [
            execution
        ]

        response = self.client.post("/api/rules/execute-all/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data["data"]], [execution.pk])

    def test_execution_history_filters_by_rule_and_user(self):
        own_rule = self.create_rule()
        other_rule = self.create_rule(user=self.other_user)
        own_execution = RuleExecution.objects.create(
            user=self.user,
            rule=own_rule,
            rule_name_snapshot=own_rule.name,
            status=RuleExecution.ExecutionStatus.SUCCESS,
        )
        RuleExecution.objects.create(
            user=self.user,
            rule=self.create_rule(name="Second own rule"),
            status=RuleExecution.ExecutionStatus.FAILED,
        )
        RuleExecution.objects.create(
            user=self.other_user,
            rule=other_rule,
            status=RuleExecution.ExecutionStatus.SUCCESS,
        )

        response = self.client.get(f"/api/rules/executions/?rule={own_rule.pk}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertEqual([item["id"] for item in results], [own_execution.pk])

    def test_execution_history_requires_authentication(self):
        self.client.credentials()
        response = self.client.get("/api/rules/executions/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
