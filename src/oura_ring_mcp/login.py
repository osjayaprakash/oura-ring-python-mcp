"""`oura-ring-mcp auth`: sign in to Oura once in the browser and save the OAuth tokens."""

from __future__ import annotations

import asyncio
import secrets
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
    b"<!doctype html><meta charset=utf-8><title>oura-ring-mcp</title>"
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
    return parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS and parts.port is not None


class _RedirectCatcher(HTTPServer):
    """Serves the redirect URI on a background thread until the browser lands on it.

    A thread, because opening the browser can block until it exits (e.g. a $BROWSER
    command), and the redirect must be answered meanwhile.
    """

    def __init__(self, redirect_uri: str) -> None:
        self.parts = urlsplit(redirect_uri)
        self.captured: str | None = None
        self.done = threading.Event()
        super().__init__((self.parts.hostname or "localhost", self.parts.port or 80), _Handler)
        self._thread = threading.Thread(target=self.serve_forever, args=(0.1,), daemon=True)

    def __enter__(self) -> _RedirectCatcher:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.shutdown()
        self._thread.join()
        self.server_close()

    def wait(self, timeout: float) -> str:
        if not self.done.wait(timeout) or self.captured is None:
            raise LoginError("Timed out waiting for the Oura sign-in to finish.")
        return self.captured


class _Handler(BaseHTTPRequestHandler):
    server: _RedirectCatcher

    def do_GET(self) -> None:  # noqa: N802
        parts = self.server.parts
        if urlsplit(self.path).path != (parts.path or "/"):
            self.send_error(404)  # e.g. the browser asking for /favicon.ico
            return
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_DONE_PAGE)
        self.server.captured = f"{parts.scheme}://{parts.netloc}{self.path}"
        self.server.done.set()

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
