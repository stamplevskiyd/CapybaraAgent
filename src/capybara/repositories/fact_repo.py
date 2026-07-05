"""Repository for Fact CRUD and user-scoped vector search."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, select

from capybara.db.models import Fact
from capybara.repositories.base import BaseRepository


class FactRepo(BaseRepository[Fact]):
    """Repository for Fact rows: inherited CRUD plus cosine-nearest search."""

    model = Fact

    def _default_order_by(self) -> Sequence[ColumnElement[Any]]:
        """Order facts newest-first for list views."""
        return (Fact.created_at.desc(),)

    async def search(
        self, user_id: UUID, embedding: list[float], k: int
    ) -> list[tuple[Fact, float]]:
        """Return the *k* nearest facts for *user_id* by cosine distance, nearest first.

        Each result is a ``(fact, distance)`` pair where ``distance`` is the pgvector
        cosine distance (``0`` identical, ``2`` opposite). Callers convert to similarity
        via ``1 - distance`` and apply their own threshold.
        """
        distance = Fact.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(Fact, distance)
            .where(Fact.user_id == user_id)
            .order_by(distance)
            .limit(k)
        )
        result = await self._session.execute(stmt)
        return [(row.Fact, row.distance) for row in result.all()]
