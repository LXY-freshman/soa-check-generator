"""Compatibility helpers for runtimes supported by the compatibility branch."""

try:
    from dataclasses import asdict, dataclass, field
except ImportError as exc:  # pragma: no cover - only exercised on Python 3.6 without the backport
    raise RuntimeError("Python 3.6 requires the dataclasses backport; install requirements-py36.txt") from exc

try:
    from http.server import ThreadingHTTPServer
except ImportError:  # pragma: no cover - Python 3.6 fallback
    from http.server import HTTPServer
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True
