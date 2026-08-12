import subprocess

import pytest

from gunkata.edit import Edit, EditorNotFoundError
from gunkata.types import ShellError


class _FakeShell:
    """Stands in for Shell: answers read_file/write_file canned, records writes."""

    def __init__(self, content: bytes | None = b"", missing: bool = False):
        self._content = content
        self._missing = missing
        self.write_calls: list[tuple[str, bytes]] = []

    def read_file(self, dpath: str) -> bytes:
        if self._missing:
            raise FileNotFoundError(dpath)
        return self._content

    def write_file(self, dpath: str, data: bytes, *, inherit_owner: bool = True) -> None:
        self.write_calls.append((dpath, data, inherit_owner))


def _editor_that_writes(new_content: bytes):
    """Build a fake `subprocess.run` standing in for an editor that overwrites its argv[1]."""

    def fake_run(argv, **kwargs):
        with open(argv[1], "wb") as f:
            f.write(new_content)
        return subprocess.CompletedProcess(argv, 0)

    return fake_run


def test_run_writes_back_when_the_editor_changed_the_content(monkeypatch):
    """Editing a file that already exists must not chown it -- see inherit_owner design note."""
    shell = _FakeShell(content=b"old\n")
    monkeypatch.setattr(subprocess, "run", _editor_that_writes(b"new\n"))
    edit = Edit(shell, editor="fake-editor")
    assert edit.run("/data/local/tmp/foo") is True
    assert shell.write_calls == [("/data/local/tmp/foo", b"new\n", False)]


def test_run_does_not_write_back_when_the_editor_left_content_unchanged(monkeypatch):
    """No-op edits must not touch the device -- an idle save is not a change."""
    shell = _FakeShell(content=b"same\n")
    monkeypatch.setattr(subprocess, "run", _editor_that_writes(b"same\n"))
    edit = Edit(shell, editor="fake-editor")
    assert edit.run("/data/local/tmp/foo") is False
    assert shell.write_calls == []


def test_run_starts_from_an_empty_buffer_when_the_device_file_is_missing(monkeypatch):
    """A missing dpath is sudoedit-style: edit starts empty, saving creates it."""
    shell = _FakeShell(missing=True)
    monkeypatch.setattr(subprocess, "run", _editor_that_writes(b"created\n"))
    edit = Edit(shell, editor="fake-editor")
    assert edit.run("/data/local/tmp/new") is True
    assert shell.write_calls == [("/data/local/tmp/new", b"created\n", True)]


def test_run_does_not_chown_a_no_op_save_of_a_missing_file(monkeypatch):
    """A missing file saved with no content still counts as no-op: nothing written, no chown."""
    shell = _FakeShell(missing=True)
    monkeypatch.setattr(subprocess, "run", _editor_that_writes(b""))
    edit = Edit(shell, editor="fake-editor")
    assert edit.run("/data/local/tmp/new") is False
    assert shell.write_calls == []


def test_run_raises_when_no_editor_is_configured(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    edit = Edit(_FakeShell(), editor=None)
    with pytest.raises(EditorNotFoundError):
        edit.run("/data/local/tmp/foo")


def test_run_prefers_visual_over_editor_env(monkeypatch):
    monkeypatch.setenv("VISUAL", "visual-editor")
    monkeypatch.setenv("EDITOR", "editor-editor")
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    Edit(_FakeShell(content=b""), editor=None).run("/data/local/tmp/foo")
    assert seen["argv"][0] == "visual-editor"


def test_run_propagates_shell_errors_from_the_write(monkeypatch):
    class _FailingWriteShell(_FakeShell):
        def write_file(self, dpath, data, **kwargs):
            raise ShellError("cat", "denied", 1)

    monkeypatch.setattr(subprocess, "run", _editor_that_writes(b"new\n"))
    edit = Edit(_FailingWriteShell(content=b"old\n"), editor="fake-editor")
    with pytest.raises(ShellError):
        edit.run("/data/local/tmp/foo")
