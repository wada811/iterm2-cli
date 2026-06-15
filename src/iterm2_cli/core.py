"""Controller — 中核操作（design.md §5）。

adapter（port）と resolver を束ね、CLI/socket/オーケストレータ から呼べる操作を提供する。
adapter にのみ依存し、iterm2 pip を直接触らない。戻り値は素のデータ（--json 化しやすい）。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from .adapter import ITerm2Adapter, SessionInfo
from .detect import State, classify_screen, wait_until
from .keys import encode_keys
from .resolver import SessionResolver


class Controller:
    def __init__(
        self,
        adapter: ITerm2Adapter,
        resolver: SessionResolver | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.resolver = resolver or SessionResolver()
        self._sleep = sleep
        self._clock = clock

    def _resolve(self, target: str | None, session: str | None) -> str:
        return self.resolver.resolve(target, session=session)

    # --- 読み取り系 ----------------------------------------------------
    def list(self) -> list[SessionInfo]:
        return self.adapter.list_sessions()

    def read(self, target: str | None = None, *, tail: int | None = None, session: str | None = None) -> list[str]:
        sid = self._resolve(target, session)
        return self.adapter.get_screen_contents(sid, max_lines=tail)

    def busy(self, target: str | None = None, *, session: str | None = None) -> State:
        sid = self._resolve(target, session)
        return classify_screen(self.adapter.get_screen_contents(sid))

    def var_get(self, target: str | None, name: str, *, session: str | None = None) -> str | None:
        sid = self._resolve(target, session)
        return self.adapter.get_variable(sid, name)

    # --- 送信・キー ----------------------------------------------------
    def send(self, target: str | None, text: str, *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.send_text(sid, text)
        return sid

    def send_key(self, target: str | None, keys: list[str], *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.send_text(sid, encode_keys(keys))
        return sid

    # --- 待機 ----------------------------------------------------------
    def wait(
        self,
        target: str | None = None,
        *,
        until: State = State.IDLE,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
        session: str | None = None,
    ) -> State:
        sid = self._resolve(target, session)
        return wait_until(
            lambda: self.adapter.get_screen_contents(sid),
            target=until,
            timeout=timeout,
            poll_interval=poll_interval,
            sleep=self._sleep,
            clock=self._clock,
        )

    # --- ライフサイクル ------------------------------------------------
    def split(
        self, target: str | None = None, *, vertical: bool = True, profile: str | None = None, session: str | None = None
    ) -> str:
        sid = self._resolve(target, session)
        return self.adapter.split_pane(sid, vertical=vertical, profile=profile)

    def tab(self, *, profile: str | None = None, command: str | None = None, new_window: bool = False) -> str:
        return self.adapter.create_tab(profile=profile, command=command, new_window=new_window)

    def focus(self, target: str | None = None, *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.activate(sid)
        return sid

    def close(self, target: str | None = None, *, force: bool = False, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.close(sid, force=force)
        return sid

    def var_set(self, target: str | None, name: str, value: str, *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.set_variable(sid, name, value)
        return sid
