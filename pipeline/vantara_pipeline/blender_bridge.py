"""Talk to a running Blender through the MCP-for-Blender add-on's socket.

The add-on (https://github.com/ahujasid/mcp-for-blender) listens on
127.0.0.1:9876 and accepts JSON commands such as ``get_scene_info`` or
``execute_code``. This is the same channel the blender-mcp server uses, for
scripted work without going through an MCP client:

    uv run python -m vantara_pipeline.blender_bridge get_scene_info
    uv run python -m vantara_pipeline.blender_bridge execute_code --code "print(1)"
"""

from __future__ import annotations

import argparse
import json
import socket
import sys

HOST, PORT = "127.0.0.1", 9876


def call(kind: str, params: dict | None = None, timeout: float = 600.0) -> dict:
    """Send one command and return the decoded reply; raises on an error status."""
    with socket.create_connection((HOST, PORT), timeout=timeout) as s:
        s.sendall(json.dumps({"type": kind, "params": params or {}}).encode())
        buf = b""
        while True:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
            try:
                reply = json.loads(buf.decode())
                break
            except json.JSONDecodeError:
                continue
        else:  # pragma: no cover
            reply = {}
    if reply.get("status") == "error":
        raise RuntimeError(f"{kind}: {reply.get('message')}")
    return reply.get("result", reply)


def run_python(code: str, timeout: float = 600.0) -> str:
    """Run Python inside Blender; returns whatever it printed."""
    result = call("execute_code", {"code": code}, timeout)
    return result.get("result", "") if isinstance(result, dict) else str(result)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command")
    p.add_argument("--params", default="{}", help="JSON object of parameters")
    p.add_argument("--code", help="shortcut for execute_code")
    a = p.parse_args()
    params = {"code": a.code} if a.code else json.loads(a.params)
    json.dump(call(a.command, params), sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
