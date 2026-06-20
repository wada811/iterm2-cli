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
    def get_screen_contents(self, session_id: str) -> list[str]:
        """現在の画面行を上から順に返す（全行）。

        末尾空行の trim・``--tail`` は Controller 側で行う（trim を tail より先に
        適用する仕様のため、取得は常に全行）。
        """

    @abc.abstractmethod
    def split_pane(
        self, session_id: str, *, vertical: bool, before: bool = False, profile: str | None = None
    ) -> str:
        """対象を分割し、新しいセッションの session_id を返す。

        before=True で新ペインを source の前（垂直分割なら左・水平分割なら上）に作る
        （iterm2 async_split_pane(before=) に対応）。既定 False は従来どおり後ろ（右/下）。
        """

    @abc.abstractmethod
    def create_tab(
        self,
        *,
        profile: str | None = None,
        command: str | None = None,
        new_window: bool = False,
        window_id: str | None = None,
        from_session: str | None = None,
    ) -> str:
        """新しいタブ（または new_window でウィンドウ）を作り、新 session_id を返す。

        - window_id 指定時はその既存ウィンドウ内にタブを作る（無ければ SessionNotFound）。
        - from_session 指定時はその session を含むウィンドウにタブを作る（無ければ
          SessionNotFound）。呼び出し元（クライアント）の current 窓を指すための引数で、
          デーモン視点の current 窓に作ってしまう D5 違反を避ける。
        - いずれも未指定なら adapter 視点の current 窓（フォールバック）。
        """

    @abc.abstractmethod
    def set_name(self, session_id: str, name: str) -> None:
        """セッション（ペイン）の表示名を設定する。"""

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
