from capybara.security.passwords import (
    hash_password,
    hash_password_async,
    verify_password,
    verify_password_async,
)


def test_hash_password_returns_argon2_hash() -> None:
    hashed = hash_password("s3cret-password")
    assert hashed.startswith("$argon2")
    assert hashed != "s3cret-password"


def test_hash_password_is_salted_unique() -> None:
    assert hash_password("same-input") != hash_password("same-input")


def test_verify_password_correct() -> None:
    hashed = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", hashed) is True


def test_verify_password_wrong() -> None:
    hashed = hash_password("correct-horse-battery")
    assert verify_password("wrong-password", hashed) is False


def test_verify_password_malformed_hash_returns_false() -> None:
    assert verify_password("anything", "not-a-valid-argon2-hash") is False


async def test_hash_password_async_produces_verifiable_hash() -> None:
    """The threadpool-offloaded hash is a normal argon2 hash the sync verifier accepts."""
    hashed = await hash_password_async("async-secret")
    assert hashed.startswith("$argon2")
    assert verify_password("async-secret", hashed) is True


async def test_verify_password_async_matches_and_rejects() -> None:
    """The offloaded verifier returns True for the right password and False otherwise."""
    hashed = hash_password("async-secret")
    assert await verify_password_async("async-secret", hashed) is True
    assert await verify_password_async("wrong", hashed) is False


async def test_verify_password_async_malformed_hash_returns_false() -> None:
    """Malformed hashes fail closed on the async path too."""
    assert await verify_password_async("anything", "not-a-valid-argon2-hash") is False
