from __future__ import annotations

import pytest

from iterm2_cli.keys import UnknownKey, encode_key, encode_keys


@pytest.mark.parametrize(
    "name,expected",
    [
        ("enter", "\r"),
        ("return", "\r"),
        ("tab", "\t"),
        ("escape", "\x1b"),
        ("esc", "\x1b"),
        ("backspace", "\x7f"),
        ("up", "\x1b[A"),
        ("down", "\x1b[B"),
        ("right", "\x1b[C"),
        ("left", "\x1b[D"),
    ],
)
def test_named_keys(name, expected):
    assert encode_key(name) == expected


def test_case_insensitive_and_trim():
    assert encode_key("  ENTER ") == "\r"


@pytest.mark.parametrize("name", ["ctrl-c", "ctrl+c", "c-c", "^c", "CTRL-C"])
def test_ctrl_variants(name):
    assert encode_key(name) == "\x03"


def test_ctrl_d_and_z():
    assert encode_key("ctrl-d") == "\x04"
    assert encode_key("ctrl-z") == "\x1a"


def test_unknown_key_raises():
    with pytest.raises(UnknownKey):
        encode_key("nope")


def test_encode_keys_concat():
    assert encode_keys(["ctrl-c", "enter"]) == "\x03\r"
