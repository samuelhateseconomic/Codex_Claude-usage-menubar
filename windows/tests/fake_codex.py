"""Local protocol fixture: never reads credentials or contacts a provider."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
initialized = False
if mode == "descendant":
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    Path(sys.argv[2]).write_text(json.dumps({"parent":os.getpid(),"child":child.pid}), encoding="utf-8")
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialized":
        initialized = True
        continue
    if method is None:
        continue
    if mode in ("timeout", "descendant"):
        time.sleep(60)
    if mode == "exit":
        break
    if mode == "error":
        print(json.dumps({"id": message["id"], "error": {"message": "SECRET must not appear"}}), flush=True)
        continue
    if method == "initialize":
        assert message["params"]["clientInfo"]["name"] == "usage_tray"
        result = {"userAgent": "fake"}
    else:
        assert initialized
        # Notifications and independent server request IDs may interleave.
        print(json.dumps({"method": "account/updated", "params": {}}), flush=True)
        print(json.dumps({"id": message["id"], "method": "test/approval", "params": {}}), flush=True)
        rejection = json.loads(sys.stdin.readline())
        assert rejection["error"]["code"] == -32601
        if method == "account/read":
            result = {"account": {"type": "chatgpt", "email": "sample@example.invalid"}}
        else:
            result = {"rateLimits": {"primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 2000000000}}}
    print(json.dumps({"id": message["id"], "result": result}), flush=True)
