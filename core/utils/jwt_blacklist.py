from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


def blacklist_refresh_token(raw_refresh: str) -> None:
    RefreshToken(raw_refresh).blacklist()


def logout_tokens(*, refresh_token: str | None = None) -> None:
    if not refresh_token:
        raise TokenError("Refresh token is required.")

    try:
        blacklist_refresh_token(refresh_token)
    except TokenError as exc:
        raise TokenError("Refresh token is invalid or already expired.") from exc