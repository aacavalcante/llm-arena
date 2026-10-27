from __future__ import annotations

import ast
from dataclasses import dataclass

ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "math",
        "itertools",
        "collections",
        "functools",
        "string",
        "re",
        "heapq",
        "bisect",
        "operator",
        "typing",
        "dataclasses",
        "fractions",
        "decimal",
        "statistics",
        "random",
        "copy",
        "enum",
        "array",
        "cmath",
        "numbers",
        "abc",
    }
)
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "__import__",
        "open",
        "exec",
        "eval",
        "compile",
        "breakpoint",
        "input",
        "globals",
        "vars",
        "__builtins__",
        "__loader__",
        "__spec__",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
    }
)


@dataclass(frozen=True)
class StaticViolation:
    detail: str


def static_check(code: str) -> StaticViolation | None:
    """Rejeita imports fora da allowlist e builtins perigosos. Retorna None se o código passa."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None  # o sandbox reporta syntax_error com a mensagem certa
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_MODULES:
                    return StaticViolation(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_MODULES:
                return StaticViolation(f"import from '{node.module}' is not allowed")
            if any(a.name == "*" for a in node.names):
                return StaticViolation("star imports are not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            return StaticViolation(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES | {
            "__subclasses__",
            "__globals__",
        }:
            return StaticViolation(f"use of '.{node.attr}' is not allowed")
    return None
