import subprocess

from typer.testing import CliRunner

from gunkata import localedit
from gunkata.cli import edit as edit_cli
from gunkata.cli.app import app


class _EditFakeAdb:
    """Answers `command -v su`, `cat <dpath>` (read), `cat ><dpath>` (write), and chown canned."""

    def __init__(self, content: bytes = b"old\n", read_ok: bool = True):
        self.serial = "fake-serial"
        self._content = content
        self._read_ok = read_ok
        self.written: bytes | None = None
        self.chown_calls: list[str] = []

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        if "if [ -e" in command:
            if not self._read_ok:
                return subprocess.CompletedProcess(args, 90, b"", b"")
            return subprocess.CompletedProcess(args, 0, self._content, b"")
        if "cat >" in command:
            data = kwargs.get("input", b"")
            self.written = data
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if "chown" in command:
            self.chown_calls.append(command)
            return subprocess.CompletedProcess(args, 0, b"", b"")
        raise AssertionError(f"unexpected command: {command!r}")


def _editor_that_writes(new_content: bytes):
    def fake_run(argv, **kwargs):
        with open(argv[1], "wb") as f:
            f.write(new_content)
        return subprocess.CompletedProcess(argv, 0)

    return fake_run


def test_edit_writes_back_a_changed_file(monkeypatch):
    """Editing a file that already exists must not chown it -- see Edit.run's design note."""
    fake = _EditFakeAdb(content=b"old\n")
    monkeypatch.setattr(edit_cli, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(localedit.subprocess, "run", _editor_that_writes(b"new\n"))
    result = CliRunner().invoke(
        app, ["edit", "/data/local/tmp/foo", "--editor", "fake-editor"]
    )
    assert result.exit_code == 0
    assert "updated" in result.output
    assert fake.written == b"new\n"
    assert fake.chown_calls == []


def test_edit_creating_a_missing_file_chowns_it_to_its_parent_dir(monkeypatch):
    """create-on-write must inherit the parent directory's owner -- a fresh inode is
    otherwise owned by whichever user ran the write, not the app that owns the dir."""
    fake = _EditFakeAdb(read_ok=False)
    monkeypatch.setattr(edit_cli, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(localedit.subprocess, "run", _editor_that_writes(b"created\n"))
    result = CliRunner().invoke(
        app, ["edit", "/data/local/tmp/new", "--editor", "fake-editor"]
    )
    assert result.exit_code == 0
    assert "updated" in result.output
    assert fake.written == b"created\n"
    assert len(fake.chown_calls) == 1
    assert "dirname /data/local/tmp/new" in fake.chown_calls[0]


def test_edit_reports_unchanged_without_writing(monkeypatch):
    fake = _EditFakeAdb(content=b"same\n")
    monkeypatch.setattr(edit_cli, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(localedit.subprocess, "run", _editor_that_writes(b"same\n"))
    result = CliRunner().invoke(
        app, ["edit", "/data/local/tmp/foo", "--editor", "fake-editor"]
    )
    assert result.exit_code == 0
    assert "unchanged" in result.output
    assert fake.written is None


def test_edit_exits_loudly_when_no_editor_is_configured(monkeypatch):
    fake = _EditFakeAdb(content=b"old\n")
    monkeypatch.setattr(edit_cli, "Adb", lambda *a, **k: fake)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    result = CliRunner().invoke(app, ["edit", "/data/local/tmp/foo"])
    assert result.exit_code == 1
    assert "editor" in result.output
