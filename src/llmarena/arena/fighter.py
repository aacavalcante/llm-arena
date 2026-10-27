from __future__ import annotations

import asyncio
from typing import Any

from llmarena.arena.prompts import SYSTEM_PROMPT, build_user_prompt
from llmarena.challenges.schema import Challenge
from llmarena.domain.codeparse import ensure_function, extract_code
from llmarena.domain.models import Category, FighterStatus, GolpeResult, Side
from llmarena.logging import get_logger
from llmarena.protocol import FighterStatusEvent, TokenEvent
from llmarena.providers.base import Provider, ProviderError, RateLimitedError
from llmarena.sandbox.executor import Sandbox
from llmarena.sandbox.static_check import static_check
from llmarena.settings import Settings
from llmarena.ws import Broadcaster

log = get_logger(__name__)
STUN_SECONDS = 0.5


class FighterTask:
    """Um lutador tentando um desafio: stream -> parse -> static check -> sandbox -> resultado na fila.

    Não muda estado compartilhado; só publica tokens/status e enfileira GolpeResult para o árbitro.
    """

    def __init__(
        self,
        *,
        side: Side,
        provider: Provider,
        model: str,
        model_extra: dict[str, Any] | None,
        challenge: Challenge,
        seq: int,
        dispatched_at: float,
        results: asyncio.Queue[GolpeResult],
        settings: Settings,
        broadcaster: Broadcaster,
        sandbox: Sandbox,
    ) -> None:
        self.side = side
        self.provider = provider
        self.model = model
        self.model_extra = model_extra
        self.challenge = challenge
        self.seq = seq
        self.dispatched_at = dispatched_at
        self.results = results
        self.settings = settings
        self.bc = broadcaster
        self.sandbox = sandbox

    def _status(self, status: FighterStatus) -> None:
        self.bc.publish(FighterStatusEvent(side=self.side.value, status=status.value))

    def _elapsed_ms(self) -> int:
        return int((asyncio.get_running_loop().time() - self.dispatched_at) * 1000)

    async def _miss(
        self, attempt: int, category: Category, detail: str, code: str = "", chars: int = 0
    ) -> None:
        await self.results.put(
            GolpeResult(
                side=self.side,
                seq=self.seq,
                attempt=attempt,
                passed=False,
                category=category,
                detail=detail[:300],
                ms=self._elapsed_ms(),
                code=code,
                output_chars=chars,
            )
        )

    async def _generate(self) -> str:
        buf: list[str] = []
        agen = self.provider.stream_completion(
            system=SYSTEM_PROMPT,
            user=self._user_prompt,
            model=self.model,
            max_tokens=self.settings.llm_max_tokens,
            extra=self.model_extra,
        )
        try:
            async with asyncio.timeout(self.settings.llm_timeout_s):
                first = True
                while True:
                    try:
                        if first:
                            async with asyncio.timeout(self.settings.first_token_timeout_s):
                                tok = await anext(agen)
                            first = False
                        else:
                            tok = await anext(agen)
                    except StopAsyncIteration:
                        break
                    buf.append(tok)
                    self.bc.publish(TokenEvent(side=self.side.value, seq=self.seq, text=tok))
        finally:
            await agen.aclose()
        return "".join(buf)

    async def run(self) -> None:
        feedback: str | None = None
        for attempt in range(1, self.settings.max_attempts_per_challenge + 1):
            self._user_prompt = build_user_prompt(self.challenge, feedback)
            self._status(FighterStatus.WRITING)
            try:
                text = await self._generate()
            except asyncio.CancelledError:
                raise
            except RateLimitedError as e:
                await self._miss(attempt, Category.API_ERROR, f"rate limited: {e}")
                feedback = None
                await asyncio.sleep(min(2.0 * attempt, 6.0))
                continue
            except TimeoutError:
                await self._miss(attempt, Category.API_ERROR, "no response from the model in time")
                feedback = None
                await asyncio.sleep(STUN_SECONDS)
                continue
            except ProviderError as e:
                await self._miss(attempt, Category.API_ERROR, str(e))
                feedback = None
                await asyncio.sleep(1.0)
                continue
            except Exception as e:  # noqa: BLE001 - erro inesperado do provedor vira golpe perdido
                log.exception("fighter.provider_crash", side=self.side.value, model=self.model)
                await self._miss(attempt, Category.API_ERROR, f"unexpected provider error: {e!r}"[:200])
                feedback = None
                await asyncio.sleep(1.0)
                continue

            code = extract_code(text)
            if not code:
                await self._miss(
                    attempt, Category.NO_CODE, "no python code found in the response", chars=len(text)
                )
                feedback = "no_code: reply with only the Python source code"
                await asyncio.sleep(STUN_SECONDS)
                continue
            code, _renamed = ensure_function(code, self.challenge.function)
            violation = static_check(code)
            if violation is not None:
                await self._miss(attempt, Category.FORBIDDEN_IMPORT, violation.detail, code, len(text))
                feedback = f"forbidden: {violation.detail}"
                await asyncio.sleep(STUN_SECONDS)
                continue

            self._status(FighterStatus.TESTING)
            res = await self.sandbox.run(code, self.challenge)
            await self.results.put(
                GolpeResult(
                    side=self.side,
                    seq=self.seq,
                    attempt=attempt,
                    passed=res.passed,
                    category=res.category,
                    detail=res.detail,
                    ms=self._elapsed_ms(),
                    code=code,
                    output_chars=len(text),
                    tests_passed=res.tests_passed,
                    tests_total=res.tests_total,
                )
            )
            if res.passed:
                return
            feedback = f"{res.category.value}: {res.detail}"
            await asyncio.sleep(STUN_SECONDS)
        self._status(FighterStatus.IDLE)
