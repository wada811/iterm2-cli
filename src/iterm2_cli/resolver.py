"""<target> 解決層。

CLI/socket が受け取った `<target>` を iTerm2 の session_id（UUID）へ解決する。
解決順（requirements.md FR11）: 明示 --session <id> → ラベル → $ITERM_SESSION_ID(current)。

外部 I/O を持たない純ロジック。ユニットテストで赤緑が回る（design.md §2.2）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

# iTerm2 の session_id は 8-4-4-4-12 の UUID 形式。
_UUID_RE = re.compile(
    r"\A[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z"
)


class ResolutionError(Exception):
    """`<target>` を session_id へ解決できないときに送出する（silent fail しない / NFR7）。"""


def strip_iterm_session_prefix(iterm_session_id: str) -> str:
    """環境変数 ITERM_SESSION_ID の値から session_id(UUID) を取り出す。

    形式は ``w1t3p0:3970511E-...`` のように ``<window/tab/pane>:`<UUID>`` 。
    コロン以降が iTerm2 Python API の session_id に一致する。
    """
    _, sep, tail = iterm_session_id.partition(":")
    return tail if sep else iterm_session_id


class SessionResolver:
    """`<target>` → session_id の解決器。

    labels: ラベル名 → session_id の最小マッピング（design.md §4 / 最小状態主義）。
    env: 環境変数（既定で os.environ）。current 解決に ITERM_SESSION_ID を見る。
    """

    def __init__(
        self,
        labels: Mapping[str, str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._labels: dict[str, str] = dict(labels or {})
        self._env: Mapping[str, str] = env if env is not None else os.environ

    def resolve(self, target: str | None = None, *, session: str | None = None) -> str:
        # 1. 明示 --session <id> が最優先。
        if session:
            return session
        # 2. 位置引数 target: 既知ラベル → UUID そのもの の順。
        #    ラベルは保存時に normalize_label で正規化されるため、照合も正規化して合わせる
        #    （例: "my project" も "my-project" として登録済みのラベルに解決できる）。
        if target:
            from .labels import normalize_label

            normalized = normalize_label(target)
            if normalized in self._labels:
                return self._labels[normalized]
            if _UUID_RE.match(target):
                return target
            raise ResolutionError(
                f"unknown target: {target!r} (既知のラベルでも session_id でもない)"
            )
        # 3. current = $ITERM_SESSION_ID。
        current = self._env.get("ITERM_SESSION_ID")
        if current:
            return strip_iterm_session_prefix(current)
        raise ResolutionError(
            "target 未指定かつ ITERM_SESSION_ID 未設定（iTerm2 の外で実行?）"
        )
