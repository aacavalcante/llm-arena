from __future__ import annotations

from pathlib import Path

import yaml

from llmarena.challenges.schema import ChallengeBank
from llmarena.logging import get_logger

log = get_logger(__name__)


def load_bank(path: Path) -> ChallengeBank:
    """Carrega um arquivo YAML (chave `challenges:`) ou todos os *.yaml de um diretório."""
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    items: list[dict] = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        items.extend(data.get("challenges", []))
    bank = ChallengeBank(challenges=items)
    counts = bank.count_by_difficulty()
    for diff, n in counts.items():
        if n < 5:
            log.warning("bank.few_challenges", difficulty=diff.value, count=n)
    log.info("bank.loaded", total=len(bank.challenges), by_difficulty={k.value: v for k, v in counts.items()})
    return bank
