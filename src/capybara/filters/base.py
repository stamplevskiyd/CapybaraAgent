"""Base filter abstraction for repository queries."""

from abc import ABC, abstractmethod

from sqlalchemy import ColumnElement

from capybara.db.base import Base


class Filter(ABC):
    """A reusable query filter that yields a SQLAlchemy WHERE criterion.

    Filters compose: repositories apply their ``default_filters`` plus whatever the
    caller passes to ``get_list``/``get_one``. Implementations should be small value
    objects so they can be shared and compared in tests.
    """

    @abstractmethod
    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Return the SQLAlchemy boolean criterion for the given model."""
