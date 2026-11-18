import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class EncryptedTextField(models.TextField):
    """Fernet-encrypted text. Reads legacy plaintext values without failing."""

    PREFIX = "enc:"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)

        if value in (None, ""):
            return value

        if isinstance(value, bytes):
            value = value.decode("utf-8")

        if value.startswith(self.PREFIX):
            return value

        token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
        return f"{self.PREFIX}{token}"

    def from_db_value(self, value, expression, connection):
        return self._decrypt(value)

    def to_python(self, value):
        return self._decrypt(value)

    def _decrypt(self, value):
        if value in (None, ""):
            return value

        if isinstance(value, bytes):
            value = value.decode("utf-8")

        if not value.startswith(self.PREFIX):
            return value

        try:
            return _fernet().decrypt(value[len(self.PREFIX):].encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return value
