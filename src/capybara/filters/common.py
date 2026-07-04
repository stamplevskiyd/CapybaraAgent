"""Common reusable query filters."""

from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute

from capybara.db.base import Base
from capybara.filters.base import Filter


class FieldEquals(Filter):
    """Filter rows where a mapped column equals a value.

    The column is passed as the mapped attribute itself (e.g. ``Message.chat_id``)
    rather than a string name, so a wrong or misspelled field is a type error at
    author time instead of an ``AttributeError`` at runtime.
    """

    def __init__(self, column: InstrumentedAttribute[Any], value: Any) -> None:
        self._column = column
        self._value = value

    def to_criterion(self, model: type[Base]) -> ColumnElement[bool]:
        """Build ``column == value``; the bound column already names its table."""
        criterion: ColumnElement[bool] = self._column == self._value
        return criterion
