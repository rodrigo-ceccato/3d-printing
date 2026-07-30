#!/usr/bin/env python3
"""Launch OrcaSlicer with the local ESP3D proxy ensured in the background."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 18889
DEFAULT_PRINTER_HOST = "192.168.3.13"
DEFAULT_TARGET_DIR = "/up_and_p/"
DEFAULT_UPLOAD_TIMEOUT = 30 * 60
DEFAULT_ORCA_BIN = "/home/fopor/Software/OrcaSlicer_Linux_AppImage_V2.3.0.AppImage"
STARTUP_TIMEOUT = 5.0
RETRY_INTERVAL = 0.2

BASE_DIR = Path(__file__).resolve().parent
PROXY_SCRIPT = BASE_DIR / "orca_esp3d_up_and_p_proxy.py"
STATE_DIR = Path.home() / ".local" / "state" / "orca_esp3d_up_and_p_proxy"
PID_FILE = STATE_DIR / "proxy.pid"
LOG_FILE = STATE_DIR / "proxy.log"


def normalize_target_dir(raw: str) -> str:
    target = raw.strip().replace("\\", "/")
    if not target:
        raise ValueError("target dir cannot be empty")
    target = "/" + target.strip("/") + "/"
    if target == "/":
        raise ValueError("target dir cannot be root")
    return target


def proxy_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/"


def load_proxy_status(host: str, port: int) -> dict[str, Any] | None:
    try:
        with urlopen(proxy_url(host, port), timeout=0.5) as response:
            if response.status != 200:
                return None
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def proxy_matches(
    status: dict[str, Any],
    printer_host: str,
    target_dir: str,
    upload_timeout: int,
) -> bool:
    return (
        status.get("printer_base_url") == f"http://{printer_host}"
        and status.get("target_dir") == target_dir
        and status.get("upload_timeout") == upload_timeout
    )


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_pid(pid: int) -> None:
    ensure_state_dir()
    PID_FILE.write_text(f"{pid}\n")


def clear_pid() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def tail_log() -> str:
    try:
        data = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    if not data:
        return ""
    return "\n".join(data[-10:])


def stop_proxy(host: str, port: int) -> bool:
    pid = read_pid()
    if not pid:
        clear_pid()
        return False
    if not pid_is_running(pid):
        if not port_is_open(host, port):
            clear_pid()
            return False

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if not pid_is_running(pid) and not port_is_open(host, port):
            clear_pid()
            return True
        time.sleep(RETRY_INTERVAL)

    if pid_is_running(pid):
        os.kill(pid, signal.SIGKILL)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if not port_is_open(host, port):
            clear_pid()
            return True
        time.sleep(RETRY_INTERVAL)

    return False


def start_proxy(
    host: str,
    port: int,
    printer_host: str,
    target_dir: str,
    upload_timeout: int,
    verbose: bool,
) -> str:
    expected_printer = f"http://{printer_host}"
    status = load_proxy_status(host, port)
    if status:
        if proxy_matches(status, printer_host, target_dir, upload_timeout):
            return "reused"
        raise RuntimeError(
            f"Port {port} is already serving a different proxy instance: "
            f"{status.get('printer_base_url')} {status.get('target_dir')}"
        )

    if port_is_open(host, port):
        raise RuntimeError(f"Port {port} is already in use by another service.")

    ensure_state_dir()
    with LOG_FILE.open("ab") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(PROXY_SCRIPT),
                "--listen-host",
                host,
                "--listen-port",
                str(port),
                "--printer-host",
                printer_host,
                "--target-dir",
                target_dir,
                "--upload-timeout",
                str(upload_timeout),
                *(["--verbose"] if verbose else []),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    write_pid(proc.pid)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        status = load_proxy_status(host, port)
        if (
            status
            and proxy_matches(status, printer_host, target_dir, upload_timeout)
        ):
            return "started"
        if proc.poll() is not None:
            break
        time.sleep(RETRY_INTERVAL)

    clear_pid()
    log_tail = tail_log()
    detail = f"\n{log_tail}" if log_tail else ""
    raise RuntimeError(f"Proxy did not become ready on {host}:{port}.{detail}")


def launch_orca(orca_bin: str, orca_args: list[str]) -> int:
    proc = subprocess.run([orca_bin, *orca_args], check=False)
    return proc.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch OrcaSlicer with the ESP3D proxy ensured.")
    parser.add_argument("--orca-bin", default=DEFAULT_ORCA_BIN, help="Path to the OrcaSlicer executable.")
    parser.add_argument("--printer-host", default=DEFAULT_PRINTER_HOST, help="Printer ESP3D host or host:port.")
    parser.add_argument("--proxy-host", default=DEFAULT_PROXY_HOST, help="Local proxy listen host.")
    parser.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT, help="Local proxy listen port.")
    parser.add_argument("--target-dir", default=DEFAULT_TARGET_DIR, help="SD folder used for uploads.")
    parser.add_argument(
        "--upload-timeout",
        type=int,
        default=DEFAULT_UPLOAD_TIMEOUT,
        help="Maximum seconds without upload socket progress before failing.",
    )
    parser.add_argument("--verbose-proxy", action="store_true", help="Run the proxy in verbose logging mode.")
    parser.add_argument("--ensure-proxy-only", action="store_true", help="Ensure the proxy is running and then exit.")
    parser.add_argument("--stop-proxy", action="store_true", help="Stop the background proxy and exit.")
    parser.add_argument("orca_args", nargs=argparse.REMAINDER, help="Arguments forwarded to OrcaSlicer.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_dir = normalize_target_dir(args.target_dir)
    if args.upload_timeout <= 0:
        print("--upload-timeout must be greater than zero", file=sys.stderr)
        return 2

    if args.stop_proxy:
        stopped = stop_proxy(args.proxy_host, args.proxy_port)
        print("Stopped proxy." if stopped else "Proxy was not running.")
        return 0 if stopped else 1

    try:
        result = start_proxy(
            host=args.proxy_host,
            port=args.proxy_port,
            printer_host=args.printer_host,
            target_dir=target_dir,
            upload_timeout=args.upload_timeout,
            verbose=args.verbose_proxy,
        )
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.ensure_proxy_only:
        print(f"Proxy {result} on {args.proxy_host}:{args.proxy_port}.")
        return 0

    orca_args = list(args.orca_args)
    if orca_args and orca_args[0] == "--":
        orca_args = orca_args[1:]
    return launch_orca(args.orca_bin, orca_args)


if __name__ == "__main__":
    raise SystemExit(main())
