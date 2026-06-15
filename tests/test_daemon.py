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

from iterm2_cli import cli
from iterm2_cli import daemon as daemon_mod
from iterm2_cli.client import DaemonClient, DaemonError
from iterm2_cli.core import Controller
from iterm2_cli.daemon import Daemon, is_alive
from iterm2_cli.detect import State
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


def test_long_wait_does_not_block_other_commands(running_daemon):
    # busy のままのセッションで wait（タイムアウトまでブロック）を投げつつ、
    # 別接続の ping が即応することを確認（接続ごとスレッド処理 = HOL 回避）。
    fa, sockp, *_ = running_daemon
    fa._get(A).screen = ["esc to interrupt"]  # ずっと busy

    waiter = DaemonClient(sockp, SessionResolver())

    def do_wait():
        try:
            waiter.wait(session=A, until=State.IDLE, timeout=1.5, poll_interval=0.05)
        except DaemonError:
            pass  # wait_timeout を error で受ける

    th = threading.Thread(target=do_wait, daemon=True)
    th.start()
    time.sleep(0.2)  # wait が走行中であることを担保

    pinger = DaemonClient(sockp, SessionResolver())
    t0 = time.perf_counter()
    pinger._rpc("system.ping", {})
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.8, f"ping が wait に塞がれている: {elapsed:.2f}s"
    th.join(timeout=3)


def test_stop_daemon(running_daemon):
    _, sockp, d, th = running_daemon
    DaemonClient(sockp).stop_daemon()
    th.join(timeout=2)
    assert not th.is_alive()
    assert not is_alive(sockp)


def test_rpc_to_dead_socket_raises_daemon_error(short_sockdir):
    # 存在しない socket への接続は OSError ではなく DaemonError として整える（CLI で exit 2）。
    client = DaemonClient(short_sockdir / "nonexistent.sock", SessionResolver())
    with pytest.raises(DaemonError):
        client.list()


def test_bad_until_value_is_bad_request(running_daemon):
    _, sockp, *_ = running_daemon
    client = DaemonClient(sockp, SessionResolver())
    with pytest.raises(DaemonError) as ei:
        client._rpc("session.wait", {"session": A, "until": "bogus", "timeout": 0.1})
    assert "bad_request" in str(ei.value)


def test_every_backend_op_round_trips_through_daemon(running_daemon):
    """Backend の全操作をデーモン越しに通し、3層（client/handler/controller）の一致を担保。

    新操作を Backend に足したらこのテストの DRIVEN にも足す必要がある（= 操作表面の単一ゲート）。
    HANDLERS への登録漏れや params 名ズレはここで unknown_method/bad_request として顕在化する。
    """
    from iterm2_cli.backend import Backend

    fa, sockp, *_ = running_daemon
    fa._get(A).screen = ["$ ready"]  # busy マーカー無し → idle（wait が即返る）
    c = DaemonClient(sockp, SessionResolver())

    # 各 Backend 操作を 1 回ずつ実行（close は A を消すので最後）。idle セッションで wait も即返る。
    driven = {
        "list": lambda: c.list(),
        "send": lambda: c.send(None, "x", session=A),
        "send_key": lambda: c.send_key(None, ["enter"], session=A),
        "read": lambda: c.read(session=A),
        "busy": lambda: c.busy(session=A),
        "wait": lambda: c.wait(session=A, until=State.IDLE, timeout=1, poll_interval=0.05),
        "split": lambda: c.split(session=A),
        "tab": lambda: c.tab(),
        "focus": lambda: c.focus(session=A),
        "set_name": lambda: c.set_name(None, "renamed", session=A),
        "var_set": lambda: c.var_set(None, "user.k", "v", session=A),
        "var_get": lambda: c.var_get(None, "user.k", session=A),
        "close": lambda: c.close(session=A),
        "shutdown": lambda: None,  # ライフサイクル（socket 越しではない）
    }

    # 公開 Backend メソッド集合とテスト網羅集合が一致すること（新操作のテスト漏れを防ぐ）。
    backend_methods = {m for m in dir(Backend) if not m.startswith("_")}
    assert backend_methods == set(driven), (
        f"Backend と契約テストの操作集合が不一致: "
        f"未網羅={backend_methods - set(driven)} 余分={set(driven) - backend_methods}"
    )

    # close 以外を先に、close を最後に実行（A を消すため）。
    order = [k for k in driven if k != "close"] + ["close"]
    for name in order:
        if name == "shutdown":
            continue
        driven[name]()  # 例外（DaemonError 等）が出れば失敗


def test_set_name_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    client = DaemonClient(sockp, SessionResolver())
    client.set_name(None, "🟢 worker", session=A)
    assert fa._get(A).info.name == "🟢 worker"


def test_wait_until_text_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    fa._get(A).screen = ["Remote Control active"]
    client = DaemonClient(sockp, SessionResolver())
    # marker が既に出ているので即返る（state は idle = 条件到達）。
    assert client.wait(session=A, until_text="Remote Control active", timeout=1, poll_interval=0.05) == State.IDLE


def test_wait_until_text_times_out_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    fa._get(A).screen = ["nothing here"]
    client = DaemonClient(sockp, SessionResolver())
    with pytest.raises(DaemonError):  # wait_timeout を error で受ける
        client.wait(session=A, until_text="never appears", timeout=0.2, poll_interval=0.05)


def test_tab_in_window_over_socket(running_daemon):
    fa, sockp, *_ = running_daemon
    # A は window_id を持たないので、A と同じ窓を持つセッションを 1 つ用意する。
    fa.add_session("WIN-SESS", "anchor", window_id="w-1", is_active=False)
    client = DaemonClient(sockp, SessionResolver())
    new_sid = client.tab(window_id="w-1")
    new_info = next(s for s in client.list() if s.session_id == new_sid)
    assert new_info.window_id == "w-1"


def test_make_controller_prefers_daemon(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon_mod, "is_alive", lambda p, **kw: True)
    monkeypatch.setattr(daemon_mod, "default_socket_path", lambda: tmp_path / "d.sock")
    backend = cli.make_controller()
    assert isinstance(backend, DaemonClient)
