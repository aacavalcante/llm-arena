from __future__ import annotations

import random
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from llmarena.domain.models import Difficulty

_ID_RE = re.compile(r"^[a-z0-9_]+$")


class TestCase(BaseModel):
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    expected: Any = None


class Challenge(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    function: str
    signature: str
    statement: str = Field(max_length=600)
    tests: list[TestCase] = Field(min_length=3)
    float_tol: float | None = None
    reference: str | None = None
    level: int = 0  # > 0 quando gerado pelo juiz a partir de um problema do usuário
    custom: bool = False

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(f"id '{v}' must match {_ID_RE.pattern}")
        return v

    @field_validator("function")
    @classmethod
    def _function_identifier(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"function '{v}' is not a valid identifier")
        return v

    @model_validator(mode="after")
    def _signature_matches(self) -> Challenge:
        if f"def {self.function}(" not in self.signature:
            raise ValueError(f"signature '{self.signature}' does not define '{self.function}'")
        return self

    def test_dicts(self) -> list[dict[str, Any]]:
        return [t.model_dump() for t in self.tests]

    def example(self) -> str:
        t = self.tests[0]
        args = ", ".join(repr(a) for a in t.args)
        if t.kwargs:
            args += ", " + ", ".join(f"{k}={v!r}" for k, v in t.kwargs.items())
        return f"{self.function}({args}) -> {t.expected!r}"


class ChallengeBank(BaseModel):
    challenges: list[Challenge]

    @model_validator(mode="after")
    def _unique_ids(self) -> ChallengeBank:
        seen: set[str] = set()
        for c in self.challenges:
            if c.id in seen:
                raise ValueError(f"duplicate challenge id '{c.id}'")
            seen.add(c.id)
        if not self.challenges:
            raise ValueError("challenge bank is empty")
        return self

    def by_id(self, cid: str) -> Challenge:
        for c in self.challenges:
            if c.id == cid:
                return c
        raise KeyError(cid)

    def by_title(self, title: str) -> Challenge | None:
        return next((c for c in self.challenges if c.title == title), None)

    def count_by_difficulty(self) -> dict[Difficulty, int]:
        out = dict.fromkeys(Difficulty, 0)
        for c in self.challenges:
            out[c.difficulty] += 1
        return out

    def draw(self, exclude: set[str], rng: random.Random) -> Challenge:
        pool = [c for c in self.challenges if c.id not in exclude] or self.challenges
        return rng.choice(pool)
