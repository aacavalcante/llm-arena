"""Runner executado dentro do sandbox com `python3 -I -S`. Só stdlib.

Uso: python3 -I -S runner_script.py <workdir> <mem_mb> <cpu_s>
Lê <workdir>/submission.py e <workdir>/tests.json, escreve <workdir>/result.json.
"""
import io
import json
import math
import os
import resource
import signal
import sys
import time
import traceback


def apply_limits(mem_mb, cpu_s):
    mem = mem_mb * 1024 * 1024
    limits = [
        (resource.RLIMIT_AS, (mem, mem)),
        (resource.RLIMIT_CPU, (cpu_s, cpu_s + 1)),
        (resource.RLIMIT_NPROC, (64, 64)),
        (resource.RLIMIT_FSIZE, (1 << 20, 1 << 20)),
        (resource.RLIMIT_NOFILE, (32, 32)),
        (resource.RLIMIT_CORE, (0, 0)),
    ]
    for res, val in limits:
        try:
            resource.setrlimit(res, val)
        except (ValueError, OSError):
            pass


def normalize(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, (list, tuple)):
        return [normalize(i) for i in x]
    if isinstance(x, (set, frozenset)):
        items = [normalize(i) for i in x]
        try:
            return sorted(items)
        except TypeError:
            return sorted(items, key=repr)
    if isinstance(x, dict):
        return {str(k): normalize(v) for k, v in x.items()}
    return x


def _eq(a, b, tol):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) or isinstance(b, float):
            return math.isclose(a, b, rel_tol=1e-9, abs_tol=tol)
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_eq(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k], tol) for k in a)
    return a == b


def outputs_equal(actual, expected, tol=1e-6):
    return _eq(normalize(actual), normalize(expected), tol)


def short(x, n=200):
    try:
        r = repr(x)
    except Exception:  # noqa: BLE001
        r = "<unrepr>"
    return r if len(r) <= n else r[: n - 3] + "..."


def run(source, spec):
    t0 = time.perf_counter()
    fn_name = spec["function"]
    tests = spec["tests"]
    tol = spec.get("float_tol") or 1e-6
    total = len(tests)
    result = {"passed": False, "category": "runtime_error", "detail": "", "tests_total": total, "tests_passed": 0,
              "failed_test": None, "elapsed_ms": 0}
    try:
        code = compile(source, "submission.py", "exec")
    except SyntaxError as e:
        result["category"] = "syntax_error"
        result["detail"] = "line %s: %s" % (e.lineno, e.msg)
        return result
    ns = {"__name__": "submission"}
    real_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        try:
            exec(code, ns)
        except BaseException as e:  # noqa: BLE001
            result["detail"] = "at import: %s" % short(e)
            return result
        fn = ns.get(fn_name)
        if not callable(fn):
            result["detail"] = "function %s not defined" % fn_name
            return result
        for i, t in enumerate(tests):
            args = t.get("args", [])
            kwargs = t.get("kwargs", {}) or {}
            try:
                actual = fn(*args, **kwargs)
            except BaseException as e:  # noqa: BLE001
                result["detail"] = "test %d: %s" % (i, short(e))
                result["failed_test"] = {"index": i, "args": short(args), "expected": short(t.get("expected")),
                                         "actual": None, "error": short(e)}
                return result
            if not outputs_equal(actual, t.get("expected"), tol):
                result["category"] = "wrong_answer"
                result["detail"] = "test %d: %s -> expected %s, got %s" % (
                    i, short(args, 80), short(t.get("expected"), 80), short(actual, 80))
                result["failed_test"] = {"index": i, "args": short(args), "expected": short(t.get("expected")),
                                         "actual": short(actual), "error": None}
                return result
            result["tests_passed"] = i + 1
        result["passed"] = True
        result["category"] = "ok"
        result["detail"] = "%d/%d tests passed" % (total, total)
        return result
    finally:
        sys.stdout = real_stdout
        result["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)


def main():
    workdir = sys.argv[1]
    mem_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    cpu_s = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    apply_limits(mem_mb, cpu_s)
    signal.alarm(cpu_s + 1)
    sys.setrecursionlimit(3000)
    with open(os.path.join(workdir, "tests.json")) as f:
        spec = json.load(f)
    with open(os.path.join(workdir, "submission.py")) as f:
        source = f.read()
    try:
        result = run(source, spec)
    except BaseException as e:  # noqa: BLE001
        result = {"passed": False, "category": "runtime_error", "detail": "runner: %s" % short(e),
                  "tests_total": len(spec.get("tests", [])), "tests_passed": 0, "failed_test": None,
                  "elapsed_ms": 0}
        traceback.print_exc()
    tmp = os.path.join(workdir, "result.json.tmp")
    with open(tmp, "w") as f:
        json.dump(result, f)
    os.replace(tmp, os.path.join(workdir, "result.json"))


if __name__ == "__main__":
    main()
