"""
mcp_bridge.py — Unix socket client for the onlycodes MCP bridge.

Placed in every execute_code cwd. Agent-written code uses this to call
sub-MCP tools via the bridge server running on the main MCP process.

Protocol: newline-delimited JSON (NDJSON) over Unix domain socket.
Socket path: ONLYCODES_BRIDGE_SOCK env var, or /tmp/onlycodes-bridge-{ppid}.sock

Usage:
    import mcp_bridge
    result = mcp_bridge.call("github", "create_pr", {"title": "...", "body": "..."})
    schema = mcp_bridge.get_schema("github", "create_pr")
"""

import json
import os
import socket
import time


class McpBridgeError(Exception):
    pass


def _get_socket_path():
    # Use env var if set (matches bridge-server.js)
    if 'ONLYCODES_BRIDGE_SOCK' in os.environ:
        return os.environ['ONLYCODES_BRIDGE_SOCK']
    # Default: use parent process PID (the main MCP server's PID)
    ppid = os.getppid()
    return f'/tmp/onlycodes-bridge-{ppid}.sock'


def _send_request(payload: dict) -> dict:
    sock_path = _get_socket_path()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(30)
        sock.connect(sock_path)

        # Send NDJSON request
        request_line = json.dumps(payload) + '\n'
        sock.sendall(request_line.encode('utf-8'))

        # Read NDJSON response
        buf = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b'\n' in buf:
                break

        response_line = buf.split(b'\n')[0]
        return json.loads(response_line.decode('utf-8'))
    except (ConnectionRefusedError, FileNotFoundError) as e:
        raise McpBridgeError(f"Cannot connect to bridge at {sock_path}: {e}") from e
    except socket.timeout:
        raise McpBridgeError(f"Bridge request timed out after 30s") from None
    except json.JSONDecodeError as e:
        raise McpBridgeError(f"Invalid JSON response from bridge: {e}") from e
    except OSError as e:
        raise McpBridgeError(f"Bridge socket error: {e}") from e
    finally:
        sock.close()


def call(server: str, tool: str, args: dict) -> dict:
    """Call a sub-MCP tool via the bridge. Returns the result dict."""
    response = _send_request({
        "method": "call",
        "server": server,
        "tool": tool,
        "args": args
    })
    if response.get("error"):
        raise McpBridgeError(f"Bridge error: {response.get('message', 'unknown error')}")
    return response.get("result", response)


def get_schema(server: str, tool: str) -> dict:
    """Fetch the JSON schema for a sub-MCP tool. Returns the schema dict."""
    response = _send_request({
        "method": "get_schema",
        "server": server,
        "tool": tool
    })
    if response.get("error"):
        raise McpBridgeError(f"Bridge error: {response.get('message', 'unknown error')}")
    return response.get("schema", response)
