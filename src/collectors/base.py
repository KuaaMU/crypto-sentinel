from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    """Base interface for all data collectors."""

    @abstractmethod
    async def collect(self) -> Any:
        """Collect data from the source. Returns immutable data object."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the data source is reachable."""
        ...
