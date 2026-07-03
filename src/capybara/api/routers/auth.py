"""Router for authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.api.dependencies import get_auth_service
from capybara.api.schemas import LoginRequest, TokenResponse
from capybara.services.auth_service import AuthService, InvalidCredentials

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate and return a JWT bearer token; 401 on invalid credentials."""
    try:
        token = await auth.login(payload.username, payload.password)
    except InvalidCredentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        ) from None
    return TokenResponse(access_token=token)
