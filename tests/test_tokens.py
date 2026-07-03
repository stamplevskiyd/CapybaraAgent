from uuid import uuid4

import jwt as pyjwt
import pytest

from capybara.security.tokens import create_access_token, decode_access_token

SECRET = "unit-test-secret"


def test_create_decode_roundtrip() -> None:
    uid = uuid4()
    token = create_access_token(uid, secret=SECRET, ttl_minutes=60)
    assert decode_access_token(token, secret=SECRET) == uid


def test_expired_token_rejected() -> None:
    token = create_access_token(uuid4(), secret=SECRET, ttl_minutes=-1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(token, secret=SECRET)


def test_wrong_secret_rejected() -> None:
    token = create_access_token(uuid4(), secret=SECRET, ttl_minutes=60)
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(token, secret="a-different-secret")


def test_algorithm_mismatch_rejected() -> None:
    token = create_access_token(uuid4(), secret=SECRET, ttl_minutes=60, algorithm="HS256")
    with pytest.raises(pyjwt.InvalidAlgorithmError):
        decode_access_token(token, secret=SECRET, algorithm="HS512")
