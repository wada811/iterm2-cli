"""Controller — 中核操作（design.md §5）。

adapter（port）と resolver を束ね、CLI/socket/ライブラリ利用側から呼べる操作を提供する。
adapter にのみ依存し、iterm2 pip を直接触らない。戻り値は素のデータ（--json 化しやすい）。
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

from .adapter import ITerm2Adapter, SessionInfo
from .detect import (
    DEFAULT_BUSY_MARKERS,
    DEFAULT_NEEDS_INPUT_MARKERS,
    STATE_VAR,
    State,
    classify_screen,
    state_from_var,
    wait_until,
)
from .keys import encode_keys
from .resolver import ResolutionError, SessionResolver


def _markers_from_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """環境変数（改行/カンマ区切り）からマーカー一覧を読む。未設定なら default。"""
    raw = os.environ.get(name)
    if not raw:
        return default
    parts = [m.strip() for m in re.split(r"[\n,]", raw)]
    return tuple(p for p in parts if p) or default


class Controller:
    def __init__(
        self,
        adapter: ITerm2Adapter,
        resolver: SessionResolver | None = None,
        *,
        state_var: str = STATE_VAR,
        busy_markers: tuple[str, ...] | None = None,
        needs_input_markers: tuple[str, ...] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.resolver = resolver or SessionResolver()
        self.state_var = state_var
        # 画面マーカー（フォールバック）は環境変数で上書き可能。
        # ITERM2_CLI_BUSY_MARKERS / ITERM2_CLI_NEEDS_INPUT_MARKERS（改行/カンマ区切り）。
        self.busy_markers = busy_markers or _markers_from_env("ITERM2_CLI_BUSY_MARKERS", DEFAULT_BUSY_MARKERS)
        self.needs_input_markers = needs_input_markers or _markers_from_env(
            "ITERM2_CLI_NEEDS_INPUT_MARKERS", DEFAULT_NEEDS_INPUT_MARKERS
        )
        self._sleep = sleep
        self._clock = clock

    def _resolve(self, target: str | None, session: str | None) -> str:
        return self.resolver.resolve(target, session=session)

    def shutdown(self) -> None:
        """背後の adapter を後始末する（CLI が finally で呼ぶ）。"""
        self.adapter.shutdown()

    # --- 読み取り系 ----------------------------------------------------
    def list(self) -> list[SessionInfo]:
        return self.adapter.list_sessions()

    def read(self, target: str | None = None, *, tail: int | None = None, session: str | None = None) -> list[str]:
        sid = self._resolve(target, session)
        lines = self.adapter.get_screen_contents(sid)
        # 画面下部の空行は通常不要なので落とす（内容が上部にあるとき --tail が空行ばかりになるのを防ぐ）。
        while lines and not lines[-1].strip():
            lines.pop()
        if tail is not None:
            lines = lines[-tail:]
        return lines

    def busy(self, target: str | None = None, *, session: str | None = None) -> State:
        sid = self._resolve(target, session)
        return self._state(sid)

    def _state(self, sid: str) -> State:
        """状態を判定する。user 状態変数を最優先、無ければ画面マーカー（design.md §7）。"""
        value = self.adapter.get_variable(sid, self.state_var)
        from_var = state_from_var(value)
        if from_var is not None:
            return from_var
        return classify_screen(
            self.adapter.get_screen_contents(sid),
            busy_markers=self.busy_markers,
            needs_input_markers=self.needs_input_markers,
        )

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
        until_text: str | None = None,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
        session: str | None = None,
    ) -> State:
        sid = self._resolve(target, session)
        if until_text is not None:
            # 画面に marker が出現するまで待つ。wait_until の predicate を「marker 出現」にするだけ
            # （達したら IDLE、未達は BUSY を返す state_fn として表現し、target=IDLE で待つ）。
            needle = until_text.lower()

            def text_state() -> State:
                haystack = "\n".join(self.adapter.get_screen_contents(sid)).lower()
                return State.IDLE if needle in haystack else State.BUSY

            state_fn = text_state
            target_state = State.IDLE
        else:
            state_fn = lambda: self._state(sid)  # noqa: E731
            target_state = until
        return wait_until(
            state_fn,
            target=target_state,
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

    _UNSET = object()

    def tab(
        self,
        target: str | None = None,
        *,
        profile: str | None = None,
        command: str | None = None,
        new_window: bool = False,
        window_id: str | None = None,
        session: str | None = None,
        from_session: object = _UNSET,
    ) -> str:
        # from_session が明示渡し（デーモンの handler 経路）ならクライアントで解決済み。
        # 未指定（直接利用＝CLI 非デーモン経路）なら、呼び出し元の current ペインを
        # このプロセスで解決し「呼び出し元の窓」にタブを作る（D5: current 解決はクライアント側）。
        if from_session is Controller._UNSET:
            from_session = None
            if not new_window and window_id is None:
                try:
                    from_session = self._resolve(target, session)
                except ResolutionError:
                    # iTerm2 外などで current を特定できない → adapter 既定の current 窓へ。
                    from_session = None
        return self.adapter.create_tab(
            profile=profile,
            command=command,
            new_window=new_window,
            window_id=window_id,
            from_session=from_session,
        )

    def focus(self, target: str | None = None, *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.activate(sid)
        return sid

    def set_name(self, target: str | None, name: str, *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.set_name(sid, name)
        return sid

    def close(self, target: str | None = None, *, force: bool = False, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.close(sid, force=force)
        return sid

    def var_set(self, target: str | None, name: str, value: str, *, session: str | None = None) -> str:
        sid = self._resolve(target, session)
        self.adapter.set_variable(sid, name, value)
        return sid
