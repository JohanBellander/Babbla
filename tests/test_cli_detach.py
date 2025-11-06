from __future__ import annotations

import types

from babbla import cli


def test_detach_returns_immediately(monkeypatch):
    # Monkeypatch subprocess.Popen to avoid spawning a real background process.
    class DummyProc:
        def __init__(self):
            self.pid = 43210
    fake_subprocess = types.SimpleNamespace(
        Popen=lambda *a, **k: DummyProc(), DEVNULL=None
    )
    monkeypatch.setattr(cli, "subprocess", fake_subprocess)

    exit_code = cli.main(["--detach", "--dry-run", "Hello async detach"])
    assert exit_code == 0
