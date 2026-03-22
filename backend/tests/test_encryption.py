"""加密服务测试"""

import pytest
from app.core.encryption import encryption_service


def test_encrypt_decrypt():
    """测试加密解密可逆"""
    plaintext = "test-api-key-123"
    ciphertext = encryption_service.encrypt(plaintext)
    decrypted = encryption_service.decrypt(ciphertext)
    assert decrypted == plaintext


def test_encrypt_different():
    """不同明文加密后密文不同"""
    text1 = "text1"
    text2 = "text2"
    cipher1 = encryption_service.encrypt(text1)
    cipher2 = encryption_service.encrypt(text2)
    assert cipher1 != cipher2
