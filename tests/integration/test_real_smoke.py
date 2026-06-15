"""実 iTerm2 への結合スモーク（オプトイン）。

通常の `uv run pytest` ではスキップする。実行するには iTerm2 が起動し API 有効な状態で:

    ITERM2_CLI_INTEGRATION=1 uv run --extra iterm2 pytest tests/integration -q

非破壊: 使い捨ての新規ウィンドウ（cat 実行）を作り、送信→エコー読取→close する。
既存ペインには触れない。
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ITERM2_CLI_INTEGRATION"),
    reason="ITERM2_CLI_INTEGRATION=1 のときのみ実行（実 iTerm2 が必要）",
)


def test_create_send_read_close():
    from iterm2_cli.adapter_real import RealAdapter

    adapter = RealAdapter.connect()
    sid = None
    try:
        sid = adapter.create_tab(command="cat", new_window=True)
        assert sid

        marker = f"itest-{os.getpid()}-ok"
        adapter.send_text(sid, marker)
        adapter.send_text(sid, "\r")

        # cat のエコーを待つ（数回リトライ）。
        hit = False
        for _ in range(20):
            lines = adapter.get_screen_contents(sid)
            if any(marker in line for line in lines):
                hit = True
                break
            time.sleep(0.1)
        assert hit, "送信テキストが画面に現れなかった"
    finally:
        if sid:
            adapter.close(sid, force=True)
        adapter.shutdown()
