from __future__ import annotations

import asyncio
from pathlib import Path

from llmarena.challenges.loader import load_bank
from llmarena.sandbox.executor import SubprocessSandbox
from llmarena.sandbox.static_check import static_check


async def verify_bank(path: Path) -> int:
    """Roda a solução de referência de cada desafio no sandbox. Retorna o número de falhas."""
    bank = load_bank(path)
    sandbox = SubprocessSandbox()
    failures = 0
    print(f"{'id':<32} {'dif':<7} {'tests':>5} {'ms':>6}  status")
    for c in bank.challenges:
        if not c.reference:
            print(f"{c.id:<32} {c.difficulty.value:<7} {len(c.tests):>5} {'-':>6}  SEM REFERÊNCIA")
            failures += 1
            continue
        v = static_check(c.reference)
        if v is not None:
            print(f"{c.id:<32} {c.difficulty.value:<7} {len(c.tests):>5} {'-':>6}  STATIC: {v.detail}")
            failures += 1
            continue
        res = await sandbox.run(c.reference, c)
        status = "ok" if res.passed else f"FALHOU {res.category.value}: {res.detail}"
        print(
            f"{c.id:<32} {c.difficulty.value:<7} {res.tests_passed:>2}/{res.tests_total:<2} {res.elapsed_ms:>6}  {status}"
        )
        if not res.passed:
            failures += 1
    counts = {k.value: v for k, v in bank.count_by_difficulty().items()}
    print(f"\n{len(bank.challenges)} desafios {counts}; falhas: {failures}")
    return failures


def main(path: str = "challenges/bank.yaml") -> int:
    return 1 if asyncio.run(verify_bank(Path(path))) else 0
