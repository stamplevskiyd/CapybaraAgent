from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.models import User


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)
