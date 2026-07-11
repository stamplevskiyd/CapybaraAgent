"""Router for authentication endpoints."""

from fastapi import APIRouter, HTTPException, status

from capybara.api.dependencies import AppSettings, Sessionmaker
from capybara.api.schemas import LoginRequest, TokenResponse
from capybara.commands.auth.login import InvalidCredentials, LoginUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    sessionmaker: Sessionmaker,
    settings: AppSettings,
) -> TokenResponse:
    """Authenticate and return a JWT bearer token; 401 on invalid credentials."""
    command = LoginUser(
        sessionmaker,
        username=payload.username,
        password=payload.password,
        secret=settings.jwt_secret,
        ttl_minutes=settings.jwt_ttl_minutes,
        algorithm=settings.jwt_algorithm,
    )
    try:
        token = await command.execute()
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from None
    return TokenResponse(access_token=token)
