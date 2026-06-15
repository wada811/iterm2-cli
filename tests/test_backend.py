"""Controller と DaemonClient が Backend 表面を満たすことを担保する（ドリフト検出）。"""

from __future__ import annotations

from iterm2_cli.backend import Backend
from iterm2_cli.client import DaemonClient
from iterm2_cli.core import Controller
from iterm2_cli.resolver import SessionResolver
from tests.fakes import FakeAdapter


def test_controller_satisfies_backend():
    c = Controller(FakeAdapter(), SessionResolver())
    assert isinstance(c, Backend)


def test_daemon_client_satisfies_backend():
    client = DaemonClient("/tmp/does-not-matter.sock", SessionResolver())
    assert isinstance(client, Backend)
