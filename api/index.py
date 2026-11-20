"""TEMPORÁRIO (debug): mostra o que a Vercel entrega ao ASGI."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from salim.app import create_app  # noqa: E402

_inner = create_app(seed=False)


async def app(scope, receive, send):
    if scope["type"] == "http" and b"__scope=1" in scope.get("query_string", b""):
        info = {
            "path": scope.get("path"),
            "raw_path": (scope.get("raw_path") or b"").decode("latin1"),
            "root_path": scope.get("root_path"),
            "query": scope.get("query_string", b"").decode(),
            "headers": [k.decode() for k, _ in scope.get("headers", [])],
            "hdr_values": {k.decode(): v.decode()[:120] for k, v in scope.get("headers", [])
                           if k.decode().startswith(("x-vercel", "x-matched", "x-forwarded-host", "x-now", "x-invoke"))},
        }
        body = json.dumps(info).encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
        return
    await _inner(scope, receive, send)
