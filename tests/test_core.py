from __future__ import annotations

import pytest

from iterm2_cli.core import Controller
from iterm2_cli.detect import State, WaitTimeout
from iterm2_cli.resolver import SessionResolver
from tests.fakes import FakeAdapter

A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"


def make(labels=None, env=None, **kw):
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    resolver = SessionResolver(labels=labels or {}, env=env if env is not None else {})
    return fa, Controller(fa, resolver, **kw)


def test_list():
    fa, c = make()
    assert [s.session_id for s in c.list()] == [A]


def test_send_resolves_and_records():
    fa, c = make()
    c.send(A, "hello")
    assert fa._get(A).sent == ["hello"]


def test_send_via_label():
    fa, c = make(labels={"a": A})
    c.send("a", "hi")
    assert fa._get(A).sent == ["hi"]


def test_send_current_from_env():
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    c = Controller(fa, SessionResolver(env={"ITERM_SESSION_ID": f"x:{A}"}))
    c.send(None, "yo")
    assert fa._get(A).sent == ["yo"]


def test_send_key_encodes():
    fa, c = make()
    c.send_key(A, ["ctrl-c", "enter"])
    assert fa._get(A).sent == ["\x03\r"]


def test_read_tail():
    fa, c = make()
    fa._get(A).screen = ["l1", "l2", "l3"]
    assert c.read(A, tail=2) == ["l2", "l3"]


def test_read_trims_trailing_blank_lines():
    fa, c = make()
    # 内容は上部、下部は空行。trim 後に tail を当てるので内容が残る。
    fa._get(A).screen = ["hello", "world", "", "   ", ""]
    assert c.read(A) == ["hello", "world"]
    assert c.read(A, tail=1) == ["world"]


def test_busy_markers_configurable_via_env(monkeypatch):
    monkeypatch.setenv("ITERM2_CLI_BUSY_MARKERS", "Running tests,compiling")
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    c = Controller(fa, SessionResolver())  # env を読む
    fa._get(A).screen = ["...compiling..."]
    assert c.busy(A) == State.BUSY
    # 既定マーカー（esc to interrupt）は上書きされたので busy 扱いにならない
    fa._get(A).screen = ["esc to interrupt"]
    assert c.busy(A) == State.IDLE


def test_busy_markers_explicit_arg():
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    c = Controller(fa, SessionResolver(), busy_markers=("WORKING",))
    fa._get(A).screen = ["WORKING hard"]
    assert c.busy(A) == State.BUSY


def test_busy_classifies():
    fa, c = make()
    fa._get(A).screen = ["esc to interrupt"]
    assert c.busy(A) == State.BUSY


def test_busy_prefers_state_variable_over_screen():
    fa, c = make()
    # 画面は idle だが状態変数は running → 変数が優先される。
    fa._get(A).screen = ["$ ready"]
    fa._get(A).variables["user.itermcli_state"] = "running"
    assert c.busy(A) == State.BUSY


def test_busy_falls_back_to_screen_when_var_unknown():
    fa, c = make()
    fa._get(A).screen = ["esc to interrupt"]
    fa._get(A).variables["user.itermcli_state"] = "garbage"
    assert c.busy(A) == State.BUSY


def test_split_returns_new_id():
    fa, c = make()
    new_id = c.split(A, vertical=True)
    assert new_id != A
    assert new_id in [s.session_id for s in c.list()]
    assert fa.splits[-1]["before"] is False  # 既定は後ろ


def test_split_before_propagates_to_adapter():
    fa, c = make()
    c.split(A, vertical=True, before=True)
    assert fa.splits[-1]["before"] is True


def test_focus_and_close():
    fa, c = make()
    c.focus(A)
    assert fa._get(A).info.is_active
    c.close(A)
    assert c.list() == []


def test_var_roundtrip():
    fa, c = make()
    c.var_set(A, "user.k", "v")
    assert c.var_get(A, "user.k") == "v"


def test_wait_until_idle_with_injected_clock():
    fa, c0 = make()
    fa._get(A).screen = ["$ done"]
    t = {"v": 0.0}
    c = Controller(fa, SessionResolver(), sleep=lambda dt: t.__setitem__("v", t["v"] + dt), clock=lambda: t["v"])
    assert c.wait(session=A, until=State.IDLE, timeout=5, poll_interval=1) == State.IDLE


def test_wait_times_out_when_busy():
    fa, _ = make()
    fa._get(A).screen = ["esc to interrupt"]
    t = {"v": 0.0}
    c = Controller(fa, SessionResolver(), sleep=lambda dt: t.__setitem__("v", t["v"] + dt), clock=lambda: t["v"])
    with pytest.raises(WaitTimeout):
        c.wait(session=A, until=State.IDLE, timeout=3, poll_interval=1)


def test_set_name_sets_display_name():
    fa, c = make()
    c.set_name(A, "🟢 worker")
    assert fa._get(A).info.name == "🟢 worker"


def test_set_name_via_label():
    fa, c = make(labels={"a": A})
    c.set_name("a", "renamed")
    assert fa._get(A).info.name == "renamed"


def test_wait_until_text_returns_when_marker_present():
    fa, _ = make()
    fa._get(A).screen = ["connecting...", "Remote Control active"]
    t = {"v": 0.0}
    c = Controller(fa, SessionResolver(), sleep=lambda dt: t.__setitem__("v", t["v"] + dt), clock=lambda: t["v"])
    assert c.wait(session=A, until_text="Remote Control active", timeout=5, poll_interval=1) == State.IDLE


def test_wait_until_text_is_case_insensitive():
    fa, _ = make()
    fa._get(A).screen = ["REMOTE CONTROL ACTIVE"]
    t = {"v": 0.0}
    c = Controller(fa, SessionResolver(), sleep=lambda dt: t.__setitem__("v", t["v"] + dt), clock=lambda: t["v"])
    assert c.wait(session=A, until_text="remote control active", timeout=5, poll_interval=1) == State.IDLE


def test_wait_until_text_times_out_when_absent():
    fa, _ = make()
    fa._get(A).screen = ["nothing relevant here"]
    t = {"v": 0.0}
    c = Controller(fa, SessionResolver(), sleep=lambda dt: t.__setitem__("v", t["v"] + dt), clock=lambda: t["v"])
    with pytest.raises(WaitTimeout):
        c.wait(session=A, until_text="never appears", timeout=3, poll_interval=1)


def test_tab_in_window_places_session_in_window():
    fa, c = make()
    fa.add_session("WIN-SESS", "anchor", window_id="w-1")
    new_id = c.tab(window_id="w-1")
    new_info = next(s for s in c.list() if s.session_id == new_id)
    assert new_info.window_id == "w-1"


def test_tab_in_unknown_window_raises():
    from iterm2_cli.adapter import SessionNotFound

    fa, c = make()
    with pytest.raises(SessionNotFound):
        c.tab(window_id="w-nonexistent")


def test_tab_defaults_to_caller_window():
    # #2: 既定 tab は呼び出し元（current = $ITERM_SESSION_ID）の窓にタブを作る（D5）。
    fa = FakeAdapter()
    fa.add_session(A, "pane-a", window_id="w-caller")
    c = Controller(fa, SessionResolver(env={"ITERM_SESSION_ID": f"x:{A}"}))
    new_id = c.tab()
    new_info = next(s for s in c.list() if s.session_id == new_id)
    assert new_info.window_id == "w-caller"


def test_tab_falls_back_when_current_unresolvable():
    # current を特定できない（target も session も env も無い）場合は adapter 既定に委ねる
    # （ResolutionError で落とさない）。
    fa = FakeAdapter()
    fa.add_session(A, "pane-a", window_id="w-1")
    c = Controller(fa, SessionResolver(env={}))
    new_id = c.tab()  # 例外を出さずに新タブを作る
    assert new_id in [s.session_id for s in c.list()]
