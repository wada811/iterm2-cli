from __future__ import annotations

import pytest

from iterm2_cli.adapter import SessionNotFound
from tests.fakes import FakeAdapter

A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"


def test_list_sessions_returns_added():
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    ids = [s.session_id for s in fa.list_sessions()]
    assert ids == [A]


def test_send_text_recorded():
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    fa.send_text(A, "hello")
    assert fa._get(A).sent == ["hello"]


def test_get_screen_contents():
    fa = FakeAdapter()
    fa.add_session(A, screen=["l1", "l2", "l3"])
    assert fa.get_screen_contents(A) == ["l1", "l2", "l3"]


def test_split_creates_new_session():
    fa = FakeAdapter()
    fa.add_session(A)
    new_id = fa.split_pane(A, vertical=True)
    assert new_id != A
    assert new_id in [s.session_id for s in fa.list_sessions()]


def test_create_tab_returns_new_session():
    fa = FakeAdapter()
    new_id = fa.create_tab()
    assert new_id in [s.session_id for s in fa.list_sessions()]


def test_close_removes_from_list():
    fa = FakeAdapter()
    fa.add_session(A)
    fa.close(A)
    assert fa.list_sessions() == []
    with pytest.raises(SessionNotFound):
        fa.send_text(A, "x")


def test_variables_roundtrip():
    fa = FakeAdapter()
    fa.add_session(A)
    assert fa.get_variable(A, "user.x") is None
    fa.set_variable(A, "user.x", "1")
    assert fa.get_variable(A, "user.x") == "1"


def test_activate_sets_is_active_flag():
    fa = FakeAdapter()
    fa.add_session(A)
    b = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
    fa.add_session(b)
    fa.activate(b)
    actives = {s.session_id: s.is_active for s in fa.list_sessions()}
    assert actives == {A: False, b: True}


def test_unknown_session_raises():
    fa = FakeAdapter()
    with pytest.raises(SessionNotFound):
        fa.get_screen_contents("missing")


def test_set_name_updates_info():
    fa = FakeAdapter()
    fa.add_session(A, "old")
    fa.set_name(A, "new")
    assert next(s for s in fa.list_sessions() if s.session_id == A).name == "new"


def test_create_tab_in_window_inherits_window_id():
    fa = FakeAdapter()
    fa.add_session(A, window_id="w-1")
    new_id = fa.create_tab(window_id="w-1")
    new_info = next(s for s in fa.list_sessions() if s.session_id == new_id)
    assert new_info.window_id == "w-1"


def test_create_tab_in_unknown_window_raises():
    fa = FakeAdapter()
    with pytest.raises(SessionNotFound):
        fa.create_tab(window_id="missing")
