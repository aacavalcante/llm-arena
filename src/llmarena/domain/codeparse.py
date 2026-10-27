from __future__ import annotations

import ast
import re

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)
_CODE_START_RE = re.compile(r"^(def |import |from |class |@|async def )")


def extract_code(text: str) -> str:
    """Extrai o código Python da resposta do modelo, tolerando fences e prosa em volta."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return ""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip("\n")
    # Sem fence fechado: pode ter um fence aberto sem fechamento
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if _CODE_START_RE.match(ln)), None)
    if start is None:
        return ""
    body = lines[start:]
    # Corta prosa no fim: a partir da primeira linha em branco seguida de linha sem cara de código
    end = len(body)
    for i in range(1, len(body)):
        if body[i - 1].strip() == "" and body[i].strip() and not _looks_like_code(body[i]):
            end = i
            break
    return "\n".join(body[:end]).strip("\n")


def _looks_like_code(line: str) -> bool:
    if line.startswith((" ", "\t", "#", "def ", "class ", "import ", "from ", "@", "async ", ")", "]", "}")):
        return True
    stripped = line.strip()
    if _CODE_START_RE.match(stripped) or stripped.startswith(
        ("return", "if ", "for ", "while ", "try:", "except")
    ):
        return True
    # Atribuição ou chamada no nível superior
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_\.\[\]]*\s*(=|\()", stripped))


def ensure_function(code: str, name: str) -> tuple[str, bool]:
    """Garante que `name` exista no módulo. Se houver exatamente uma def com outro nome, cria um alias.

    Retorna (código, renomeado).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, False
    defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    assigned = {
        t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
    }
    if name in defs or name in assigned:
        return code, False
    if len(defs) == 1:
        return f"{code.rstrip()}\n\n{name} = {defs[0]}\n", True
    return code, False
