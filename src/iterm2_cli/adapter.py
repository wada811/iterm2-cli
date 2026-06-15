"""iTerm2 への接続を抽象化する port（design.md §2.2）。

中核ロジックはこの ``ITerm2Adapter`` にのみ依存する。本番は RealAdapter（iterm2 pip）、
テストは FakeAdapter（インメモリ）を差し込む。port は **同期**インターフェースにし、
async/websocket/認証といった IO は RealAdapter の内部にだけ閉じ込める（humble object）。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionInfo:
    """1 セッション（ペイン）の最小情報。"""

    session_id: str
    name: str
    rows: int = 0
    cols: int = 0
    tab_id: str | None = None
    window_id: str | None = None
    is_active: bool = False


class ITerm2Adapter(abc.ABC):
    """iTerm2 操作の最小 port。すべて同期。session は session_id(UUID) で指す。"""

    @abc.abstractmethod
    def list_sessions(self) -> list[SessionInfo]:
        """全ウィンドウ/タブ/セッションを平坦に列挙する。"""

    @abc.abstractmethod
    def send_text(self, session_id: str, text: str) -> None:
        """ユーザーが打鍵したかのようにテキスト（制御文字含む）を送る。"""

    @abc.abstractmethod
    def get_screen_contents(self, session_id: str, max_lines: int | None = None) -> list[str]:
        """現在の画面行を上から順に返す。max_lines 指定時は末尾 N 行。"""

    @abc.abstractmethod
    def split_pane(self, session_id: str, *, vertical: bool, profile: str | None = None) -> str:
        """対象を分割し、新しいセッションの session_id を返す。"""

    @abc.abstractmethod
    def create_tab(
        self, *, profile: str | None = None, command: str | None = None, new_window: bool = False
    ) -> str:
        """新しいタブ（または new_window でウィンドウ）を作り、新 session_id を返す。"""

    @abc.abstractmethod
    def activate(self, session_id: str) -> None:
        """対象セッションにフォーカスを移す。"""

    @abc.abstractmethod
    def close(self, session_id: str, *, force: bool = False) -> None:
        """対象セッション（ペイン/タブ）を閉じる。"""

    @abc.abstractmethod
    def get_variable(self, session_id: str, name: str) -> str | None:
        """セッション変数を取得する（無ければ None）。"""

    @abc.abstractmethod
    def set_variable(self, session_id: str, name: str, value: str) -> None:
        """セッション変数（user.* 等）を設定する。"""

    def shutdown(self) -> None:
        """接続等の後始末（既定は no-op）。RealAdapter が websocket を閉じる。"""
        return None


class SessionNotFound(Exception):
    """指定 session_id のセッションが存在しないとき（NFR7: silent fail しない）。"""
