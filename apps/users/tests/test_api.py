from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core.encryption.ids import encode_id
from core.utils.tokens import issue_tokens


User = get_user_model()


class UserApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            password="User-password-4892!",
            full_name="Test User",
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="Admin-password-4892!",
        )

    def authenticate(self, user=None):
        token = issue_tokens(user or self.user)["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return token

    def test_register_creates_user_and_returns_tokens(self):
        response = self.client.post(
            "/api/users/register/",
            {
                "email": "new@example.com",
                "full_name": "New User",
                "password": "New-user-password-4892!",
                "confirm_password": "New-user-password-4892!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])
        self.assertEqual(response.data["data"]["user"]["email"], "new@example.com")

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/api/users/register/",
            {
                "email": "new@example.com",
                "password": "New-user-password-4892!",
                "confirm_password": "Different-password-4892!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data["errors"])

    def test_register_rejects_duplicate_email(self):
        response = self.client.post(
            "/api/users/register/",
            {
                "email": self.user.email,
                "password": "New-user-password-4892!",
                "confirm_password": "New-user-password-4892!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_returns_access_and_refresh_tokens(self):
        response = self.client.post(
            "/api/users/login/",
            {"email": self.user.email, "password": "User-password-4892!"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])
        self.assertEqual(response.data["data"]["user"]["uid"], encode_id(self.user.pk, "users.user"))

    def test_login_rejects_invalid_password(self):
        response = self.client.post(
            "/api/users/login/",
            {"email": self.user.email, "password": "not-the-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_rotates_tokens(self):
        refresh = str(RefreshToken.for_user(self.user))
        response = self.client.post(
            "/api/users/refresh/",
            {"refresh": refresh},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])
        self.assertNotEqual(response.data["data"]["refresh"], refresh)

    def test_refresh_rejects_invalid_token(self):
        response = self.client.post(
            "/api/users/refresh/",
            {"refresh": "not-a-refresh-token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_requires_authentication(self):
        response = self.client.post(
            "/api/users/logout/",
            {"refresh": str(RefreshToken.for_user(self.user))},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token(self):
        tokens = issue_tokens(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        response = self.client.post(
            "/api/users/logout/",
            {"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        refresh_response = self.client.post(
            "/api/users/refresh/",
            {"refresh": tokens["refresh"]},
            format="json",
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_requires_authentication_and_returns_current_user(self):
        self.assertEqual(
            self.client.get("/api/users/me/").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.authenticate()
        response = self.client.get("/api/users/me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["email"], self.user.email)

    def test_get_users_is_admin_only_and_supports_email_filter(self):
        self.assertEqual(
            self.client.get("/api/users/get-users/").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.authenticate()
        self.assertEqual(
            self.client.get("/api/users/get-users/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.authenticate(self.admin)
        response = self.client.get("/api/users/get-users/?email=user@example.com")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertEqual([result["email"] for result in results], [self.user.email])

    def test_delete_users_deactivates_account(self):
        self.authenticate(self.admin)
        uid = encode_id(self.user.pk, User._meta.label_lower)
        response = self.client.delete(
            "/api/users/delete-users/",
            {"uids": [uid]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(response.data["data"]["deleted"], 1)

    def test_delete_users_rejects_self_deletion(self):
        self.authenticate(self.admin)
        uid = encode_id(self.admin.pk, User._meta.label_lower)
        response = self.client.delete(
            "/api/users/delete-users/",
            {"uids": [uid]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
