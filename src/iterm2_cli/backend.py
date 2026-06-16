"""Backend — 操作のバックエンド共通インターフェース（design.md §2）。

Controller（都度接続）と DaemonClient（socket 経由）はこの同一表面を実装し、
CLI から透過的に差し替えられる。runtime_checkable なので、両者が表面を満たすことを
テストで担保できる（操作追加時のドリフト検出）。公開 API としても export する。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .adapter import SessionInfo
from .detect import State


@runtime_checkable
class Backend(Protocol):
    def list(self) -> list[SessionInfo]: ...

    def send(self, target: str | None, text: str, *, session: str | None = None): ...

    def send_key(self, target: str | None, keys: list[str], *, session: str | None = None): ...

    def read(self, target: str | None = None, *, tail: int | None = None, session: str | None = None) -> list[str]: ...

    def busy(self, target: str | None = None, *, session: str | None = None) -> State: ...

    def wait(
        self,
        target: str | None = None,
        *,
        until: State = State.IDLE,
        until_text: str | None = None,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
        session: str | None = None,
    ) -> State: ...

    def split(
        self, target: str | None = None, *, vertical: bool = True, profile: str | None = None, session: str | None = None
    ) -> str: ...

    def tab(
        self,
        target: str | None = None,
        *,
        profile: str | None = None,
        command: str | None = None,
        new_window: bool = False,
        window_id: str | None = None,
        session: str | None = None,
    ) -> str: ...

    def focus(self, target: str | None = None, *, session: str | None = None): ...

    def set_name(self, target: str | None, name: str, *, session: str | None = None) -> str: ...

    def close(self, target: str | None = None, *, force: bool = False, session: str | None = None): ...

    def var_get(self, target: str | None, name: str, *, session: str | None = None) -> str | None: ...

    def var_set(self, target: str | None, name: str, value: str, *, session: str | None = None): ...

    def shutdown(self) -> None: ...
