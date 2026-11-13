"""Start the local SOA Generator service and open it in a browser."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _choose_port(requested: int) -> tuple[int, bool]:
    if requested == 0:
        return _free_port(), True
    if _port_available(requested):
        return requested, False
    return _free_port(), True


class _EmbeddedService:
    """Run the HTTP service in-process when this launcher is frozen."""

    def __init__(self, port: int) -> None:
        from http.server import ThreadingHTTPServer

        from soa_generator.service import Handler

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="soa-service", daemon=True)
        self.thread.start()

    def poll(self) -> int | None:
        return None if self.thread.is_alive() else 0

    def wait(self) -> int:
        self.thread.join()
        return 0

    def terminate(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def _start_service(port: int) -> Any:
    if getattr(sys, "frozen", False):
        return _EmbeddedService(port)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "soa_generator.service",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
    )


def _wait_for_health(url: str, process: Any, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    return False


def _stop(process: Any) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="Start the local SOA Generator service.")
    parser.add_argument("--port", type=int, default=8765, help="Preferred local port (default: 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically.")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")

    port, changed = _choose_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    health_url = f"http://127.0.0.1:{port}/api/health"
    print("Starting SOA Generator service...")
    if changed and args.port:
        print(f"Port {args.port} is busy; using port {port} instead.")
    try:
        process = _start_service(port)
        if not _wait_for_health(health_url, process):
            code = process.poll()
            print(f"The service did not become ready (exit code: {code}).", file=sys.stderr)
            return 1
        print(f"Open {url}")
        if not args.no_browser:
            webbrowser.open(url)
        print("Press Ctrl+C in this window to stop the service.")
        return process.wait()
    except KeyboardInterrupt:
        print("Stopping SOA Generator service...")
        return 0
    except OSError as exc:
        print(f"Could not start the local service: {exc}", file=sys.stderr)
        return 1
    finally:
        if "process" in locals():
            _stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
