from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from llmarena.domain.models import Category
from llmarena.logging import get_logger
from llmarena.sandbox.capabilities import probe

log = get_logger(__name__)
RUNNER_PATH = Path(__file__).with_name("runner_script.py")
MAX_CAPTURE = 4096


@dataclass(frozen=True)
class SandboxLimits:
    wall_s: float = 3.5
    cpu_s: int = 3
    mem_mb: int = 256
    netns: str = "auto"  # auto | on | off
    parallel: int = 4


@dataclass
class SandboxResult:
    passed: bool
    category: Category
    detail: str
    tests_passed: int = 0
    tests_total: int = 0
    elapsed_ms: int = 0
    failed_test: dict[str, Any] | None = None


class TestSpec(Protocol):
    """O que o sandbox precisa saber de um desafio (o Challenge do banco satisfaz isto)."""

    function: str
    float_tol: float | None

    def test_dicts(self) -> list[dict[str, Any]]: ...


class Sandbox(Protocol):
    async def run(self, code: str, spec: TestSpec) -> SandboxResult: ...


class SubprocessSandbox:
    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()
        self._sem = asyncio.Semaphore(self.limits.parallel)
        self._prefix: tuple[str, ...] = ()
        caps = probe() if self.limits.netns != "off" else None
        if caps is not None:
            self._prefix = caps.netns_prefix
            if not caps.network_isolated:
                msg = "sandbox sem isolamento de rede (unshare indisponível): " + "; ".join(caps.notes)
                if self.limits.netns == "on":
                    raise RuntimeError(msg)
                log.warning("sandbox.no_netns", notes=caps.notes)
        log.info("sandbox.ready", netns=list(self._prefix) or None, limits=self.limits)

    @property
    def network_isolated(self) -> bool:
        return bool(self._prefix)

    async def run(self, code: str, spec: TestSpec) -> SandboxResult:
        async with self._sem:
            return await self._run(code, spec)

    async def _run(self, code: str, spec: TestSpec) -> SandboxResult:
        workdir = tempfile.mkdtemp(prefix="arena-")
        proc: asyncio.subprocess.Process | None = None
        try:
            sub = Path(workdir, "submission.py")
            sub.write_text(code, encoding="utf-8")
            tests = Path(workdir, "tests.json")
            tests.write_text(
                json.dumps(
                    {"function": spec.function, "float_tol": spec.float_tol, "tests": spec.test_dicts()}
                ),
                encoding="utf-8",
            )
            sub.chmod(0o444)
            tests.chmod(0o444)
            os.chmod(workdir, 0o777)  # o runner precisa criar result.json mesmo com uid diferente (userns)
            cmd = [
                *self._prefix,
                sys.executable,
                "-I",
                "-S",
                str(RUNNER_PATH),
                workdir,
                str(self.limits.mem_mb),
                str(self.limits.cpu_s),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=workdir,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONHASHSEED": "0"},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                async with asyncio.timeout(self.limits.wall_s):
                    _out, err = await proc.communicate()
            except TimeoutError:
                _kill(proc)
                return SandboxResult(
                    False, Category.TIMEOUT, f"exceeded {self.limits.wall_s:.1f}s wall clock"
                )
            result_path = Path(workdir, "result.json")
            if result_path.exists():
                data = json.loads(result_path.read_text(encoding="utf-8"))
                return SandboxResult(
                    passed=bool(data["passed"]),
                    category=Category(data["category"]),
                    detail=str(data.get("detail", ""))[:300],
                    tests_passed=int(data.get("tests_passed", 0)),
                    tests_total=int(data.get("tests_total", 0)),
                    elapsed_ms=int(data.get("elapsed_ms", 0)),
                    failed_test=data.get("failed_test"),
                )
            return _classify_crash(proc.returncode, err[-MAX_CAPTURE:].decode("utf-8", "replace"))
        except asyncio.CancelledError:
            if proc is not None:
                _kill(proc)
            raise
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        proc.kill()


def _classify_crash(returncode: int | None, stderr: str) -> SandboxResult:
    last = next((ln for ln in reversed(stderr.strip().splitlines()) if ln.strip()), "")
    if "MemoryError" in stderr:
        return SandboxResult(False, Category.RUNTIME_ERROR, "MemoryError (memory limit exceeded)")
    if returncode is not None and returncode < 0:
        sig = -returncode
        if sig in (signal.SIGALRM, signal.SIGXCPU, signal.SIGKILL):
            return SandboxResult(False, Category.TIMEOUT, f"killed by signal {sig} (CPU/time limit)")
        return SandboxResult(False, Category.RUNTIME_ERROR, f"killed by signal {sig}")
    return SandboxResult(False, Category.RUNTIME_ERROR, f"exit {returncode}: {last[:200]}")
