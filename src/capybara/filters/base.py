"""Base filter abstraction for repository queries."""

from abc import ABC, abstractmethod

from sqlalchemy import ColumnElement

from capybara.db.base import Base


class Filter(ABC):
    """A reusable query filter that yields a SQLAlchemy WHERE criterion."""

    @abstractmethod
    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Return the SQLAlchemy boolean criterion for the given model."""
