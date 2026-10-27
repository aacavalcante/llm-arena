from __future__ import annotations

import httpx
import pytest
import respx

from llmarena.providers.base import ProviderError, RateLimitedError
from llmarena.providers.fake import DemoProvider
from llmarena.providers.openrouter_provider import OpenRouterProvider

URL = "https://openrouter.ai/api/v1/chat/completions"


def sse(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


async def collect(provider, model="x/y"):
    out = []
    async for t in provider.stream_completion(system="s", user="u", model=model, max_tokens=10):
        out.append(t)
    return "".join(out)


@respx.mock
async def test_openrouter_streams_content_and_ignores_reasoning():
    body = ": OPENROUTER PROCESSING\n\n" + sse(
        '{"choices":[{"delta":{"reasoning":"thinking..."}}]}',
        '{"choices":[{"delta":{"content":"def f"}}]}',
        '{"choices":[{"delta":{"content":"():\\n    return 1"}}]}',
        "[DONE]",
    )
    route = respx.post(URL).mock(return_value=httpx.Response(200, text=body))
    p = OpenRouterProvider("key")
    assert await collect(p) == "def f():\n    return 1"
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer key"
    import json

    payload = json.loads(sent.content)
    assert payload["stream"] is True and payload["reasoning"]["effort"] == "low"
    await p.aclose()


@respx.mock
async def test_openrouter_rate_limit_and_errors():
    respx.post(URL).mock(return_value=httpx.Response(429, text="slow down"))
    p = OpenRouterProvider("key")
    with pytest.raises(RateLimitedError):
        await collect(p)
    respx.post(URL).mock(return_value=httpx.Response(500, text="oops"))
    with pytest.raises(ProviderError):
        await collect(p)
    respx.post(URL).mock(return_value=httpx.Response(200, text=sse('{"error":{"message":"bad model"}}')))
    with pytest.raises(ProviderError):
        await collect(p)
    await p.aclose()


@respx.mock
async def test_openrouter_retries_without_reasoning_on_400():
    import json

    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if "reasoning" in payload:
            return httpx.Response(400, text='{"error":{"message":"reasoning is not supported"}}')
        return httpx.Response(200, text=sse('{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"))

    respx.post(URL).mock(side_effect=handler)
    p = OpenRouterProvider("key")
    assert await collect(p, "m/old") == "ok"
    assert len(calls) == 2 and "reasoning" not in calls[1]
    assert await collect(p, "m/old") == "ok"
    assert len(calls) == 3 and "reasoning" not in calls[2]  # lembrou que o modelo não aceita
    await p.aclose()


async def test_demo_provider_answers_with_reference(real_bank):
    c = real_bank.by_id("fibonacci")
    p = DemoProvider(real_bank, seed=1)
    from llmarena.arena.prompts import build_user_prompt

    text = await collect_user(p, build_user_prompt(c))
    assert "def fibonacci" in text


async def collect_user(provider, user):
    out = []
    async for t in provider.stream_completion(system="s", user=user, model="demo/relampago", max_tokens=10):
        out.append(t)
    return "".join(out)
