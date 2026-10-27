from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from llmarena.providers.base import Provider, ProviderError, RateLimitedError

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(Provider):
    name = "openrouter"

    def __init__(
        self, api_key: str, *, base_url: str = DEFAULT_BASE_URL, client: httpx.AsyncClient | None = None
    ):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/aacavalcante/llm-arena",
            "X-Title": "LLM Arena",
        }
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=5.0)
        )
        self._owns_client = client is None
        self._no_reasoning: set[str] = set()  # modelos que rejeitaram o parâmetro `reasoning`

    async def stream_completion(
        self, *, system: str, user: str, model: str, max_tokens: int, extra: dict[str, Any] | None = None
    ) -> AsyncIterator[str]:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": True,
            "max_tokens": max_tokens,
        }
        if model not in self._no_reasoning:
            body["reasoning"] = {"effort": "low", "exclude": True}
        if extra:
            body.update(extra)
        for attempt in range(2):
            try:
                async with self._client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=body, headers=self._headers
                ) as resp:
                    if resp.status_code == 429:
                        raise RateLimitedError("openrouter rate limited")
                    if resp.status_code >= 400:
                        raw = (await resp.aread())[:400].decode("utf-8", "replace")
                        if (
                            resp.status_code == 400
                            and attempt == 0
                            and "reasoning" in body
                            and "reasoning" in raw
                        ):
                            self._no_reasoning.add(model)
                            body.pop("reasoning", None)
                            continue
                        raise ProviderError(f"openrouter HTTP {resp.status_code}: {raw[:160]}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue  # comentários ": OPENROUTER PROCESSING" e linhas vazias
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if "error" in obj:
                            raise ProviderError(f"openrouter: {str(obj['error'])[:160]}")
                        for choice in obj.get("choices", []):
                            content = (choice.get("delta") or {}).get("content")
                            if content:
                                yield content
                    return
            except httpx.HTTPError as e:
                raise ProviderError(f"openrouter connection error: {str(e)[:160]}") from e

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
