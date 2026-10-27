from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class SandboxCapabilities:
    netns_prefix: tuple[str, ...] = field(default=())
    notes: tuple[str, ...] = field(default=())

    @property
    def network_isolated(self) -> bool:
        return bool(self.netns_prefix)


def _works(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=5, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def probe() -> SandboxCapabilities:
    """Descobre se dá para isolar a rede do subprocesso com `unshare` neste host/container."""
    notes: list[str] = []
    if shutil.which("unshare") is None:
        return SandboxCapabilities(notes=("unshare not found",))
    for prefix in (["unshare", "-n"], ["unshare", "-Urn"]):
        if _works([*prefix, "true"]):
            return SandboxCapabilities(netns_prefix=tuple(prefix), notes=tuple(notes))
        notes.append(f"{' '.join(prefix)} failed")
    return SandboxCapabilities(notes=tuple(notes))
