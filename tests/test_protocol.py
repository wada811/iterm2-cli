from __future__ import annotations

from iterm2_cli.core import Controller
from iterm2_cli.protocol import (
    decode,
    dispatch,
    encode,
    error,
    make_request,
    success,
)
from iterm2_cli.resolver import SessionResolver
from tests.fakes import FakeAdapter

A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"


def ctl():
    fa = FakeAdapter()
    fa.add_session(A, "pane-a")
    return fa, Controller(fa, SessionResolver())


def test_encode_decode_roundtrip():
    msg = make_request("1", "system.ping", {})
    assert decode(encode(msg)) == msg


def test_success_and_error_shape():
    assert success("1", {"x": 1}) == {"id": "1", "ok": True, "result": {"x": 1}}
    e = error("1", "bad", "boom")
    assert e["ok"] is False and e["error"]["code"] == "bad"


def test_dispatch_ping():
    _, c = ctl()
    resp = dispatch(c, make_request("1", "system.ping"))
    assert resp["ok"] and resp["result"] == {"ok": True}


def test_dispatch_list():
    _, c = ctl()
    resp = dispatch(c, make_request("1", "session.list"))
    assert resp["result"]["sessions"][0]["session_id"] == A


def test_dispatch_send_text():
    fa, c = ctl()
    resp = dispatch(c, make_request("1", "session.send_text", {"session": A, "text": "hi"}))
    assert resp["ok"]
    assert fa._get(A).sent == ["hi"]


def test_dispatch_send_key_encodes():
    fa, c = ctl()
    dispatch(c, make_request("1", "session.send_key", {"session": A, "keys": ["enter"]}))
    assert fa._get(A).sent == ["\r"]


def test_dispatch_read_tail():
    fa, c = ctl()
    fa._get(A).screen = ["l1", "l2", "l3"]
    resp = dispatch(c, make_request("1", "session.read", {"session": A, "tail": 2}))
    assert resp["result"]["lines"] == ["l2", "l3"]


def test_dispatch_unknown_method():
    _, c = ctl()
    resp = dispatch(c, make_request("1", "nope.nope"))
    assert not resp["ok"] and resp["error"]["code"] == "unknown_method"


def test_dispatch_missing_param_is_bad_request():
    _, c = ctl()
    resp = dispatch(c, make_request("1", "session.send_text", {"session": A}))  # text 欠落
    assert not resp["ok"] and resp["error"]["code"] == "bad_request"


def test_dispatch_session_not_found():
    _, c = ctl()
    resp = dispatch(c, make_request("1", "session.read", {"session": "missing"}))
    assert not resp["ok"] and resp["error"]["code"] == "session_not_found"
