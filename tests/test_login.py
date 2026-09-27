import io
import socket
import stat
import threading
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from oura_ring_mcp.config import load_settings
from oura_ring_mcp.core.tokens import TokenStore
from oura_ring_mcp.login import LoginError, code_from_redirect, run_login
from tests.core.mock_api import MockAPI

GRANT = {"access_token": "at-1", "expires_in": 86400, "refresh_token": "rt-1"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def settings_for(tmp_path, redirect_uri):
    return load_settings(
        {
            "OURA_CLIENT_ID": "cid",
            "OURA_CLIENT_SECRET": "csecret",
            "OURA_REDIRECT_URI": redirect_uri,
            "OURA_TOKEN_FILE": str(tmp_path / "tokens.json"),
        }
    )


def token_api() -> MockAPI:
    api = MockAPI()
    api.on("POST", "/oauth/token", json_body=GRANT)
    return api


def state_of(authorize_url: str) -> str:
    return parse_qs(urlsplit(authorize_url).query)["state"][0]


class FakeBrowser:
    """Plays Oura: after 'sign-in', sends the browser to the redirect URI."""

    def __init__(self, redirect_uri, *, code="the-code", error=None, favicon_first=True):
        self.redirect_uri = redirect_uri
        self.code, self.error, self.favicon_first = code, error, favicon_first
        self.pages: list[bytes] = []
        self.thread: threading.Thread | None = None

    def __call__(self, url: str) -> bool:
        state = state_of(url)
        query = f"error={self.error}" if self.error else f"code={self.code}&scope=daily"

        def visit():
            if self.favicon_first:
                base = urlsplit(self.redirect_uri)
                try:
                    urllib.request.urlopen(f"{base.scheme}://{base.netloc}/favicon.ico")
                except urllib.error.HTTPError:
                    pass
            with urllib.request.urlopen(f"{self.redirect_uri}?{query}&state={state}") as r:
                self.pages.append(r.read())

        self.thread = threading.Thread(target=visit)
        self.thread.start()
        return True


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_local_redirect_is_caught_and_tokens_saved(tmp_path, host):
    redirect = f"http://{host}:{free_port()}/callback"
    settings = settings_for(tmp_path, redirect)
    browser = FakeBrowser(redirect)
    api = token_api()
    out = io.StringIO()

    path = run_login(settings, open_browser=browser, out=out, transport=api.transport())
    browser.thread.join()

    saved = TokenStore(path).load()
    assert (saved.access_token, saved.refresh_token) == ("at-1", "rt-1")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert b"Oura sign-in received" in browser.pages[0]
    assert parse_qs(api.requests[0].content.decode())["code"] == ["the-code"]
    assert "Saved Oura tokens" in out.getvalue()


def test_browser_that_blocks_until_it_exits(tmp_path):
    # webbrowser.open waits for a $BROWSER command to exit; the redirect must still be served.
    redirect = f"http://localhost:{free_port()}/callback"
    browser = FakeBrowser(redirect, favicon_first=False)

    def blocking_browser(url):
        browser(url)
        browser.thread.join(timeout=5)
        assert not browser.thread.is_alive(), "redirect was not served while browser blocked"
        return True

    api = token_api()
    run_login(
        settings_for(tmp_path, redirect),
        open_browser=blocking_browser,
        out=io.StringIO(),
        transport=api.transport(),
        timeout=5,
    )
    assert TokenStore(tmp_path / "tokens.json").load().access_token == "at-1"


def test_denied_access(tmp_path):
    redirect = f"http://localhost:{free_port()}/callback"
    browser = FakeBrowser(redirect, error="access_denied", favicon_first=False)
    with pytest.raises(LoginError, match="access_denied"):
        run_login(settings_for(tmp_path, redirect), open_browser=browser, out=io.StringIO())
    browser.thread.join()
    assert not (tmp_path / "tokens.json").exists()


def test_timeout(tmp_path):
    redirect = f"http://localhost:{free_port()}/callback"
    with pytest.raises(LoginError, match="Timed out"):
        run_login(
            settings_for(tmp_path, redirect),
            open_browser=lambda url: True,
            out=io.StringIO(),
            timeout=0.2,
        )


def test_port_in_use_suggests_paste(tmp_path):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        redirect = f"http://127.0.0.1:{busy.getsockname()[1]}/callback"
        with pytest.raises(LoginError, match="--paste"):
            run_login(
                settings_for(tmp_path, redirect), open_browser=lambda u: True, out=io.StringIO()
            )


@pytest.mark.parametrize("paste", [True, False])
def test_paste_mode(tmp_path, paste):
    # --paste, or a redirect URI this machine can't serve (https, remote host).
    redirect = "http://localhost:47651/callback" if paste else "https://example.com/cb"
    opened: list[str] = []

    def read_line(prompt):
        return f"{redirect}?code=pasted&state={state_of(opened[0])}\n"

    api = token_api()
    run_login(
        settings_for(tmp_path, redirect),
        paste=paste,
        open_browser=opened.append,
        read_line=read_line,
        out=io.StringIO(),
        transport=api.transport(),
    )
    assert parse_qs(api.requests[0].content.decode())["code"] == ["pasted"]
    assert TokenStore(tmp_path / "tokens.json").load().access_token == "at-1"


def test_code_from_redirect():
    assert code_from_redirect("http://x/cb?code=abc&scope=daily&state=s", "s") == "abc"


@pytest.mark.parametrize(
    "url, message",
    [
        ("http://x/cb?code=abc&state=other", "state does not match"),
        ("http://x/cb?code=abc", "state does not match"),
        ("http://x/cb?error=access_denied&state=s", "access_denied"),
        ("http://x/cb?state=s", "no authorization code"),
    ],
)
def test_code_from_redirect_rejects(url, message):
    with pytest.raises(LoginError, match=message):
        code_from_redirect(url, "s")
