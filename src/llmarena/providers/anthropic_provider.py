from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic

from llmarena.providers.base import Provider, ProviderError, RateLimitedError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, *, fallbacks: bool = True) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=1)
        self._fallbacks = fallbacks

    async def stream_completion(
        self, *, system: str, user: str, model: str, max_tokens: int, extra: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": "low"},
        }
        if self._fallbacks:
            # Se um classificador recusar, o servidor reencaminha para outro modelo em vez de devolver vazio.
            kwargs["extra_headers"] = {"anthropic-beta": FALLBACK_BETA}
            kwargs["extra_body"] = {"fallbacks": "default"}
        if extra:
            kwargs.update(extra)
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.RateLimitError as e:
            raise RateLimitedError(f"anthropic rate limited: {e.message[:120]}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"anthropic HTTP {e.status_code}: {e.message[:160]}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"anthropic connection error: {str(e)[:160]}") from e
        if final.stop_reason == "refusal":
            raise ProviderError("anthropic refused the request")

    async def aclose(self) -> None:
        await self._client.close()
