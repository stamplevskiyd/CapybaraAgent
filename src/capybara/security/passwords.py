"""Password hashing utilities using argon2."""

import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2 hash of the given plaintext password."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if the password matches the argon2 hash, else False."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """Hash a password off the event loop.

    argon2 is deliberately CPU-heavy; running it inline would block the single async
    worker thread during login/registration. Offload to a worker thread so concurrent
    requests keep flowing.
    """
    return await anyio.to_thread.run_sync(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """Verify a password off the event loop (see ``hash_password_async``)."""
    return await anyio.to_thread.run_sync(verify_password, password, password_hash)
