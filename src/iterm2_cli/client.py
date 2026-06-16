"""DaemonClient — デーモンへの軽量クライアント（design.md §2.1 / §3）。

Controller と同じメソッド表面を持ち、CLI から透過的に差し替えられる。
**target 解決はクライアント側**で行い、デーモンには具体的 session_id を渡す
（current = クライアントのペインを正しく指すため）。1 リクエスト = 1 接続。
"""

from __future__ import annotations

import socket
from pathlib import Path

from .adapter import SessionInfo
from .daemon import read_line
from .detect import State
from .protocol import decode, encode, make_request
from .resolver import ResolutionError, SessionResolver


class DaemonError(Exception):
    """デーモンがエラーレスポンスを返したとき。"""


class DaemonClient:
    def __init__(self, socket_path: Path | str, resolver: SessionResolver | None = None) -> None:
        self._path = str(socket_path)
        self._resolver = resolver or SessionResolver()
        self._counter = 0

    # --- 低レベル ------------------------------------------------------
    def _rpc(self, method: str, params: dict):
        self._counter += 1
        req = make_request(str(self._counter), method, params)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(self._path)
                s.sendall(encode(req))
                line = read_line(s)
        except OSError as e:
            # デーモンが check 後に停止した等。整ったエラーにして CLI で exit 2 に。
            raise DaemonError(f"connection_failed: デーモンに接続できません ({e})") from e
        if not line.strip():
            raise DaemonError("no_response: デーモンが応答せず接続を閉じました")
        resp = decode(line)
        if not resp.get("ok"):
            err = resp.get("error", {})
            raise DaemonError(f"{err.get('code')}: {err.get('message')}")
        return resp.get("result")

    def _resolve(self, target: str | None, session: str | None) -> str:
        return self._resolver.resolve(target, session=session)

    # --- Controller と同じ表面 ----------------------------------------
    def list(self) -> list[SessionInfo]:
        return [SessionInfo(**d) for d in self._rpc("session.list", {})["sessions"]]

    def send(self, target: str | None, text: str, *, session: str | None = None) -> None:
        self._rpc("session.send_text", {"session": self._resolve(target, session), "text": text})

    def send_key(self, target: str | None, keys: list[str], *, session: str | None = None) -> None:
        self._rpc("session.send_key", {"session": self._resolve(target, session), "keys": list(keys)})

    def read(self, target: str | None = None, *, tail: int | None = None, session: str | None = None) -> list[str]:
        return self._rpc("session.read", {"session": self._resolve(target, session), "tail": tail})["lines"]

    def busy(self, target: str | None = None, *, session: str | None = None) -> State:
        return State(self._rpc("session.busy", {"session": self._resolve(target, session)})["state"])

    def wait(
        self,
        target: str | None = None,
        *,
        until: State = State.IDLE,
        until_text: str | None = None,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
        session: str | None = None,
    ) -> State:
        result = self._rpc(
            "session.wait",
            {
                "session": self._resolve(target, session),
                "until": until.value,
                "until_text": until_text,
                "timeout": timeout,
                "poll_interval": poll_interval,
            },
        )
        return State(result["state"])

    def split(
        self, target: str | None = None, *, vertical: bool = True, profile: str | None = None, session: str | None = None
    ) -> str:
        return self._rpc(
            "pane.split",
            {"session": self._resolve(target, session), "vertical": vertical, "profile": profile},
        )["session_id"]

    def tab(
        self,
        target: str | None = None,
        *,
        profile: str | None = None,
        command: str | None = None,
        new_window: bool = False,
        window_id: str | None = None,
        session: str | None = None,
    ) -> str:
        # 既定（新規窓でも指定窓でもない）は「呼び出し元の窓」に作る。current の解決は
        # クライアント側で行い（D5）、デーモンには具体的 session_id を from_session で渡す。
        from_session = None
        if not new_window and window_id is None:
            try:
                from_session = self._resolve(target, session)
            except ResolutionError:
                from_session = None  # current を特定できない → デーモン側の current 窓へ
        return self._rpc(
            "window.new_tab",
            {
                "profile": profile,
                "command": command,
                "new_window": new_window,
                "window_id": window_id,
                "from_session": from_session,
            },
        )["session_id"]

    def focus(self, target: str | None = None, *, session: str | None = None) -> None:
        self._rpc("session.focus", {"session": self._resolve(target, session)})

    def set_name(self, target: str | None, name: str, *, session: str | None = None) -> str:
        # session_id を出力契約（set-name --json）に載せるため、クライアントで解決した
        # 具体 id を返す（デーモンは set のみ・往復は増やさない）。
        sid = self._resolve(target, session)
        self._rpc("session.set_name", {"session": sid, "name": name})
        return sid

    def close(self, target: str | None = None, *, force: bool = False, session: str | None = None) -> None:
        self._rpc("session.close", {"session": self._resolve(target, session), "force": force})

    def var_get(self, target: str | None, name: str, *, session: str | None = None) -> str | None:
        return self._rpc("session.get_var", {"session": self._resolve(target, session), "name": name})["value"]

    def var_set(self, target: str | None, name: str, value: str, *, session: str | None = None) -> None:
        self._rpc("session.set_var", {"session": self._resolve(target, session), "name": name, "value": value})

    def shutdown(self) -> None:
        """1 リクエスト = 1 接続なので保持リソースは無い。"""
        return None

    def stop_daemon(self) -> None:
        """デーモンを停止させる（system.stop）。"""
        try:
            self._rpc("system.stop", {})
        except (OSError, DaemonError):
            pass
