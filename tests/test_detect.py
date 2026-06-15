from __future__ import annotations

import pytest

from iterm2_cli.detect import State, WaitTimeout, classify_screen, wait_until


def test_empty_screen_unknown():
    assert classify_screen([]) == State.UNKNOWN


def test_busy_marker():
    assert classify_screen(["working...", "esc to interrupt"]) == State.BUSY


def test_busy_case_insensitive():
    assert classify_screen(["ESC to Interrupt"]) == State.BUSY


def test_needs_input_marker():
    assert classify_screen(["Do you want to proceed?", "❯ 1. Yes"]) == State.NEEDS_INPUT


def test_idle_when_no_marker():
    assert classify_screen(["$ ", "ready"]) == State.IDLE


def test_busy_takes_precedence_over_needs_input():
    assert classify_screen(["(y/n)", "esc to interrupt"]) == State.BUSY


def test_custom_markers():
    assert classify_screen(["Running tests"], busy_markers=("running",)) == State.BUSY


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_wait_reaches_target_after_polls():
    # 3 回目の読み取りで idle になる画面を返す。
    screens = [["esc to interrupt"], ["esc to interrupt"], ["$ done"]]
    calls = {"n": 0}

    def read():
        i = min(calls["n"], len(screens) - 1)
        calls["n"] += 1
        return screens[i]

    clock = _Clock()

    def sleep(dt):
        clock.t += dt

    state = wait_until(read, target=State.IDLE, timeout=30, poll_interval=0.5, sleep=sleep, clock=clock)
    assert state == State.IDLE
    assert calls["n"] == 3


def test_wait_times_out():
    clock = _Clock()

    def sleep(dt):
        clock.t += dt

    with pytest.raises(WaitTimeout):
        wait_until(
            lambda: ["esc to interrupt"],
            target=State.IDLE,
            timeout=2,
            poll_interval=1,
            sleep=sleep,
            clock=clock,
        )
