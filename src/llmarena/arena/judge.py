"""Juiz: transforma o problema escrito pelo usuário em um Challenge testável e valida no sandbox."""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from llmarena.challenges.schema import Challenge
from llmarena.domain.codeparse import extract_code
from llmarena.logging import get_logger
from llmarena.providers.base import Provider, ProviderError
from llmarena.sandbox.executor import Sandbox
from llmarena.sandbox.static_check import static_check

log = get_logger(__name__)

JUDGE_SYSTEM = (
    "You are the judge of a coding arena where two AI models race to solve small Python tasks. Turn the "
    "user's problem into ONE self-contained Python challenge with deterministic tests.\n"
    "Reply with ONLY a JSON object (no markdown, no prose) with exactly these keys:\n"
    '- "title": short name (max 40 chars)\n'
    '- "function": a valid Python identifier\n'
    '- "signature": e.g. "def name(items: list[int], k: int) -> int"\n'
    '- "statement": max 500 chars, written in the same language as the user\'s text; precise about inputs, '
    "outputs, edge cases and constraints so that the tests are unambiguous\n"
    '- "difficulty": "easy", "medium" or "hard"\n'
    '- "tests": 4 to 6 objects {"args": [...], "expected": ...}. args and expected must be plain JSON values '
    "(numbers, strings, booleans, null, lists, objects with string keys). No tuples or sets. Include edge cases.\n"
    '- "reference": a correct Python solution defining the function. Imports only from math, itertools, '
    "collections, functools, string, re, heapq, bisect. No prints, no input(), no file or network access. "
    "It must pass every test and each test must run in well under 100 ms.\n"
    "The function must be pure and deterministic. expected must be exactly what the reference returns."
)


class JudgeError(Exception):
    pass


@dataclass(frozen=True)
class GeneratedProblem:
    problem_id: str
    statement_src: str
    challenge: Challenge
    judge_model: str


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        code = extract_code(text)
        if code:
            text = code
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise JudgeError("no JSON object in the judge response")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise JudgeError(f"invalid JSON: {e.msg} at char {e.pos}") from e
    if not isinstance(data, dict):
        raise JudgeError("JSON is not an object")
    return data


def _user_prompt(statement: str, level: int, previous: Challenge | None, error: str | None) -> str:
    parts = [f"Problem written by the user:\n{statement.strip()}"]
    if level <= 1 or previous is None:
        parts.append("Level 1: stay faithful to the user's problem; pick a difficulty that matches it.")
    else:
        parts.append(
            f"The previous variation (level {previous.level}) was:\n"
            f"title: {previous.title}\nsignature: {previous.signature}\nstatement: {previous.statement}\n\n"
            f"Level {level}: create a STRICTLY HARDER variation on the same theme (tighter constraints, a "
            "generalization, bigger inputs, trickier edge cases). A different function name or an extended "
            "signature is fine. Raise the difficulty label when appropriate."
        )
    if error:
        parts.append(f"Your previous answer was rejected: {error}\nReturn a corrected JSON object only.")
    return "\n\n".join(parts)


class Judge:
    def __init__(
        self,
        *,
        provider: Provider,
        model: str,
        sandbox: Sandbox,
        max_tokens: int = 4000,
        timeout_s: float = 120.0,
        max_tries: int = 3,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.sandbox = sandbox
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_tries = max_tries
        self.extra = extra

    async def _ask(self, user: str) -> str:
        buf: list[str] = []
        async with asyncio.timeout(self.timeout_s):
            async for tok in self.provider.stream_completion(
                system=JUDGE_SYSTEM, user=user, model=self.model, max_tokens=self.max_tokens, extra=self.extra
            ):
                buf.append(tok)
        return "".join(buf)

    async def _validate(self, data: dict[str, Any], level: int) -> Challenge:
        fields = {
            k: data.get(k)
            for k in ("title", "function", "signature", "statement", "difficulty", "tests", "reference")
        }
        if isinstance(fields["statement"], str):
            fields["statement"] = fields["statement"][:600]
        try:
            challenge = Challenge(id=f"custom_{secrets.token_hex(4)}", level=level, custom=True, **fields)
        except ValidationError as e:
            raise JudgeError(
                "schema: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])
            ) from e
        if not challenge.reference:
            raise JudgeError("missing reference solution")
        violation = static_check(challenge.reference)
        if violation is not None:
            raise JudgeError(f"reference solution rejected: {violation.detail}")
        res = await self.sandbox.run(challenge.reference, challenge)
        if not res.passed:
            raise JudgeError(f"reference solution failed its own tests ({res.category.value}): {res.detail}")
        return challenge

    async def generate(self, statement: str, level: int = 1, previous: Challenge | None = None) -> Challenge:
        """Gera e valida um desafio; tenta de novo com o erro no prompt. Levanta JudgeError se não conseguir."""
        error: str | None = None
        for attempt in range(1, self.max_tries + 1):
            try:
                text = await self._ask(_user_prompt(statement, level, previous, error))
                data = _extract_json(text)
                challenge = await self._validate(data, level)
            except (JudgeError, ProviderError, TimeoutError) as e:
                error = str(e)[:400]
                log.warning("judge.retry", attempt=attempt, level=level, error=error)
                continue
            log.info("judge.generated", level=level, id=challenge.id, difficulty=challenge.difficulty.value)
            return challenge
        raise JudgeError(
            f"o juiz não conseguiu produzir um desafio válido após {self.max_tries} tentativas: {error}"
        )

    async def generate_problem(self, statement: str) -> GeneratedProblem:
        challenge = await self.generate(statement, level=1)
        return GeneratedProblem(
            problem_id=secrets.token_hex(6),
            statement_src=statement.strip(),
            challenge=challenge,
            judge_model=self.model,
        )
