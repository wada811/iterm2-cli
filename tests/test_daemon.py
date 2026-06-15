"""daemon サーバ + DaemonClient を実 Unix socket 越しに往復させるテスト（iTerm2 不要）。

FakeAdapter を載せた Controller をデーモンに差し、socket framing〜dispatch を端から端まで通す。
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

from iterm2_cli import cli, daemon as daemon_mod
from iterm2_cli.client import DaemonClient, DaemonError
from iterm2_cli.core import Controller
from iterm2_cli.daemon import Daemon, is_alive
from iterm2_cli.resolver import SessionResolver
from tests.fakes import FakeAdapter

A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"


@pytest.fixture
def short_sockdir():
    # macOS の AF_UNIX パス長制限(~104)を避けるため /tmp 直下の短いパスを使う。
    d = tempfile.mkdtemp(dir="/tmp", prefix="i2c")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def running_daemon(short_sockdir):
    fa = FakeAdapter()
    fa.add_session(A, "pane-a", is_active=True)
    controller = Controller(fa, SessionResolver())
    sockp = short_sockdir / "s"
    d = Daemon(controller, sockp)
    th = threading.Thread(target=d.serve, daemon=True)
    th.start()
    for _ in range(200):
        if is_alive(sockp):
            break
        time.sleep(0.01)
    assert is_alive(sockp), "デーモンが起動しなかった"
    yield fa, sockp, d, th
    d.stop()
    th.join(timeout=2)


def test_list_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    client = DaemonClient(sockp, SessionResolver())
    assert [s.session_id for s in client.list()] == [A]
    assert client.list()[0].is_active is True


def test_send_and_send_key_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    client = DaemonClient(sockp, SessionResolver())
    client.send(None, "hi", session=A)
    client.send_key(None, ["enter"], session=A)
    assert fa._get(A).sent == ["hi", "\r"]


def test_read_and_busy_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    fa._get(A).screen = ["esc to interrupt"]
    client = DaemonClient(sockp, SessionResolver())
    assert client.read(session=A) == ["esc to interrupt"]
    assert client.busy(session=A).value == "busy"


def test_error_propagates_as_daemon_error(running_daemon):
    _, sockp, *_ = running_daemon
    client = DaemonClient(sockp, SessionResolver())
    with pytest.raises(DaemonError):
        client.read(session="missing")


def test_label_resolution_on_client_side(running_daemon):
    fa, sockp, *_ = running_daemon
    client = DaemonClient(sockp, SessionResolver(labels={"a": A}))
    client.send("a", "yo")  # ラベルはクライアントが解決して具体 id を送る
    assert fa._get(A).sent == ["yo"]


def test_stop_daemon(running_daemon):
    _, sockp, d, th = running_daemon
    DaemonClient(sockp).stop_daemon()
    th.join(timeout=2)
    assert not th.is_alive()
    assert not is_alive(sockp)


def test_make_controller_prefers_daemon(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_mod, "is_alive", lambda p, **kw: True)
    monkeypatch.setattr(daemon_mod, "default_socket_path", lambda: tmp_path / "d.sock")
    backend = cli.make_controller()
    assert isinstance(backend, DaemonClient)
