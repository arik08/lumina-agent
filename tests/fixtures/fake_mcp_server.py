from __future__ import annotations

import json
import os
from pathlib import Path
import sys


MODE = sys.argv[1]
LOG_PATH = Path(sys.argv[2])


def respond(request_id: object, result: dict[str, object]) -> None:
    sys.stdout.write(
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": result},
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


def respond_error(
    request_id: object, code: int, message: str, data: dict[str, object]
) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message, "data": data},
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    method = str(message.get("method", ""))
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(method + "\n")
    if "id" not in message:
        continue
    if method == "initialize":
        respond(
            message["id"],
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp", "version": "1.0"},
            },
        )
    elif method == "tools/list":
        value_type = "integer" if MODE == "drift" else "string"
        respond(
            message["id"],
            {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo a value",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"value": {"type": value_type}},
                            "required": ["value"],
                        },
                    },
                    {
                        "name": "not_allowed",
                        "inputSchema": {"type": "object"},
                    },
                ]
            },
        )
    elif method == "tools/call":
        arguments = message.get("params", {}).get("arguments", {})
        if MODE == "rpc_error":
            respond_error(
                message["id"],
                -32602,
                "Invalid parameter value",
                {
                    "field": "partnerCode",
                    "secret": os.environ.get("MCP_TEST_TOKEN", ""),
                },
            )
            continue
        respond(
            message["id"],
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"echo={arguments.get('value')};"
                            f"secret={os.environ.get('MCP_TEST_TOKEN', '')}"
                        ),
                    }
                ],
                "structuredContent": {
                    "value": arguments.get("value"),
                    "secret": os.environ.get("MCP_TEST_TOKEN", ""),
                },
                "isError": MODE == "tool_error",
            },
        )
