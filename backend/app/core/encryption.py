"""敏感信息加密"""

from cryptography.fernet import Fernet
from app.config import settings


class EncryptionService:
    """加密服务，用于加密存储 APIKey 等敏感信息"""

    def __init__(self):
        self._fernet = Fernet(settings.encryption_key.encode())

    def encrypt(self, plaintext: str) -> str:
        """加密"""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """解密"""
        return self._fernet.decrypt(ciphertext.encode()).decode()


encryption_service = EncryptionService()
