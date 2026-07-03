"""Password hashing utilities using argon2."""

from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2 hash of the given plaintext password."""
    return _hasher.hash(password)
