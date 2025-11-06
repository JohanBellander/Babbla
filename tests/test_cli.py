from __future__ import annotations

import io
import types
from contextlib import redirect_stdout

from babbla import cli


def test_cli_requires_text():
    dummy_stdout = io.StringIO()
    with redirect_stdout(dummy_stdout):
        exit_code = cli.main([])
    assert exit_code == 2


def test_cli_dry_run_with_positional_text():
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cli.main(["--dry-run", "Hello CLI"])
    assert exit_code == 0
    output = buffer.getvalue()
    assert "Chunks" in output
    assert "estimated_frames" in output


def test_cli_reads_from_stdin(monkeypatch):
    class FakeStdin(io.StringIO):
        def isatty(self) -> bool:
            return False

    fake_stdin = FakeStdin("Hello from stdin")
    fake_sys = types.SimpleNamespace(stdin=fake_stdin)
    monkeypatch.setattr(cli, "sys", fake_sys)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = cli.main(["--dry-run"])
    assert exit_code == 0
    assert "Chunks" in buffer.getvalue()
