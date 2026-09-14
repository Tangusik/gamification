"""Тесты проверки access-токена.

Каждый тест соответствует одному способу подсунуть сервису токен,
которому доверять нельзя.
"""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gamification_auth import (
    TokenClaimsError,
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
)

ALGORITHM = "RS256"
AUDIENCE = ["fastapi-users:auth"]
SUBJECT = "3f2b1c4d-0000-4000-8000-000000000001"


def _keypair() -> tuple[str, str]:
    """Сгенерировать пару ключей для подписи и проверки."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


# Пара ключей на весь прогон: генерация RSA заметно дороже самих тестов.
PRIVATE_KEY, PUBLIC_KEY = _keypair()
FOREIGN_PRIVATE_KEY, _FOREIGN_PUBLIC_KEY = _keypair()


def _payload(**overrides: Any) -> dict[str, Any]:
    """Нагрузка валидного токена с возможностью подменить поля."""
    payload: dict[str, Any] = {
        "sub": SUBJECT,
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": "11111111-2222-4333-8444-555555555555",
        "role": "teacher",
        "institution_id": None,
    }
    payload.update(overrides)
    return payload


def _encode(payload: dict[str, Any], key: str = PRIVATE_KEY) -> str:
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def _decode(token: str) -> Any:
    return decode_access_token(
        token, public_key=PUBLIC_KEY, algorithms=[ALGORITHM], audience=AUDIENCE
    )


def test_valid_token_returns_claims() -> None:
    """Валидный токен разбирается в claims активного контекста."""
    claims = _decode(_encode(_payload()))

    assert claims.subject == SUBJECT
    assert claims.role == "teacher"
    assert claims.institution_id is None
    assert claims.token_id == "11111111-2222-4333-8444-555555555555"
    assert claims.expires_at > datetime.now(UTC)


def test_token_without_exp_rejected() -> None:
    """Токен без срока не принимается, даже с верной подписью.

    Главное, ради чего заведена библиотека: PyJWT проверяет ``exp``
    только если он есть, поэтому бессрочный токен прошёл бы насквозь.
    """
    payload = _payload()
    del payload["exp"]

    with pytest.raises(TokenClaimsError):
        _decode(_encode(payload))


def test_token_without_sub_rejected() -> None:
    """Токен без субъекта не принимается: предъявителя не установить."""
    payload = _payload()
    del payload["sub"]

    with pytest.raises(TokenClaimsError):
        _decode(_encode(payload))


def test_expired_token_rejected() -> None:
    """Просроченный токен отличается от невалидного отдельным типом."""
    token = _encode(_payload(exp=datetime.now(UTC) - timedelta(seconds=1)))

    with pytest.raises(TokenExpiredError):
        _decode(token)


def test_foreign_signature_rejected() -> None:
    """Токен, подписанный чужим ключом, не принимается."""
    with pytest.raises(TokenInvalidError):
        _decode(_encode(_payload(), key=FOREIGN_PRIVATE_KEY))


def test_foreign_audience_rejected() -> None:
    """Токен для другой аудитории не открывает наши эндпоинты."""
    with pytest.raises(TokenInvalidError):
        _decode(_encode(_payload(aud=["some-other:audience"])))


def test_missing_audience_rejected() -> None:
    """Токен вовсе без ``aud`` тоже не проходит."""
    payload = _payload()
    del payload["aud"]

    with pytest.raises(TokenClaimsError):
        _decode(_encode(payload))


def _forge_hs256(payload: dict[str, Any], secret: str) -> str:
    """Собрать HS256-токен в обход PyJWT.

    Своим энкодером PyJWT такой токен собрать не даёт — он отказывается
    брать PEM-ключ как HMAC-секрет. Атакующий этим ограничением не
    связан, поэтому токен куётся вручную: заголовок, нагрузка, подпись.
    """

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload, default=_json_default).encode())
    signing_input = header + b"." + body
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + b64(signature)).decode()


def _json_default(value: Any) -> Any:
    """Сериализация ``datetime`` так же, как это делает PyJWT."""
    if isinstance(value, datetime):
        return int(value.timestamp())
    raise TypeError(f"Не сериализуется: {type(value)!r}")


def test_hmac_token_signed_with_public_key_rejected() -> None:
    """Algorithm confusion: подпись публичным ключом как HMAC-секретом.

    Публичный ключ известен любому. Если бы проверка брала алгоритм из
    заголовка токена, проверяющий взял бы тот же публичный ключ в роли
    HMAC-секрета и подпись сошлась бы.

    Подделка настоящая: подпись собрана вручную и по HS256 верна.
    Отвергается она двумя независимыми слоями, и это стоит различать —
    наш явный список алгоритмов и, глубже, отказ PyJWT принимать
    PEM-ключ как HMAC-секрет вообще. Тест фиксирует итог, а не то, какой
    из слоёв сработал: собрать сценарий, где второй слой не мешает
    первому, на PEM-ключах невозможно.
    """
    forged = _forge_hs256(_payload(), PUBLIC_KEY)

    assert json.loads(base64.urlsafe_b64decode(forged.split(".")[0] + "=="))["alg"] == (
        "HS256"
    )

    with pytest.raises(TokenInvalidError):
        _decode(forged)


def test_unsigned_token_rejected() -> None:
    """Токен с ``alg: none`` не принимается."""
    forged = jwt.encode(_payload(), key="", algorithm="none")

    with pytest.raises(TokenInvalidError):
        _decode(forged)
