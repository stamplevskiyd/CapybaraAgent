"""Generic base repository providing common CRUD operations."""

from collections.abc import Sequence
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.base import Base
from capybara.repositories.filters import Filter


class BaseRepository[ModelT: Base]:
    """Generic async repository for SQLAlchemy models."""

    model: type[ModelT]
    default_filters: ClassVar[Sequence[Filter]] = ()

    def __init__(self, session: AsyncSession) -> None:
        """Initialise the repository with an async session."""
        self._session = session

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Default result ordering — chronological by creation time; override per repo."""
        return (self.model.created_at.asc(),)  # type: ignore[attr-defined]  # all models carry created_at via TimestampMixin

    async def get(self, id_: UUID) -> ModelT | None:
        """Fetch a model instance by UUID primary key, returning None if not found."""
        return await self._session.get(self.model, id_)

    async def list(self, *filters: Filter) -> list[ModelT]:
        """List rows matching default + given filters, in the repo's default order."""
        stmt = select(self.model)
        for query_filter in (*self.default_filters, *filters):
            stmt = stmt.where(query_filter.to_criterion(self.model))
        stmt = stmt.order_by(*self._default_order_by())
        result = await self._session.execute(stmt)
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
