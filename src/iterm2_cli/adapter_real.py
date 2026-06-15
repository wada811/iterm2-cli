"""RealAdapter — iterm2 pip で実 iTerm2 を操作する port 実装（design.md §2.2）。

async/websocket/認証はすべて本モジュールの内部に閉じ込める（humble object）。
バックグラウンドスレッドで asyncio ループを 1 本持ち続け、接続をそのループ上に保持する。
同期メソッドは run_coroutine_threadsafe でそのループにコルーチンを投げて結果を待つ。

iterm2 パッケージは optional 依存。connect() 時に遅延 import する。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .adapter import ITerm2Adapter, SessionInfo, SessionNotFound

_DEFAULT_TIMEOUT = 15.0


class RealAdapter(ITerm2Adapter):
    def __init__(self, connection: Any, app: Any, loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
        self._connection = connection
        self._app = app
        self._loop = loop
        self._thread = thread

    # --- 接続ライフサイクル -------------------------------------------
    @classmethod
    def connect(cls, *, timeout: float = _DEFAULT_TIMEOUT) -> "RealAdapter":
        try:
            import iterm2  # noqa: F401
        except ImportError as e:  # pragma: no cover - 環境依存
            raise RuntimeError(
                "iterm2 パッケージが必要です（uv: --with iterm2 / 依存 extra 'iterm2'）"
            ) from e

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, name="iterm2-cli-loop", daemon=True)
        thread.start()

        async def _setup():
            import iterm2

            connection = await iterm2.Connection.async_create()
            app = await iterm2.async_get_app(connection)
            return connection, app

        fut = asyncio.run_coroutine_threadsafe(_setup(), loop)
        connection, app = fut.result(timeout)
        return cls(connection, app, loop, thread)

    def shutdown(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _call(self, coro, *, timeout: float = _DEFAULT_TIMEOUT):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # --- 内部ヘルパ ----------------------------------------------------
    def _session_or_raise(self, session_id: str):
        s = self._app.get_session_by_id(session_id)
        if s is None:
            raise SessionNotFound(session_id)
        return s

    def _current_session_id(self) -> str | None:
        win = self._app.current_terminal_window
        if win and win.current_tab and win.current_tab.current_session:
            return win.current_tab.current_session.session_id
        return None

    # --- port 実装 ------------------------------------------------------
    def list_sessions(self) -> list[SessionInfo]:
        async def _run():
            await self._app.async_refresh()
            current = self._current_session_id()
            out: list[SessionInfo] = []
            for window in self._app.terminal_windows:
                for tab in window.tabs:
                    for s in tab.sessions:
                        name = await s.async_get_variable("session.name")
                        size = s.grid_size
                        out.append(
                            SessionInfo(
                                session_id=s.session_id,
                                name=name or "",
                                rows=getattr(size, "height", 0) or 0,
                                cols=getattr(size, "width", 0) or 0,
                                tab_id=tab.tab_id,
                                window_id=window.window_id,
                                is_active=(s.session_id == current),
                            )
                        )
            return out

        return self._call(_run())

    def send_text(self, session_id: str, text: str) -> None:
        self._call(self._session_or_raise(session_id).async_send_text(text))

    def get_screen_contents(self, session_id: str, max_lines: int | None = None) -> list[str]:
        async def _run():
            contents = await self._session_or_raise(session_id).async_get_screen_contents()
            lines = [contents.line(i).string for i in range(contents.number_of_lines)]
            return lines[-max_lines:] if max_lines is not None else lines

        return self._call(_run())

    def split_pane(self, session_id: str, *, vertical: bool, profile: str | None = None) -> str:
        async def _run():
            new = await self._session_or_raise(session_id).async_split_pane(
                vertical=vertical, profile=profile
            )
            return new.session_id

        return self._call(_run())

    def create_tab(
        self, *, profile: str | None = None, command: str | None = None, new_window: bool = False
    ) -> str:
        async def _run():
            import iterm2

            if new_window or not self._app.terminal_windows:
                window = await iterm2.Window.async_create(
                    self._connection, profile=profile, command=command
                )
                return window.current_tab.current_session.session_id
            window = self._app.current_terminal_window or self._app.terminal_windows[0]
            tab = await window.async_create_tab(profile=profile, command=command)
            return tab.current_session.session_id

        return self._call(_run())

    def activate(self, session_id: str) -> None:
        self._call(self._session_or_raise(session_id).async_activate())

    def close(self, session_id: str, *, force: bool = False) -> None:
        self._call(self._session_or_raise(session_id).async_close(force=force))

    def get_variable(self, session_id: str, name: str) -> str | None:
        return self._call(self._session_or_raise(session_id).async_get_variable(name))

    def set_variable(self, session_id: str, name: str, value: str) -> None:
        self._call(self._session_or_raise(session_id).async_set_variable(name, value))
