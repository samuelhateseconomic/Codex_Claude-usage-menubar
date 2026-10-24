"""Application identity without Git commands, provider calls or user metadata."""
from functools import lru_cache
import hashlib
from pathlib import Path
import sys

APP_VERSION = "0.13.0"


@lru_cache(maxsize=1)
def build_identity():
    # A source identity covers application modules, not histories/configuration.
    # A frozen identity fingerprints the delivered executable, including its code.
    frozen = getattr(sys, "frozen", False)
    paths = [Path(sys.executable)] if frozen else sorted(Path(__file__).parent.glob("usage_*.py"))
    digest = hashlib.sha256()
    try:
        for path in paths:
            if not frozen:
                digest.update(path.name.encode("utf-8"))
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    except OSError:
        return "unavailable"
    return ("exe-sha256:" if frozen else "source-sha256:") + digest.hexdigest()


BUILD_ID = build_identity()  # One immutable code identity per process.
