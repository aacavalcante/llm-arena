from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class ProviderError(Exception):
    """Erro de API tratado como golpe perdido (api_error), nunca como crash."""


class RateLimitedError(ProviderError):
    pass


class Provider(ABC):
    name: str

    @abstractmethod
    def stream_completion(
        self, *, system: str, user: str, model: str, max_tokens: int, extra: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        """Gera os pedaços de texto da resposta. Deve fechar a conexão ao ser cancelado."""

    async def aclose(self) -> None:  # noqa: B027
        pass
