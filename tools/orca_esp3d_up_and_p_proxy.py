#!/usr/bin/env python3
"""Proxy Orca's ESP3D upload-and-print flow into a fixed SD folder.

Orca's ESP3D backend always uploads to `/upload_serial` and then starts the
print with `M23 <filename>` / `M24`. On this StarGraber setup the working web
UI flow uses the direct-SD `/upload` endpoint instead. This helper accepts
Orca's requests locally, uploads the file into a fixed SD folder, and rewrites
the later `M23` to point at that folder.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import posixpath
import threading
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import parse_qs, urlsplit

import requests

try:
    import cgi  # type: ignore
except ImportError:  # pragma: no cover - Python 3.13+ without legacy-cgi
    cgi = None


CONNECT_TIMEOUT = 5
READ_TIMEOUT = 300
DEFAULT_UPLOAD_TIMEOUT = 30 * 60
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 18889
DEFAULT_PRINTER_HOST = "192.168.3.13"
DEFAULT_TARGET_DIR = "/up_and_p/"


def normalize_target_dir(raw: str) -> str:
    target = raw.strip().replace("\\", "/")
    if not target:
        raise ValueError("target dir cannot be empty")
    target = "/" + target.strip("/") + "/"
    if target == "/":
        raise ValueError("target dir cannot be root")
    return target


def normalize_filename(raw: str) -> str:
    cleaned = raw.strip().strip('"').replace("\\", "/")
    name = PurePosixPath(cleaned).name
    if not name or name in {".", ".."}:
        raise ValueError("invalid filename")
    return name


def target_parent_and_leaf(target_dir: str) -> tuple[str, str]:
    path = PurePosixPath(target_dir.strip("/"))
    leaf = path.name
    parent = "/" if len(path.parts) == 1 else "/" + "/".join(path.parts[:-1]) + "/"
    return parent, leaf


@dataclass(frozen=True)
class ProxyConfig:
    printer_base_url: str
    target_dir: str
    upload_timeout: int
    verbose: bool = False

    def printer_url(self, path: str) -> str:
        return f"{self.printer_base_url}{path}"


@dataclass
class ProxyState:
    pending_filename: str | None = None
    last_uploaded_filename: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class UploadPayload:
    filename: str
    content_type: str
    stream: BinaryIO
    size: int
    hold: Any = None


class OrcaESP3DProxyServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], config: ProxyConfig):
        self.config = config
        self.state = ProxyState()
        self.session = requests.Session()
        super().__init__(server_address, OrcaESP3DProxyHandler)


class PrinterProxyError(RuntimeError):
    """Raised when the upstream printer reports a known blocking condition."""


class OrcaESP3DProxyHandler(BaseHTTPRequestHandler):
    server: OrcaESP3DProxyServer

    def log_message(self, fmt: str, *args: object) -> None:
        if self.server.config.verbose:
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            self.send_json(
                200,
                {
                    "status": "ok",
                    "printer_base_url": self.server.config.printer_base_url,
                    "target_dir": self.server.config.target_dir,
                    "upload_timeout": self.server.config.upload_timeout,
                    "last_uploaded_filename": self.server.state.last_uploaded_filename,
                },
            )
            return

        if parsed.path == "/command":
            self.handle_command_get(parsed.query)
            return

        self.send_text(404, f"Unsupported path: {parsed.path}\n")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/upload_serial":
            self.handle_orca_upload()
            return

        self.send_text(404, f"Unsupported path: {parsed.path}\n")

    def handle_command_get(self, raw_query: str) -> None:
        params = parse_qs(raw_query, keep_blank_values=True)
        command_key = "plain" if "plain" in params else "commandText" if "commandText" in params else None
        if not command_key or not params.get(command_key):
            self.send_text(400, "Missing command parameter.\n")
            return

        try:
            command_text = params[command_key][0]
            rewritten = self.rewrite_command_text(command_text)
        except ValueError as exc:
            self.send_text(400, f"{exc}\n")
            return

        if rewritten is None:
            self.send_text(200, "Ok")
            return

        params[command_key] = [rewritten]
        try:
            response = self.server.session.get(
                self.server.config.printer_url("/command"),
                params=params,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
        except requests.RequestException as exc:
            self.send_text(502, f"Printer command proxy failed: {exc}\n")
            return

        self.send_response_from_requests(response)

    def handle_orca_upload(self) -> None:
        try:
            upload = self.parse_orca_upload()
        except ValueError as exc:
            self.send_text(400, f"{exc}\n")
            return

        try:
            if self.server.config.verbose:
                print(
                    f"Forwarding upload {upload.filename} ({upload.size} bytes) "
                    f"to {self.server.config.target_dir}",
                    flush=True,
                )
            self.ensure_target_dir()
            size_key = f"{self.server.config.target_dir}{upload.filename}S"
            data = [
                ("path", self.server.config.target_dir),
                (size_key, str(upload.size)),
            ]
            files = {
                "myfile[]": (
                    f"{self.server.config.target_dir}{upload.filename}",
                    upload.stream,
                    upload.content_type or "application/octet-stream",
                )
            }
            response = self.server.session.post(
                self.server.config.printer_url("/upload"),
                data=data,
                files=files,
                # urllib3 keeps the connect timeout on the socket while it
                # sends the request body. ESP3D can stop reading for more than
                # five seconds while flushing a large file to the SD card, so
                # uploads need a longer write timeout than small GET requests.
                timeout=(
                    self.server.config.upload_timeout,
                    self.server.config.upload_timeout,
                ),
            )
            self.raise_for_known_printer_state(response)
        except PrinterProxyError as exc:
            print(f"Printer upload rejected for {upload.filename}: {exc}", flush=True)
            self.send_text(503, f"{exc}\n")
            return
        except requests.RequestException as exc:
            print(f"Printer upload failed for {upload.filename}: {exc}", flush=True)
            self.send_text(502, f"Printer upload proxy failed: {exc}\n")
            return
        finally:
            try:
                upload.stream.close()
            except Exception:
                pass

        if response.ok:
            with self.server.state.lock:
                self.server.state.last_uploaded_filename = upload.filename

        self.send_response_from_requests(response)

    def rewrite_command_text(self, command_text: str) -> str | None:
        outgoing: list[str] = []
        lines = [line.strip() for line in command_text.replace("\r", "\n").split("\n") if line.strip()]

        with self.server.state.lock:
            for line in lines:
                upper = line.upper()
                if upper.startswith("M23 "):
                    filename = normalize_filename(line[4:].strip())
                    self.server.state.pending_filename = filename
                    if self.server.config.verbose:
                        print(f"Stashed Orca M23 for {filename}", flush=True)
                    continue

                if upper == "M24" and self.server.state.pending_filename:
                    filename = self.server.state.pending_filename
                    sd_path = posixpath.join(self.server.config.target_dir, filename)
                    outgoing.append(f"M23 {sd_path}")
                    outgoing.append("M24")
                    self.server.state.pending_filename = None
                    if self.server.config.verbose:
                        print(f"Rewrote Orca start-print to {sd_path}", flush=True)
                    continue

                outgoing.append(line)

        if not outgoing:
            return None
        return "\n".join(outgoing)

    def ensure_target_dir(self) -> None:
        parent, leaf = target_parent_and_leaf(self.server.config.target_dir)
        response = self.server.session.get(
            self.server.config.printer_url("/upload"),
            params={"path": parent, "action": "createdir", "filename": leaf},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        response.raise_for_status()
        self.raise_for_known_printer_state(response)

    def parse_orca_upload(self) -> UploadPayload:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Empty upload body.")

        if cgi is not None:
            environ = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(content_length),
            }
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ=environ,
                keep_blank_values=True,
            )
            if "file" not in form:
                raise ValueError("Expected Orca multipart field named 'file'.")

            upload_field = form["file"]
            if isinstance(upload_field, list):
                upload_field = upload_field[0]

            filename = normalize_filename(upload_field.filename or "")
            stream = upload_field.file
            content_type = getattr(upload_field, "type", "") or "application/octet-stream"
            size = self.stream_size(stream)
            return UploadPayload(filename=filename, content_type=content_type, stream=stream, size=size, hold=form)

        body = self.rfile.read(content_length)
        return self.parse_orca_upload_email(body)

    def parse_orca_upload_email(self, body: bytes) -> UploadPayload:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            raise ValueError("Expected multipart/form-data upload.")

        header_block = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        message = BytesParser(policy=email_policy).parsebytes(header_block + body)
        if not message.is_multipart():
            raise ValueError("Malformed multipart upload.")

        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") != "file":
                continue

            filename = normalize_filename(part.get_filename() or "")
            payload = part.get_payload(decode=True) or b""
            return UploadPayload(
                filename=filename,
                content_type=part.get_content_type(),
                stream=io.BytesIO(payload),
                size=len(payload),
            )

        raise ValueError("Expected Orca multipart field named 'file'.")

    @staticmethod
    def stream_size(stream: BinaryIO) -> int:
        current = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if current not in (0, size):
            stream.seek(current)
            stream.seek(0)
        return size

    def send_response_from_requests(self, response: requests.Response) -> None:
        body = response.content
        content_type = response.headers.get("Content-Type", "text/plain; charset=utf-8")
        self.send_response(response.status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def raise_for_known_printer_state(response: requests.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            return

        status = str(payload.get("status", "")).strip().lower()
        if status == "no sd card":
            raise PrinterProxyError("Printer direct-SD endpoint reports: No SD Card")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Proxy Orca ESP3D uploads into a fixed direct-SD folder."
    )
    parser.add_argument("--listen-host", default=DEFAULT_LISTEN_HOST, help="Host to bind locally.")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT, help="Local port to bind.")
    parser.add_argument(
        "--printer-host",
        default=DEFAULT_PRINTER_HOST,
        help="ESP3D printer host or host:port without a URL scheme.",
    )
    parser.add_argument(
        "--target-dir",
        default=DEFAULT_TARGET_DIR,
        help="SD directory that should receive every Orca upload.",
    )
    parser.add_argument(
        "--upload-timeout",
        type=int,
        default=DEFAULT_UPLOAD_TIMEOUT,
        help="Maximum seconds without upload socket progress before failing.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print proxied actions to stderr.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.upload_timeout <= 0:
        raise SystemExit("--upload-timeout must be greater than zero")
    config = ProxyConfig(
        printer_base_url=f"http://{args.printer_host}",
        target_dir=normalize_target_dir(args.target_dir),
        upload_timeout=args.upload_timeout,
        verbose=args.verbose,
    )

    server = OrcaESP3DProxyServer((args.listen_host, args.listen_port), config)
    bind = f"http://{args.listen_host}:{args.listen_port}"
    print(
        f"Listening on {bind} and forwarding Orca uploads to "
        f"{config.printer_base_url}{config.target_dir}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
