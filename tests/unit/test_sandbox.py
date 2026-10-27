from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path

import pytest

from llmarena.domain.models import Category
from llmarena.sandbox.executor import RUNNER_PATH, SandboxLimits, SubprocessSandbox
from llmarena.sandbox.static_check import static_check
from tests.conftest import BAD_CODE, GOOD_CODE


@pytest.fixture(scope="module")
def sandbox() -> SubprocessSandbox:
    return SubprocessSandbox(SandboxLimits(wall_s=3.0, cpu_s=2, mem_mb=256, netns="auto"))


def _runner_module():
    spec = importlib.util.spec_from_file_location("runner_script", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def test_passing_solution(sandbox, challenge):
    res = await sandbox.run(GOOD_CODE, challenge)
    assert res.passed and res.category is Category.OK
    assert res.tests_passed == res.tests_total == 3


async def test_wrong_answer(sandbox, challenge):
    res = await sandbox.run(BAD_CODE, challenge)
    assert not res.passed and res.category is Category.WRONG_ANSWER
    assert res.failed_test["index"] == 0
    assert "expected 3" in res.detail


async def test_syntax_error(sandbox, challenge):
    res = await sandbox.run("def add(a, b)\n    return a + b\n", challenge)
    assert res.category is Category.SYNTAX_ERROR and "line 1" in res.detail


async def test_runtime_error_in_test(sandbox, challenge):
    res = await sandbox.run("def add(a, b):\n    return a / 0\n", challenge)
    assert res.category is Category.RUNTIME_ERROR and "ZeroDivisionError" in res.detail


async def test_function_missing(sandbox, challenge):
    res = await sandbox.run("def plus(a, b):\n    return a + b\n", challenge)
    assert res.category is Category.RUNTIME_ERROR and "not defined" in res.detail


async def test_infinite_loop_times_out(sandbox, challenge):
    t0 = asyncio.get_running_loop().time()
    res = await sandbox.run("def add(a, b):\n    while True:\n        pass\n", challenge)
    assert res.category is Category.TIMEOUT
    assert asyncio.get_running_loop().time() - t0 < 4.5


async def test_memory_bomb(sandbox, challenge):
    res = await sandbox.run("def add(a, b):\n    x = [0] * (10 ** 9)\n    return len(x)\n", challenge)
    assert not res.passed
    assert res.category in (Category.RUNTIME_ERROR, Category.TIMEOUT)
    assert "Memory" in res.detail or res.category is Category.TIMEOUT


async def test_input_gets_eof(sandbox, challenge):
    res = await sandbox.run("def add(a, b):\n    return int(input())\n", challenge)
    assert res.category is Category.RUNTIME_ERROR and "EOFError" in res.detail


async def test_print_spam_does_not_break_result(sandbox, challenge):
    res = await sandbox.run("def add(a, b):\n    print('x' * 100000)\n    return a + b\n", challenge)
    assert res.passed


async def test_fork_bomb_is_contained(sandbox, challenge):
    code = "import os\ndef add(a, b):\n    while True:\n        os.fork()\n"
    res = await sandbox.run(code, challenge)
    assert not res.passed
    assert res.category in (Category.TIMEOUT, Category.RUNTIME_ERROR)


async def test_file_write_is_limited(sandbox, challenge):
    code = "def add(a, b):\n    with open('/tmp/arena-evil', 'w') as f:\n        f.write('x' * (2 << 20))\n    return a + b\n"
    res = await sandbox.run(code, challenge)
    assert not res.passed
    Path("/tmp/arena-evil").unlink(missing_ok=True)


async def test_env_has_no_secrets(sandbox, challenge):
    code = "import os\ndef add(a, b):\n    return a + b if 'ANTHROPIC_API_KEY' not in os.environ and len(os.environ) < 6 else -999\n"
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    try:
        res = await sandbox.run(code, challenge)
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
    assert res.passed, res.detail


async def test_tempdir_cleaned(sandbox, challenge):
    before = {p for p in Path(tempfile.gettempdir()).glob("arena-*")}
    await sandbox.run(GOOD_CODE, challenge)
    after = {p for p in Path(tempfile.gettempdir()).glob("arena-*")}
    assert after <= before


async def test_cancellation_kills_process(sandbox, challenge):
    task = asyncio.create_task(sandbox.run("def add(a, b):\n    while True:\n        pass\n", challenge))
    await asyncio.sleep(0.4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_concurrent_runs(sandbox, challenge):
    results = await asyncio.gather(*(sandbox.run(GOOD_CODE, challenge) for _ in range(6)))
    assert all(r.passed for r in results)


def test_outputs_equal_semantics():
    m = _runner_module()
    eq = m.outputs_equal
    assert eq((1, 2), [1, 2])
    assert eq({3, 1, 2}, [1, 2, 3])
    assert eq({1: "a"}, {"1": "a"})
    assert eq(0.1 + 0.2, 0.3)
    assert not eq(True, 1)
    assert not eq(1, True)
    assert not eq(None, 0)
    assert eq(None, None)
    assert eq([[1, (2, 3)]], [[1, [2, 3]]])
    assert not eq([1, 2], [1, 2, 3])
    assert eq({"a": [1.0, 2]}, {"a": [1, 2]})


def test_static_check_allows_and_blocks():
    assert static_check("import math\nfrom collections import Counter\n") is None
    assert "os" in static_check("import os\n").detail
    assert static_check("from os.path import join\n") is not None
    assert static_check("__import__('os')\n") is not None
    assert static_check("open('/etc/passwd')\n") is not None
    assert static_check("x = input()\n") is not None
    assert static_check("from math import *\n") is not None
    assert static_check("().__class__.__subclasses__()\n") is not None
    assert static_check("def f(:\n") is None  # erro de sintaxe fica para o sandbox reportar
