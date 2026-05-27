#!/usr/bin/env python3
"""
Logging pass-through proxy for OpenAI-compatible APIs.

Forwards every request to UPSTREAM (default https://api.openai.com) unchanged,
streams the response back, and side-logs:
  - per-request JSON body (with response_id / call sequence number)
  - per-response usage (including cached_input_tokens, cache_read details)

Use this to recover per-API-call usage when a CLI (e.g., codex) only exposes
aggregate-per-task usage in its own logs.

Usage:
  scripts/openai_logging_proxy.py --port 8088 --log-dir /tmp/openai-logs

Point a client at it:
  codex -c 'model_providers.openai.base_url="http://127.0.0.1:8088/v1"' exec ...
or:
  OPENAI_BASE_URL=http://127.0.0.1:8088/v1 your-other-client

The Authorization header is forwarded as-is, so any auth mode the upstream
accepts (API key, OAuth bearer) works.
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

DEFAULT_UPSTREAM = "https://api.openai.com"
COUNTER = 0
LOG_DIR: Path | None = None


def log_event(event: dict) -> None:
    if LOG_DIR is None:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"calls.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def make_app(upstream: str) -> FastAPI:
    app = FastAPI()
    client = httpx.AsyncClient(base_url=upstream, timeout=httpx.Timeout(300.0))

    async def proxy(request: Request, path: str):
        global COUNTER
        COUNTER += 1
        call_idx = COUNTER

        body_bytes = await request.body()
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length", "accept-encoding"}
        }
        target_url = f"/{path}"
        if request.url.query:
            target_url += f"?{request.url.query}"

        # Parse the request body for logging (best-effort)
        try:
            req_body = json.loads(body_bytes.decode())
        except Exception:
            req_body = {"__raw__": body_bytes[:500].decode("utf-8", "replace")}

        log_event({
            "ts": time.time(),
            "phase": "request",
            "call_idx": call_idx,
            "method": request.method,
            "path": target_url,
            "body": req_body,
        })

        upstream_req = client.build_request(
            request.method,
            target_url,
            content=body_bytes,
            headers=headers,
        )
        upstream_resp = await client.send(upstream_req, stream=True)

        # Stream the response and capture usage events along the way.
        # Server-Sent Events (SSE) responses contain `event: response.completed`
        # with usage in the final chunk; non-stream responses just have JSON.
        captured_chunks: list[bytes] = []
        captured_usage: list[dict] = []

        async def body_iter():
            buffer = b""
            try:
                async for chunk in upstream_resp.aiter_bytes():
                    yield chunk
                    captured_chunks.append(chunk)
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line_str = line.decode("utf-8", "replace").strip()
                        if line_str.startswith("data:"):
                            payload = line_str[5:].strip()
                            if payload and payload != "[DONE]":
                                try:
                                    j = json.loads(payload)
                                    # Capture usage where it appears (response.completed event)
                                    if isinstance(j, dict):
                                        if "usage" in j and isinstance(j["usage"], dict):
                                            captured_usage.append({
                                                "source": "sse_chunk_usage",
                                                "usage": j["usage"],
                                                "type": j.get("type"),
                                            })
                                        resp = j.get("response")
                                        if isinstance(resp, dict) and "usage" in resp:
                                            captured_usage.append({
                                                "source": "sse_response_usage",
                                                "type": j.get("type"),
                                                "usage": resp["usage"],
                                                "response_id": resp.get("id"),
                                            })
                                except Exception:
                                    pass
            finally:
                await upstream_resp.aclose()
                # If non-streaming JSON, parse it
                if not captured_usage and captured_chunks:
                    full = b"".join(captured_chunks)
                    try:
                        j = json.loads(full)
                        if isinstance(j, dict) and "usage" in j:
                            captured_usage.append({
                                "source": "json_body_usage",
                                "usage": j["usage"],
                                "response_id": j.get("id"),
                            })
                    except Exception:
                        pass
                log_event({
                    "ts": time.time(),
                    "phase": "response",
                    "call_idx": call_idx,
                    "status_code": upstream_resp.status_code,
                    "usages": captured_usage,
                })

        return StreamingResponse(
            body_iter(),
            status_code=upstream_resp.status_code,
            headers={k: v for k, v in upstream_resp.headers.items() if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}},
            media_type=upstream_resp.headers.get("content-type"),
        )

    # Catch-all route under /v1/...
    app.add_api_route("/{path:path}", proxy, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    return app


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    ap.add_argument("--log-dir", type=Path, default=Path("/tmp/openai-proxy-logs"))
    args = ap.parse_args()

    global LOG_DIR
    LOG_DIR = args.log_dir
    print(f"[proxy] forwarding to {args.upstream}", flush=True)
    print(f"[proxy] logging to {args.log_dir}/calls.jsonl", flush=True)

    import uvicorn
    uvicorn.run(make_app(args.upstream), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
