"""`oura-ring-python-mcp auth`: sign in to Oura once in the browser and save the OAuth tokens."""

from __future__ import annotations

import asyncio
import secrets
import socket
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TextIO
from urllib.parse import parse_qs, urlsplit

import httpx2

from oura_ring_mcp.config import Settings
from oura_ring_mcp.core.oauth import OuraOAuth
from oura_ring_mcp.core.tokens import TokenStore

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}
_TIMEOUT_SECONDS = 300

_DONE_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>oura-ring-python-mcp</title>"
    b"<p>Oura sign-in received. You can close this tab and return to the terminal.</p>"
)


class LoginError(Exception):
    """The browser sign-in did not produce an authorization code."""


def code_from_redirect(url: str, state: str) -> str:
    """The authorization code from the URL Oura redirected to."""
    query = parse_qs(urlsplit(url.strip()).query)
    if query.get("state", [None])[0] != state:
        raise LoginError("The redirect's state does not match this sign-in; start again.")
    if "error" in query:
        raise LoginError(f"Oura did not authorize access: {query['error'][0]}.")
    code = query.get("code", [""])[0]
    if not code:
        raise LoginError("The redirect has no authorization code.")
    return code


def _catches_locally(redirect_uri: str) -> bool:
    parts = urlsplit(redirect_uri)
    return parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS and bool(parts.port)


def _loopback_addresses(host: str) -> list[tuple[str, socket.AddressFamily]]:
    # Browsers may resolve `localhost` to ::1 or 127.0.0.1, so listen on both.
    if host == "localhost":
        return [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)]
    return [(host, socket.AF_INET)]


class _LoopbackServer(HTTPServer):
    def __init__(self, address: tuple[str, int], family: socket.AddressFamily, catcher):
        self.address_family = family
        self.catcher: _RedirectCatcher = catcher
        super().__init__(address, _Handler)


class _RedirectCatcher:
    """Serves the redirect URI on background threads until the browser lands on it.

    Threads, because opening the browser can block until it exits (e.g. a $BROWSER
    command), and the redirect must be answered meanwhile.
    """

    def __init__(self, redirect_uri: str) -> None:
        self.parts = urlsplit(redirect_uri)
        self.captured: str | None = None
        self.done = threading.Event()
        self._lock = threading.Lock()
        self._servers: list[_LoopbackServer] = []
        port = self.parts.port or 80
        try:
            for host, family in _loopback_addresses(self.parts.hostname or "localhost"):
                try:
                    self._servers.append(_LoopbackServer((host, port), family, self))
                except OSError:
                    # ::1 unavailable (no IPv6, or taken by another program): the IPv4
                    # listener is enough, and `--paste` covers a browser that insists on ::1.
                    if family is socket.AF_INET6:
                        continue
                    raise
        except OSError:
            self._close()
            raise
        self._threads = [
            threading.Thread(target=server.serve_forever, args=(0.1,), daemon=True)
            for server in self._servers
        ]

    def __enter__(self) -> _RedirectCatcher:
        for thread in self._threads:
            thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        for server in self._servers:
            server.shutdown()
        for thread in self._threads:
            thread.join()
        self._close()

    def _close(self) -> None:
        for server in self._servers:
            server.server_close()

    def record(self, url: str) -> None:
        """Keep the first redirect; a reload or retry must not replace its code."""
        with self._lock:
            if self.captured is None:
                self.captured = url
                self.done.set()

    def wait(self, timeout: float) -> str:
        if not self.done.wait(timeout) or self.captured is None:
            raise LoginError("Timed out waiting for the Oura sign-in to finish.")
        return self.captured


class _Handler(BaseHTTPRequestHandler):
    server: _LoopbackServer

    def do_GET(self) -> None:  # noqa: N802
        catcher = self.server.catcher
        parts = catcher.parts
        if urlsplit(self.path).path != (parts.path or "/"):
            self.send_error(404)  # e.g. the browser asking for /favicon.ico
            return
        # Record first: the code must survive the browser dropping the connection.
        catcher.record(f"{parts.scheme}://{parts.netloc}{self.path}")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_DONE_PAGE)

    def log_message(self, *args: object) -> None:
        pass  # stdout/stderr stay clean


def run_login(
    settings: Settings,
    *,
    paste: bool = False,
    open_browser: Callable[[str], object] = webbrowser.open,
    read_line: Callable[[str], str] = input,
    out: TextIO,
    transport: httpx2.AsyncBaseTransport | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> Path:
    """Run the browser sign-in and save the tokens. Returns the token file path."""
    oauth = OuraOAuth(
        settings.client_id,
        settings.client_secret,
        settings.redirect_uri,
        scopes=settings.scopes,
        transport=transport,
    )
    state = secrets.token_urlsafe(24)
    url = oauth.authorize_url(state)

    print(f"Sign in to Oura and allow access:\n\n  {url}\n", file=out)
    if paste or not _catches_locally(settings.redirect_uri):
        open_browser(url)
        redirected = read_line("After allowing access, paste the full URL you were sent to: ")
    else:
        try:
            catcher = _RedirectCatcher(settings.redirect_uri)
        except OSError as exc:
            raise LoginError(
                f"Cannot listen on {settings.redirect_uri} ({exc.strerror}). "
                "Free the port, or rerun with --paste."
            ) from None
        with catcher:  # listening before the browser can come back
            print(f"Waiting for Oura to redirect to {settings.redirect_uri} ...", file=out)
            open_browser(url)
            redirected = catcher.wait(timeout)

    code = code_from_redirect(redirected, state)
    tokens = asyncio.run(oauth.exchange_code(code))
    store = TokenStore(settings.token_file)
    store.save(tokens)
    print(f"Saved Oura tokens to {store.path}", file=out)
    return store.path
