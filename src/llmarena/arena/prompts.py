from __future__ import annotations

from llmarena.challenges.schema import Challenge

SYSTEM_PROMPT = (
    "You are a fighter in a coding arena. Speed wins. You will receive a tiny Python task with a required "
    "function signature. Reply with ONLY the Python source code that defines that function (plus helpers if "
    "needed). Imports allowed only from: math, itertools, collections, functools, string, re, heapq, bisect. "
    "No explanation, no markdown, no code fences, no tests, no prints, no input(). Use the exact function "
    "name given. Answer as fast as possible."
)


def build_user_prompt(challenge: Challenge, feedback: str | None = None) -> str:
    prompt = (
        f"Task: {challenge.title}\n{challenge.statement}\n\n"
        f"Signature: {challenge.signature}\n\nExample: {challenge.example()}"
    )
    if feedback:
        prompt += f"\n\nYour previous attempt failed: {feedback[:200]}. Fix it and return only the code."
    return prompt
