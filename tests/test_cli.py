from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from iterm2_cli import cli
from iterm2_cli.core import Controller
from iterm2_cli.resolver import SessionResolver
from tests.fakes import FakeAdapter

A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
runner = CliRunner()


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fa = FakeAdapter()
    fa.add_session(A, "pane-a", is_active=True)
    resolver = SessionResolver(labels={"a": A}, env={"ITERM_SESSION_ID": f"x:{A}"})
    monkeypatch.setattr(cli, "make_controller", lambda: Controller(fa, resolver))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return fa


def test_list_json(fake):
    r = runner.invoke(cli.app, ["list", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data[0]["session_id"] == A


def test_send_to_label(fake):
    r = runner.invoke(cli.app, ["send", "hello", "-t", "a"])
    assert r.exit_code == 0
    assert fake._get(A).sent == ["hello"]


def test_send_current_default(fake):
    r = runner.invoke(cli.app, ["send", "yo"])
    assert r.exit_code == 0
    assert fake._get(A).sent == ["yo"]


def test_send_key(fake):
    r = runner.invoke(cli.app, ["send-key", "enter", "-t", "a"])
    assert r.exit_code == 0
    assert fake._get(A).sent == ["\r"]


def test_send_with_enter(fake):
    r = runner.invoke(cli.app, ["send", "hello", "-t", "a", "--enter"])
    assert r.exit_code == 0
    assert fake._get(A).sent == ["hello", "\r"]


def test_set_status_writes_user_var(fake):
    r = runner.invoke(cli.app, ["set-status", "itermcli_state", "running", "-t", "a"])
    assert r.exit_code == 0
    assert fake._get(A).variables["user.itermcli_state"] == "running"
    # busy がその変数を読む。
    rb = runner.invoke(cli.app, ["busy", "a"])
    assert rb.exit_code == 1  # running → busy → exit 1


def test_set_progress_writes_user_var(fake):
    r = runner.invoke(cli.app, ["set-progress", "42", "-t", "a"])
    assert r.exit_code == 0
    assert fake._get(A).variables["user.itermcli_progress"] == "42"


def test_read_tail_json(fake):
    fake._get(A).screen = ["l1", "l2", "l3"]
    r = runner.invoke(cli.app, ["read", "a", "--tail", "2", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.stdout)["lines"] == ["l2", "l3"]


def test_busy_exit_code(fake):
    fake._get(A).screen = ["esc to interrupt"]
    r = runner.invoke(cli.app, ["busy", "a"])
    assert r.exit_code == 1
    assert "busy" in r.stdout


def test_idle_exit_zero(fake):
    fake._get(A).screen = ["$ ready"]
    r = runner.invoke(cli.app, ["busy", "a"])
    assert r.exit_code == 0


def test_split_outputs_new_id(fake):
    r = runner.invoke(cli.app, ["split", "a"])
    assert r.exit_code == 0
    assert r.stdout.strip() in [s.session_id for s in fake.list_sessions()]


def test_focus_and_close(fake):
    assert runner.invoke(cli.app, ["focus", "a"]).exit_code == 0
    assert runner.invoke(cli.app, ["close", "a"]).exit_code == 0
    assert fake.list_sessions() == []


def test_var_set_get(fake):
    assert runner.invoke(cli.app, ["var", "set", "user.k", "v", "-t", "a"]).exit_code == 0
    r = runner.invoke(cli.app, ["var", "get", "user.k", "-t", "a"])
    assert r.stdout.strip() == "v"


def test_unknown_target_exit_2(fake):
    r = runner.invoke(cli.app, ["read", "nope"])
    assert r.exit_code == 2


def test_label_set_ls_rm(fake):
    assert runner.invoke(cli.app, ["label", "set", "worker", A]).exit_code == 0
    r = runner.invoke(cli.app, ["label", "ls", "--json"])
    assert json.loads(r.stdout)["worker"] == A
    assert runner.invoke(cli.app, ["label", "rm", "worker"]).exit_code == 0
    r2 = runner.invoke(cli.app, ["label", "ls", "--json"])
    assert json.loads(r2.stdout) == {}


def test_ping(fake):
    r = runner.invoke(cli.app, ["ping"])
    assert r.exit_code == 0
    assert "ok" in r.stdout
