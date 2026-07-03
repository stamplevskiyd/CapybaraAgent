"""Repository-pattern data access classes."""

from capybara.repositories.base import BaseRepository
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo

__all__ = [
    "BaseRepository",
    "ChatRepo",
    "MessageRepo",
    "UserRepo",
]
