"""
test_mcp_bridge.py — Unit tests for mcp_bridge.py using a mock Unix socket server.

Run with:
    python3 test/test_mcp_bridge.py
"""

import json
import os
import socket
import sys
import tempfile
import threading
import unittest

# Ensure the repo root is on the path so we can import mcp_bridge
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mcp_bridge


class MockBridgeServer:
    """
    A minimal Unix socket server that serves pre-configured responses.
    Each handler callable receives the parsed request dict and returns a response dict.
    """

    def __init__(self, sock_path: str, handler):
        self.sock_path = sock_path
        self.handler = handler
        self._server_sock = None
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        # Clean up any stale socket file
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(self.sock_path)
        self._server_sock.listen(5)
        self._server_sock.settimeout(2)

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop_event.is_set():
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn):
        try:
            buf = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b'\n' in buf:
                    break
            line = buf.split(b'\n')[0]
            request = json.loads(line.decode('utf-8'))
            response = self.handler(request)
            conn.sendall((json.dumps(response) + '\n').encode('utf-8'))
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()
        try:
            self._server_sock.close()
        except Exception:
            pass
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        if self._thread:
            self._thread.join(timeout=3)


class TestMcpBridgeCall(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix='.sock', prefix='test_bridge_')
        # Set env var so mcp_bridge uses our test socket
        os.environ['ONLYCODES_BRIDGE_SOCK'] = self.tmp
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.stop()
        os.environ.pop('ONLYCODES_BRIDGE_SOCK', None)
        try:
            os.unlink(self.tmp)
        except FileNotFoundError:
            pass

    def _start_server(self, handler):
        self.server = MockBridgeServer(self.tmp, handler)
        self.server.start()
        # Give the server a moment to bind
        import time
        time.sleep(0.05)

    def test_call_returns_result_dict_on_success(self):
        """call() returns the result dict when server responds with success."""
        def handler(req):
            return {"result": {"pr_url": "https://github.com/foo/bar/pull/1"}}

        self._start_server(handler)
        result = mcp_bridge.call("github", "create_pr", {"title": "Test", "body": "body"})
        self.assertIsInstance(result, dict)
        self.assertEqual(result["pr_url"], "https://github.com/foo/bar/pull/1")

    def test_call_raises_mcp_bridge_error_on_server_error(self):
        """call() raises McpBridgeError when the server returns error=True."""
        def handler(req):
            return {"error": True, "message": "Tool not found"}

        self._start_server(handler)
        with self.assertRaises(mcp_bridge.McpBridgeError) as ctx:
            mcp_bridge.call("github", "nonexistent_tool", {})
        self.assertIn("Tool not found", str(ctx.exception))

    def test_call_raises_mcp_bridge_error_on_server_error_without_message(self):
        """call() raises McpBridgeError with 'unknown error' when server omits message."""
        def handler(req):
            return {"error": True}

        self._start_server(handler)
        with self.assertRaises(mcp_bridge.McpBridgeError) as ctx:
            mcp_bridge.call("github", "some_tool", {})
        self.assertIn("unknown error", str(ctx.exception))

    def test_get_schema_returns_schema_dict_on_success(self):
        """get_schema() returns the schema dict when server responds with success."""
        expected_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"}
            },
            "required": ["title"]
        }

        def handler(req):
            return {"schema": expected_schema}

        self._start_server(handler)
        schema = mcp_bridge.get_schema("github", "create_pr")
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema["type"], "object")
        self.assertIn("properties", schema)

    def test_get_schema_raises_mcp_bridge_error_on_server_error(self):
        """get_schema() raises McpBridgeError when the server returns error=True."""
        def handler(req):
            return {"error": True, "message": "Schema not found"}

        self._start_server(handler)
        with self.assertRaises(mcp_bridge.McpBridgeError) as ctx:
            mcp_bridge.get_schema("github", "unknown_tool")
        self.assertIn("Schema not found", str(ctx.exception))

    def test_mcp_bridge_error_on_connection_failure(self):
        """McpBridgeError (not raw socket error) raised when socket not present."""
        # No server started — socket file doesn't exist
        os.environ['ONLYCODES_BRIDGE_SOCK'] = '/tmp/definitely_nonexistent_test_bridge.sock'
        with self.assertRaises(mcp_bridge.McpBridgeError):
            mcp_bridge.call("github", "create_pr", {})

    def test_socket_path_uses_env_var_when_set(self):
        """_get_socket_path() returns the ONLYCODES_BRIDGE_SOCK env var value when set."""
        test_path = '/tmp/custom_test_bridge_path.sock'
        os.environ['ONLYCODES_BRIDGE_SOCK'] = test_path
        path = mcp_bridge._get_socket_path()
        self.assertEqual(path, test_path)

    def test_socket_path_uses_ppid_default_when_env_var_not_set(self):
        """_get_socket_path() uses ppid-based default when env var is not set."""
        os.environ.pop('ONLYCODES_BRIDGE_SOCK', None)
        path = mcp_bridge._get_socket_path()
        expected_ppid = os.getppid()
        self.assertEqual(path, f'/tmp/onlycodes-bridge-{expected_ppid}.sock')

    def test_call_sends_correct_request_method(self):
        """call() sends a request with method='call' and correct fields."""
        received_requests = []

        def handler(req):
            received_requests.append(req)
            return {"result": {"ok": True}}

        self._start_server(handler)
        mcp_bridge.call("github", "list_repos", {"org": "myorg"})

        self.assertEqual(len(received_requests), 1)
        req = received_requests[0]
        self.assertEqual(req["method"], "call")
        self.assertEqual(req["server"], "github")
        self.assertEqual(req["tool"], "list_repos")
        self.assertEqual(req["args"], {"org": "myorg"})

    def test_get_schema_sends_correct_request_method(self):
        """get_schema() sends a request with method='get_schema' and correct fields."""
        received_requests = []

        def handler(req):
            received_requests.append(req)
            return {"schema": {"type": "object"}}

        self._start_server(handler)
        mcp_bridge.get_schema("github", "create_pr")

        self.assertEqual(len(received_requests), 1)
        req = received_requests[0]
        self.assertEqual(req["method"], "get_schema")
        self.assertEqual(req["server"], "github")
        self.assertEqual(req["tool"], "create_pr")

    def test_mcp_bridge_error_is_exception_subclass(self):
        """McpBridgeError is a subclass of Exception."""
        self.assertTrue(issubclass(mcp_bridge.McpBridgeError, Exception))

    def test_call_result_fallback_when_no_result_key(self):
        """call() returns the full response when 'result' key is absent (no error)."""
        def handler(req):
            return {"data": "some_value"}

        self._start_server(handler)
        result = mcp_bridge.call("github", "some_tool", {})
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("data"), "some_value")

    def test_get_schema_fallback_when_no_schema_key(self):
        """get_schema() returns the full response when 'schema' key is absent (no error)."""
        def handler(req):
            return {"type": "object"}

        self._start_server(handler)
        schema = mcp_bridge.get_schema("github", "some_tool")
        self.assertIsInstance(schema, dict)
        self.assertEqual(schema.get("type"), "object")


if __name__ == '__main__':
    unittest.main(verbosity=2)
