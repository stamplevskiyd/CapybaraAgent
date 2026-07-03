"""Composable query filters for repositories."""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement

from capybara.db.base import Base


class Filter(ABC):
    """A reusable query filter that yields a SQLAlchemy WHERE criterion."""

    @abstractmethod
    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Return the SQLAlchemy boolean criterion for the given model."""


class FieldEquals(Filter):
    """Filter rows where a named column equals a value."""

    def __init__(self, field: str, value: Any) -> None:
        self._field = field
        self._value = value

    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Build `model.<field> == value`."""
        criterion: ColumnElement[bool] = getattr(model, self._field) == self._value
        return criterion


class OwnedByUser(Filter):
    """Filter rows owned by a given user (`model.user_id == user_id`)."""

    def __init__(self, user_id: UUID) -> None:
        self._user_id = user_id

    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Build `model.user_id == user_id`."""
        # the Base bound doesn't declare user_id; callers must use this on owner-scoped models
        criterion: ColumnElement[bool] = model.user_id == self._user_id  # type: ignore[attr-defined]
        return criterion
