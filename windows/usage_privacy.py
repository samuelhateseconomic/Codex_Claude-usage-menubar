"""Display-only projections. Never use these labels as accounting identities."""
import hashlib
from pathlib import PurePosixPath, PureWindowsPath
import unicodedata


def display_text(value):
    """Render controls, bidi/format characters and separators as visible escapes."""
    result = []
    for char in str(value):
        if unicodedata.category(char).startswith("C") or char in "\u2028\u2029":
            point = ord(char)
            result.append(("\\u%04x" if point <= 0xffff else "\\U%08x") % point)
        else:
            result.append(char)
    return "".join(result)


def metadata_label(value, kind, include_metadata=False):
    raw = str(value)
    if include_metadata or raw in ("not recorded", "Unknown project"):
        return display_text(raw)
    if kind == "id":
        return "id:" + hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    if kind == "project":
        windows, posix = PureWindowsPath(raw), PurePosixPath(raw)
        if windows.is_absolute() or posix.is_absolute():
            raw = windows.name if windows.is_absolute() else posix.name
            raw = (raw or "Root project") + " [path:" + hashlib.sha256(str(value).encode("utf-8", errors="surrogatepass")).hexdigest()[:8] + "]"
    return display_text(raw)
