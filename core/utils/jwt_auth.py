from typing import Any

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import Token


class JWTAccessBlacklistAuthentication(JWTAuthentication):

    def get_user(self, validated_token: Token) -> Any:
        user = super().get_user(validated_token)

        if user is None or not user.is_active:
            raise InvalidToken("User is inactive or deleted.")

        return user