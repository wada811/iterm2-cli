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


def test_busy_classifies():
    fa, c = make()
    fa._get(A).screen = ["esc to interrupt"]
    assert c.busy(A) == State.BUSY


def test_split_returns_new_id():
    fa, c = make()
    new_id = c.split(A, vertical=True)
    assert new_id != A
    assert new_id in [s.session_id for s in c.list()]


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
