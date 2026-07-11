"""Generic base repository providing the common CRUD surface.

Children bind ``model`` and add methods only when the base ones do not fit (e.g.
vector search). Everything else — point reads, filtered listing, pydantic-payload
create/update, delete — lives here so repositories stay uniform.
"""

from collections.abc import Sequence
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.db.base import Base
from capybara.filters import Filter


class BaseRepository[ModelT: Base]:
    """Generic async repository for SQLAlchemy models."""

    model: type[ModelT]
    #: Filters applied to every ``get_list``/``get_one`` call unless explicitly bypassed —
    #: the place for invariants like tenant scoping or soft-delete visibility.
    default_filters: ClassVar[Sequence[Filter]] = ()

    def __init__(self, session: AsyncSession) -> None:
        """Initialise the repository with an async session."""
        self._session = session

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Default result ordering — chronological by creation time; override per repo."""
        return (self.model.created_at.asc(),)  # type: ignore[attr-defined]  # all models carry created_at via TimestampMixin

    def _apply_filters(
        self,
        stmt: Select[tuple[ModelT]],
        filters: Sequence[Filter],
        *,
        bypass_default_filters: bool,
    ) -> Select[tuple[ModelT]]:
        """Apply default + given filters to *stmt* (defaults skipped when bypassed)."""
        applied = filters if bypass_default_filters else (*self.default_filters, *filters)
        for query_filter in applied:
            stmt = stmt.where(query_filter.to_criterion(self.model))
        return stmt

    @staticmethod
    def _merge_fields(data: BaseModel | None, fields: dict[str, Any]) -> dict[str, Any]:
        """Merge a pydantic payload (set fields only) with explicit overrides."""
        merged: dict[str, Any] = dict(data.model_dump(exclude_unset=True)) if data else {}
        merged.update(fields)
        return merged

    async def get(self, id_: UUID) -> ModelT | None:
        """Fetch a model instance by UUID primary key, returning None if not found."""
        return await self._session.get(self.model, id_)

    async def get_one(
        self, *filters: Filter, bypass_default_filters: bool = False
    ) -> ModelT | None:
        """Return the single row matching the filters, or None.

        Raises:
            sqlalchemy.exc.MultipleResultsFound: If more than one row matches.
        """
        stmt = self._apply_filters(
            select(self.model), filters, bypass_default_filters=bypass_default_filters
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_list(
        self, *filters: Filter, bypass_default_filters: bool = False
    ) -> list[ModelT]:
        """List rows matching default + given filters, in the repo's default order."""
        stmt = self._apply_filters(
            select(self.model), filters, bypass_default_filters=bypass_default_filters
        )
        stmt = stmt.order_by(*self._default_order_by())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: BaseModel | None = None, **fields: Any) -> ModelT:
        """Create and persist a new instance from a pydantic payload and/or fields.

        *data* contributes its explicitly-set fields; keyword *fields* override them
        (useful for server-side values like ``user_id`` or computed columns).
        """
        instance = self.model(**self._merge_fields(data, fields))
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(
        self, instance: ModelT, data: BaseModel | None = None, **fields: Any
    ) -> ModelT:
        """Apply a pydantic payload and/or field updates to an instance and flush.

        Args:
            instance: The ORM model instance to update.
            data: Optional pydantic payload; only its explicitly-set fields apply.
            **fields: Mapped attribute names and their new values (override *data*).

        Raises:
            ValueError: If any resulting key is not a mapped attribute of the model.
        """
        merged = self._merge_fields(data, fields)
        valid = set(sa_inspect(self.model).mapper.attrs.keys())
        for key in merged:
            if key not in valid:
                raise ValueError(f"Unknown field {key!r} for {self.model.__name__}")
        for key, value in merged.items():
            setattr(instance, key, value)
        await self._session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Delete an instance from the session and flush."""
        await self._session.delete(instance)
        await self._session.flush()
