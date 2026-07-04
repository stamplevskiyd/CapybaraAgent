from uuid import uuid4

import jwt as pyjwt
import pytest

from capybara.security.tokens import create_access_token, decode_access_token

SECRET = "test-jwt-secret-key-with-at-least-32-bytes!!"


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
        decode_access_token(token, secret="a-completely-different-secret-over-32-bytes!!")


def test_algorithm_mismatch_rejected() -> None:
    token = create_access_token(uuid4(), secret=SECRET, ttl_minutes=60, algorithm="HS256")
    with pytest.raises(pyjwt.InvalidAlgorithmError):
        decode_access_token(token, secret=SECRET, algorithm="HS512")


def test_non_uuid_sub_rejected() -> None:
    token = pyjwt.encode({"sub": "not-a-uuid"}, SECRET, algorithm="HS256")
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(token, secret=SECRET)


def test_token_without_exp_rejected() -> None:
    """A token that carries no expiry is refused — expiry is mandatory, not optional."""
    token = pyjwt.encode({"sub": str(uuid4())}, SECRET, algorithm="HS256")
    with pytest.raises(pyjwt.MissingRequiredClaimError):
        decode_access_token(token, secret=SECRET)
