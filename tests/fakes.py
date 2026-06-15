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

    def get_screen_contents(self, session_id: str, max_lines: int | None = None) -> list[str]:
        lines = list(self._get(session_id).screen)
        if max_lines is not None:
            return lines[-max_lines:]
        return lines

    def split_pane(self, session_id: str, *, vertical: bool, profile: str | None = None) -> str:
        parent = self._get(session_id)
        new_id = self._new_id("split")
        self.add_session(new_id, name="", tab_id=parent.info.tab_id, window_id=parent.info.window_id)
        return new_id

    def create_tab(
        self, *, profile: str | None = None, command: str | None = None, new_window: bool = False
    ) -> str:
        new_id = self._new_id("win" if new_window else "tab")
        self.add_session(new_id, name="")
        return new_id

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
