"""Generic base repository providing common CRUD operations."""

from typing import Any
from uuid import UUID

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.base import Base


class BaseRepository[ModelT: Base]:
    """Generic async repository for SQLAlchemy models."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id_: UUID) -> ModelT | None:
        """Fetch a model instance by UUID primary key, returning None if not found."""
        return await self._session.get(self.model, id_)

    async def list(self) -> list[ModelT]:
        """Return all rows for the model."""
        result = await self._session.execute(select(self.model))
        return list(result.scalars().all())

    async def create(self, **fields: Any) -> ModelT:
        """Create and persist a new model instance with the given fields."""
        instance = self.model(**fields)
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def add(self, instance: ModelT) -> ModelT:
        """Add an already-constructed instance to the session and flush."""
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(self, instance: ModelT, **fields: Any) -> ModelT:
        """Apply field updates to an instance and flush.

        Args:
            instance: The ORM model instance to update.
            **fields: Mapped attribute names and their new values.

        Raises:
            ValueError: If any key in *fields* is not a mapped attribute of the model.
        """
        valid = set(sa_inspect(self.model).mapper.attrs.keys())
        for key in fields:
            if key not in valid:
                raise ValueError(f"Unknown field {key!r} for {self.model.__name__}")
        for key, value in fields.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Delete an instance from the session and flush."""
        await self._session.delete(instance)
        await self._session.flush()
