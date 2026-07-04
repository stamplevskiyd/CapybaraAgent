"""JWT access-token creation and decoding."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt


def create_access_token(
    user_id: UUID, *, secret: str, ttl_minutes: int, algorithm: str = "HS256"
) -> str:
    """Create a signed JWT access token for the given user id."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str = "HS256") -> UUID:
    """Decode a JWT access token and return its subject user id; raise on invalid/expired."""
    payload = jwt.decode(token, secret, algorithms=[algorithm], options={"require": ["exp"]})
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError) as err:
        raise jwt.InvalidTokenError("token has no valid subject") from err
