"""Router for user registration endpoints."""

from fastapi import APIRouter, HTTPException, status

from capybara.api.dependencies import CurrentUser, Sessionmaker
from capybara.api.schemas import UserCreate, UserOut
from capybara.commands.user.register import RegisterUser, UsernameTaken

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(payload: UserCreate, sessionmaker: Sessionmaker) -> UserOut:
    """Register a new local user; 409 if the username is already taken."""
    command = RegisterUser(
        sessionmaker,
        display_name=payload.display_name,
        username=payload.username,
        password=payload.password,
    )
    try:
        user = await command.execute()
    except UsernameTaken:
        raise HTTPException(status_code=409, detail="Username already taken") from None
    return UserOut.model_validate(user)


@router.get("/me", response_model=UserOut)
async def read_current_user(user: CurrentUser) -> UserOut:
    """Return the currently authenticated user's public profile."""
    return UserOut.model_validate(user)
