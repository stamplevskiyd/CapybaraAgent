"""Command abstraction: every use case is a command with ``validate`` and ``run``."""

from abc import ABC, abstractmethod


class BaseCommand[ResultT](ABC):
    """One use case: construct with its dependencies and arguments, then ``execute()``.

    ``validate()`` holds business prechecks — anything needing I/O (ownership,
    availability, uniqueness); input *format* validation stays on the API schemas.
    Checks that must be transactional with the write itself live in ``run()`` instead.
    ``execute()`` is the public entry point: validate, then run.
    """

    async def validate(self) -> None:  # noqa: B027 — an optional hook, not an abstract method
        """Check business preconditions; raise on violation. Default: nothing to check."""

    @abstractmethod
    async def run(self) -> ResultT:
        """Execute the use case and return its result."""

    async def execute(self) -> ResultT:
        """Validate, then run."""
        await self.validate()
        return await self.run()
