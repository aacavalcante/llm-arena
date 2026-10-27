#!/usr/bin/env python3
"""Mostra o que o isolamento do sandbox consegue fazer neste host/container."""

import asyncio
import resource

from llmarena.sandbox.capabilities import probe
from llmarena.sandbox.executor import SubprocessSandbox


class _Spec:
    function = "f"
    float_tol = None

    @staticmethod
    def test_dicts():
        return [{"args": [], "kwargs": {}, "expected": True}]


async def main() -> None:
    caps = probe()
    print(f"unshare prefix: {list(caps.netns_prefix) or 'NENHUM'}  notas: {list(caps.notes)}")
    sb = SubprocessSandbox()
    net = await sb.run(
        "import socket\ndef f():\n    socket.create_connection(('1.1.1.1', 53), timeout=1)\n    return True\n",
        _Spec(),
    )
    print(
        f"rede dentro do sandbox (sem static check): {'ABERTA' if net.passed else 'bloqueada -> ' + net.detail}"
    )
    loop = await sb.run("def f():\n    while True: pass\n", _Spec())
    print(f"loop infinito: {loop.category.value} em {loop.elapsed_ms} ms ({loop.detail})")
    mem = await sb.run("def f():\n    x = [0] * (10**9)\n    return True\n", _Spec())
    print(f"alocação gigante: {mem.category.value} ({mem.detail})")
    print(f"RLIMIT_NPROC do servidor: {resource.getrlimit(resource.RLIMIT_NPROC)}")


asyncio.run(main())
