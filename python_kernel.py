"""Persistent Python REPL wrapper used by exec-server.js.

Reads length-prefixed JSON requests from stdin, executes code in a single
shared namespace, and writes length-prefixed JSON responses to stdout.
State (variables, imports, opened files) carries across calls — that's the
entire point. Each call's stdout/stderr is captured per-call and returned
as a string; only stream redirection is per-call.

Wire format (both directions):
    <ascii decimal length>\\n<UTF-8 payload of exactly that many bytes>

Request payload: {"code": "<source>"}
Response payload: {"stdout": str, "stderr": str, "exit_code": int}

The wrapper never exits voluntarily; the parent process kills it on
timeout or session end. SystemExit from user code is caught and surfaces
as exit_code without terminating the kernel.
"""
from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

# Persistent namespace for all execs. __name__='__main__' so user code
# behaves like a script (e.g. `if __name__ == "__main__":` works).
_ns: dict = {"__name__": "__main__"}

# F-20: cap per-call output at 1 MB to prevent OOM on runaway output.
_MAX_OUTPUT_BYTES = 1 * 1024 * 1024


def _safe_str(s: str) -> str:
    """F-21: Remove lone surrogates that would cause json.dumps to raise UnicodeEncodeError."""
    return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _read_msg() -> str | None:
    """Read one length-prefixed message from stdin. None on EOF."""
    header = sys.stdin.buffer.readline()
    if not header:
        return None
    try:
        n = int(header.strip())
    except ValueError:
        return None
    if n < 0:
        return None
    payload = sys.stdin.buffer.read(n)
    if len(payload) < n:
        return None
    return payload.decode("utf-8")


def _write_msg(obj: dict) -> None:
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(f"{len(data)}\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main() -> None:
    while True:
        raw = _read_msg()
        if raw is None:
            return
        try:
            req = json.loads(raw)
            code = req["code"]
        except (json.JSONDecodeError, KeyError, TypeError):
            _write_msg({"stdout": "", "stderr": "kernel: malformed request", "exit_code": 1})
            continue

        out_buf, err_buf = io.StringIO(), io.StringIO()
        exit_code = 0
        try:
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                try:
                    compiled = compile(code, "<input>", "exec")
                    exec(compiled, _ns)
                except SystemExit as e:
                    if isinstance(e.code, int):
                        exit_code = e.code
                    elif e.code is None:
                        exit_code = 0
                    else:
                        # Non-int SystemExit code: print it like CPython does
                        print(e.code, file=err_buf)
                        exit_code = 1
                except BaseException:
                    exit_code = 1
                    traceback.print_exc(file=err_buf)
        except BaseException:
            # Defensive: contextlib redirect failure shouldn't kill the kernel.
            exit_code = 1
            err_buf.write(traceback.format_exc())

        out_str = out_buf.getvalue()
        err_str = err_buf.getvalue()

        # F-20: truncate oversized output to avoid OOM and huge framed responses.
        if len(out_str) > _MAX_OUTPUT_BYTES:
            out_str = out_str[:_MAX_OUTPUT_BYTES] + "\n[output truncated]"
        if len(err_str) > _MAX_OUTPUT_BYTES:
            err_str = err_str[:_MAX_OUTPUT_BYTES] + "\n[output truncated]"

        # F-21: sanitize lone surrogates before JSON serialization.
        _write_msg({
            "stdout": _safe_str(out_str),
            "stderr": _safe_str(err_str),
            "exit_code": exit_code,
        })


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
