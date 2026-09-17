from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any


class MarketDataProvider(ABC):
    """Provider boundary: replace development data without touching agent code."""

    name = 'unknown'

    @abstractmethod
    def fetch(self, symbol: str) -> Dict[str, Any]:
        raise NotImplementedError
