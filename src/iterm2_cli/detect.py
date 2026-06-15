"""busy/完了検知（design.md §7）。

検知の優先順は hook イベント → OSC 9/99/777 → 画面マーカー（フォールバック）。
本モジュールはフォールバックの**画面マーカー分類**と、汎用の**待機ループ**を提供する。
hook/OSC ソースは外部状態に依存するため、状態を与える側（Controller / オーケストレータ）が差し込む。

純ロジック（clock/sleep を注入してテスト可能）。
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class State(str, Enum):
    BUSY = "busy"
    NEEDS_INPUT = "needs-input"
    IDLE = "idle"
    UNKNOWN = "unknown"


# Claude Code TUI のフォールバック・マーカー（小文字で照合）。
DEFAULT_BUSY_MARKERS: tuple[str, ...] = ("esc to interrupt",)
DEFAULT_NEEDS_INPUT_MARKERS: tuple[str, ...] = (
    "do you want to proceed",
    "❯ 1.",
    "(y/n)",
)


def classify_screen(
    lines: list[str],
    *,
    busy_markers: tuple[str, ...] = DEFAULT_BUSY_MARKERS,
    needs_input_markers: tuple[str, ...] = DEFAULT_NEEDS_INPUT_MARKERS,
) -> State:
    """画面行から状態を推定する。busy > needs-input > idle の優先順。

    空（読めない）なら UNKNOWN。
    """
    if not lines:
        return State.UNKNOWN
    haystack = "\n".join(lines).lower()
    if any(m.lower() in haystack for m in busy_markers):
        return State.BUSY
    if any(m.lower() in haystack for m in needs_input_markers):
        return State.NEEDS_INPUT
    return State.IDLE


class WaitTimeout(Exception):
    """待機が目標状態に達せずタイムアウトした（NFR7: silent fail しない）。"""


def wait_until(
    read_screen: Callable[[], list[str]],
    *,
    target: State = State.IDLE,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    classify: Callable[[list[str]], State] = classify_screen,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> State:
    """target 状態になるまで read_screen をポーリングする。

    達したらその State を返す。timeout を超えたら WaitTimeout。
    sleep/clock を注入することでテストでは即座に進められる。
    """
    deadline = clock() + timeout
    while True:
        state = classify(read_screen())
        if state == target:
            return state
        if clock() >= deadline:
            raise WaitTimeout(f"{target.value} に達せずタイムアウト（最終状態={state.value}）")
        sleep(poll_interval)
