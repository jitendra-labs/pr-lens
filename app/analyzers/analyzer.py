from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from ..models.pr_context import PRContext


class Analyzer(ABC):
    """Abstract analyzer definition.

    Implementations should be async and return JSON-serializable findings.
    """

    @abstractmethod
    async def analyze(self, context: PRContext) -> Dict[str, Any]:
        raise NotImplementedError()
