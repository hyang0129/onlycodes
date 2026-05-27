"""mitmproxy addon: capture all chatgpt/openai traffic into a single dir.

Used by scripts/codex_artifact_one_task.sh — that script spins up one
mitmdump per task, configures this addon with ONLYCODES_CAPTURE_DIR,
and writes all of that task's traffic into the per-task dir.

No prompt_cache_key segmentation needed since each mitm instance only
sees one task's traffic.
"""
import os
import json
import threading
from pathlib import Path
from mitmproxy import http

OUT = Path(os.environ.get("ONLYCODES_CAPTURE_DIR", "/tmp/codex_capture_per_task_default"))
OUT.mkdir(parents=True, exist_ok=True)

_counter = [0]
_lock = threading.Lock()


def _next_seq() -> int:
    with _lock:
        _counter[0] += 1
        return _counter[0]


def _write_payload(base: str, body_bytes: bytes) -> None:
    if not body_bytes:
        return
    try:
        data = json.loads(body_bytes.decode("utf-8"))
        with open(OUT / f"{base}.json", "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        with open(OUT / f"{base}.raw", "wb") as f:
            f.write(body_bytes)


def request(flow: http.HTTPFlow) -> None:
    h = flow.request.host
    if "chatgpt.com" not in h and "openai.com" not in h:
        return
    body_bytes = flow.request.raw_content or b""
    n = _next_seq()
    base = f"{n:04d}-http-{flow.request.method}-C2S"
    with open(OUT / f"{base}.url", "w") as f:
        f.write(f"{flow.request.method} {flow.request.url}\n")
    _write_payload(base, body_bytes)


def websocket_message(flow: http.HTTPFlow) -> None:
    h = flow.request.host
    if "chatgpt.com" not in h and "openai.com" not in h:
        return
    if not flow.websocket or not flow.websocket.messages:
        return
    msg = flow.websocket.messages[-1]
    data_bytes = msg.content
    n = _next_seq()
    direction = "C2S" if msg.from_client else "S2C"
    base = f"{n:04d}-ws-{direction}"
    _write_payload(base, data_bytes)
