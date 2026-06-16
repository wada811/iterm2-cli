"""実 iTerm2 への結合スモーク（オプトイン）。

通常の `uv run pytest` ではスキップする。実行するには iTerm2 が起動し API 有効な状態で:

    ITERM2_CLI_INTEGRATION=1 uv run --extra iterm2 pytest tests/integration -q

非破壊: 使い捨ての新規ウィンドウ（cat 実行）を作り、各操作後に close する。既存ペインには触れない。

接続は **1 本を共有**する（module スコープ）。iterm2.Connection に公開 close API は無く、
接続はプロセス終了で解放する設計のため、同一プロセスで張り直さない（実 CLI=1プロセス、
デーモン=接続を生涯保持、という実使用に一致）。
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ITERM2_CLI_INTEGRATION"),
    reason="ITERM2_CLI_INTEGRATION=1 のときのみ実行（実 iTerm2 が必要）",
)


@pytest.fixture(scope="module")
def adapter():
    from iterm2_cli.adapter_real import RealAdapter

    a = RealAdapter.connect()
    try:
        yield a
    finally:
        a.shutdown()


def test_create_send_read_close(adapter):
    sid = adapter.create_tab(command="cat", new_window=True)
    assert sid
    try:
        marker = f"itest-{os.getpid()}-ok"
        adapter.send_text(sid, marker)
        adapter.send_text(sid, "\r")

        hit = False
        for _ in range(20):
            if any(marker in line for line in adapter.get_screen_contents(sid)):
                hit = True
                break
            time.sleep(0.1)
        assert hit, "送信テキストが画面に現れなかった"
    finally:
        adapter.close(sid, force=True)


def test_var_split_focus_list(adapter):
    """RealAdapter の var/split/activate/list を実機で被覆（使い捨てウィンドウで非破壊）。"""
    sid = adapter.create_tab(command="cat", new_window=True)
    split_sid = None
    try:
        # 変数 set/get 往復。
        adapter.set_variable(sid, "user.itest", "v1")
        assert adapter.get_variable(sid, "user.itest") == "v1"

        # 分割 → 新セッションが list に現れる。
        split_sid = adapter.split_pane(sid, vertical=True)
        assert split_sid and split_sid != sid
        ids = {s.session_id for s in adapter.list_sessions()}
        assert {sid, split_sid} <= ids

        # フォーカス移動（例外が出ないこと）。
        adapter.activate(sid)
    finally:
        if split_sid:
            adapter.close(split_sid, force=True)
        adapter.close(sid, force=True)


def test_set_name_roundtrip(adapter):
    """#3: RealAdapter.set_name を実機で被覆（rename 後 list の name が一致）。"""
    sid = adapter.create_tab(command="cat", new_window=True)
    try:
        new_name = f"itest-name-{os.getpid()}"
        adapter.set_name(sid, new_name)
        info = next(s for s in adapter.list_sessions() if s.session_id == sid)
        assert info.name == new_name
    finally:
        adapter.close(sid, force=True)


def test_create_tab_in_existing_window(adapter):
    """#3: create_tab(window_id=...) を実機で被覆（既存窓に新タブ＝同 window_id）。"""
    anchor = adapter.create_tab(command="cat", new_window=True)
    tab_sid = None
    try:
        anchor_info = next(s for s in adapter.list_sessions() if s.session_id == anchor)
        wid = anchor_info.window_id
        assert wid
        tab_sid = adapter.create_tab(command="cat", window_id=wid)
        tab_info = next(s for s in adapter.list_sessions() if s.session_id == tab_sid)
        assert tab_info.window_id == wid
    finally:
        if tab_sid:
            adapter.close(tab_sid, force=True)
        adapter.close(anchor, force=True)


def test_create_tab_from_session_uses_that_window(adapter):
    """#3/#2: create_tab(from_session=...) は from_session を含む窓にタブを作る（D5）。"""
    anchor = adapter.create_tab(command="cat", new_window=True)
    tab_sid = None
    try:
        anchor_info = next(s for s in adapter.list_sessions() if s.session_id == anchor)
        wid = anchor_info.window_id
        tab_sid = adapter.create_tab(command="cat", from_session=anchor)
        tab_info = next(s for s in adapter.list_sessions() if s.session_id == tab_sid)
        assert tab_info.window_id == wid
    finally:
        if tab_sid:
            adapter.close(tab_sid, force=True)
        adapter.close(anchor, force=True)
