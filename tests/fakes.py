"""FakeAdapter — iTerm2 無しで中核ロジックをテストするためのインメモリ実装（design.md §2.2）。

実 iTerm2 の代わりにセッション木を持ち、送信テキスト・画面内容・変数・分割/作成/クローズを
模擬する。決定的に動かすため id は連番で振る（乱数を使わない）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from iterm2_cli.adapter import ITerm2Adapter, SessionInfo, SessionNotFound


@dataclass
class FakeSession:
    info: SessionInfo
    screen: list[str] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)
    sent: list[str] = field(default_factory=list)
    closed: bool = False


class FakeAdapter(ITerm2Adapter):
    def __init__(self, sessions: list[FakeSession] | None = None) -> None:
        self._sessions: dict[str, FakeSession] = {}
        self._order: list[str] = []
        self._counter = 0
        # split_pane の引数記録（before/vertical の伝播をテストで検証する）。
        self.splits: list[dict] = []
        for s in sessions or []:
            self._add(s)

    # --- テスト用ヘルパ -------------------------------------------------
    def _add(self, s: FakeSession) -> None:
        self._sessions[s.info.session_id] = s
        self._order.append(s.info.session_id)

    def add_session(
        self, session_id: str, name: str = "", *, screen: list[str] | None = None, **kw
    ) -> FakeSession:
        s = FakeSession(
            info=SessionInfo(session_id=session_id, name=name, **kw),
            screen=list(screen or []),
        )
        self._add(s)
        return s

    def _get(self, session_id: str) -> FakeSession:
        s = self._sessions.get(session_id)
        if s is None or s.closed:
            raise SessionNotFound(session_id)
        return s

    def _new_id(self, kind: str) -> str:
        self._counter += 1
        return f"FAKE-{kind}-{self._counter}"

    # --- port 実装 ------------------------------------------------------
    def list_sessions(self) -> list[SessionInfo]:
        return [self._sessions[i].info for i in self._order if not self._sessions[i].closed]

    def send_text(self, session_id: str, text: str) -> None:
        self._get(session_id).sent.append(text)

    def get_screen_contents(self, session_id: str) -> list[str]:
        return list(self._get(session_id).screen)

    def split_pane(
        self, session_id: str, *, vertical: bool, before: bool = False, profile: str | None = None
    ) -> str:
        parent = self._get(session_id)
        self.splits.append({"session_id": session_id, "vertical": vertical, "before": before, "profile": profile})
        new_id = self._new_id("split")
        self.add_session(new_id, name="", tab_id=parent.info.tab_id, window_id=parent.info.window_id)
        return new_id

    def create_tab(
        self,
        *,
        profile: str | None = None,
        command: str | None = None,
        new_window: bool = False,
        window_id: str | None = None,
        from_session: str | None = None,
    ) -> str:
        if window_id is not None:
            # 指定窓が存在するか（その窓に属する開いたセッションがあるか）を確認。
            if not any(
                s.info.window_id == window_id for s in self._sessions.values() if not s.closed
            ):
                raise SessionNotFound(window_id)
            new_id = self._new_id("tab")
            self.add_session(new_id, name="", window_id=window_id)
            return new_id
        if new_window:
            new_id = self._new_id("win")
            self.add_session(new_id, name="")
            return new_id
        if from_session is not None:
            # 呼び出し元のペインを含む窓にタブを作る（D5）。
            src = self._sessions.get(from_session)
            if src is None or src.closed:
                raise SessionNotFound(from_session)
            new_id = self._new_id("tab")
            self.add_session(new_id, name="", window_id=src.info.window_id)
            return new_id
        new_id = self._new_id("tab")
        self.add_session(new_id, name="")
        return new_id

    def set_name(self, session_id: str, name: str) -> None:
        s = self._get(session_id)
        s.info = _with(s.info, name=name)

    def activate(self, session_id: str) -> None:
        self._get(session_id)  # 存在チェック
        # SessionInfo は frozen なので is_active を差し替えて再設定する。
        for sid in list(self._sessions):
            s = self._sessions[sid]
            s.info = _with(s.info, is_active=(sid == session_id))

    def close(self, session_id: str, *, force: bool = False) -> None:
        self._get(session_id).closed = True

    def get_variable(self, session_id: str, name: str) -> str | None:
        return self._get(session_id).variables.get(name)

    def set_variable(self, session_id: str, name: str, value: str) -> None:
        self._get(session_id).variables[name] = value


def _with(info: SessionInfo, **changes) -> SessionInfo:
    from dataclasses import replace

    return replace(info, **changes)
