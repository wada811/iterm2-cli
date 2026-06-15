"""SessionResolver のテストリスト（Canon TDD）。

期待する振る舞い（requirements.md FR11 / design.md §4）:
  1. 明示 --session id はそのまま返る
  2. 位置引数が既知ラベルならその session_id に解決
  3. 位置引数が UUID ならそのまま返る
  4. target 未指定なら current = $ITERM_SESSION_ID（wNtMpK: 接頭辞を剥がす）
  5. target も ITERM_SESSION_ID も無ければ ResolutionError
  6. 未知の位置引数（ラベルでも UUID でもない）は ResolutionError
  7. 優先順: --session > 位置引数 > env
"""

from __future__ import annotations

import pytest

from iterm2_cli.resolver import (
    ResolutionError,
    SessionResolver,
    strip_iterm_session_prefix,
)

UUID_A = "3970511E-DDB7-4CE6-9364-3E200AF48272"
UUID_B = "8F519BAB-3E6D-45FB-ADE8-E04202D5C0CA"


def test_explicit_session_returned_as_is():
    r = SessionResolver()
    assert r.resolve(session=UUID_A) == UUID_A


def test_label_resolves_to_session_id():
    r = SessionResolver(labels={"worker": UUID_A})
    assert r.resolve("worker") == UUID_A


def test_uuid_target_returned_as_is():
    r = SessionResolver()
    assert r.resolve(UUID_B) == UUID_B


def test_current_from_env_strips_prefix():
    r = SessionResolver(env={"ITERM_SESSION_ID": f"w1t3p0:{UUID_A}"})
    assert r.resolve() == UUID_A


def test_no_target_no_env_raises():
    r = SessionResolver(env={})
    with pytest.raises(ResolutionError):
        r.resolve()


def test_unknown_target_raises():
    r = SessionResolver(labels={"known": UUID_A})
    with pytest.raises(ResolutionError):
        r.resolve("does-not-exist")


def test_precedence_session_over_label_and_env():
    r = SessionResolver(
        labels={"worker": UUID_B},
        env={"ITERM_SESSION_ID": f"w1t3p0:{UUID_B}"},
    )
    assert r.resolve("worker", session=UUID_A) == UUID_A


def test_strip_prefix_without_colon_is_identity():
    assert strip_iterm_session_prefix(UUID_A) == UUID_A
