"""Router for user registration endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.api.dependencies import get_user_service
from capybara.api.schemas import UserCreate, UserOut
from capybara.services.user_service import UsernameTaken, UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(
    payload: UserCreate,
    users: Annotated[UserService, Depends(get_user_service)],
) -> UserOut:
    """Register a new local user; 409 if the username is already taken."""
    try:
        user = await users.register(payload.display_name, payload.username, payload.password)
    except UsernameTaken:
        raise HTTPException(status_code=409, detail="Username already taken") from None
    return UserOut.model_validate(user)
