import base64
from datetime import datetime, timedelta
from typing import Any, Union, Optional

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


ALGORITHM = "HS256"
passphrase = "weneedtocrud"

def create_access_token(user_id: str, username: Optional[str] = None, expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "exp": expire,
        "user_id": str(user_id),
    }
    encoded_jwt = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def decrypt_api_key(encrypted_text: str, key: str = passphrase) -> str:
    """Декодирование XOR с кодовым словом"""
    decrypted = base64.urlsafe_b64decode(encrypted_text).decode()
    return ''.join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(decrypted))

