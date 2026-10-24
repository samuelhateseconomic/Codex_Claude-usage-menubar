"""Opt-in synthetic browser test driver; never imported by the application.

Use --control-dir under windows/build. Write a JSON array to steps.json;
each query consumes one entry: fail, conflict, hold, or normal. A held query
continues when release exists or after 20 seconds. No source/credential IO.
The production preview handler still owns cookies, origin checks and assets.
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_hub import HubService, create_server


class FaultService(HubService):
    def __init__(self, control):
        super().__init__(demo=True)
        self.control = control
        self.fault_lock = threading.Lock()

    def query(self, params):
        with self.fault_lock:
            path = self.control / "steps.json"
            steps = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else []
            action = steps.pop(0) if steps else "normal"
            path.write_text(json.dumps(steps), encoding="utf-8")
        print(f"Synthetic query: {action}", flush=True)
        if action == "fail":
            raise RuntimeError("synthetic unavailable snapshot")
        if action == "conflict":
            raise LookupError("synthetic revision conflict")
        if action == "hold":
            deadline = time.monotonic() + 20
            while not (self.control / "release").exists() and time.monotonic() < deadline:
                time.sleep(.05)
        return super().query(params)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--control-dir", required=True, type=Path)
    args = parser.parse_args()
    control = args.control_dir.resolve()
    build = Path(__file__).resolve().parents[1] / "build"
    if not control.is_relative_to(build.resolve()) or control == build.resolve():
        parser.error("Use a dedicated control folder beneath windows/build")
    control.mkdir(parents=True, exist_ok=True)
    service = FaultService(control)
    service.refresh()
    server = create_server(service, args.port)
    print(f"Synthetic fault preview: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
