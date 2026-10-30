from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    def __init__(self, key: str | bytes):
        self._cipher = Fernet(key.encode("ascii") if isinstance(key, str) else key)

    def encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode("ascii")).decode()
        except InvalidToken:
            raise ValueError(
                "Cannot decrypt credentials with the configured key"
            ) from None
