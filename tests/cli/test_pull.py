import importlib
import io
import subprocess
import tarfile

from typer.testing import CliRunner

from gunkata.cli import pull  # noqa: F401 -- imported for its command registration
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


class _PullFakeAdb:
    """Answers pull's file/directory/missing probe as a file, then `cat <dpath>`
    by writing canned content to the stdout fd, like real adb does.
    """

    def __init__(self, content: bytes = b"", returncode: int = 0):
        self.serial = "fake-serial"
        self._content = content
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        if "stdout" not in kwargs:
            return subprocess.CompletedProcess(args, 0, b"f", b"")
        kwargs["stdout"].write(self._content)
        return subprocess.CompletedProcess(args, self._returncode, b"", b"")


def test_pull_defaults_lpath_to_cwd_and_the_remote_basename(monkeypatch, tmp_path):
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _PullFakeAdb(content=b"payload"))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/foo.bin"])
    assert result.exit_code == 0
    assert (tmp_path / "foo.bin").read_bytes() == b"payload"


def test_pull_honors_an_explicit_lpath(monkeypatch, tmp_path):
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _PullFakeAdb(content=b"payload"))
    dst = tmp_path / "renamed.bin"
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/foo.bin", str(dst)])
    assert result.exit_code == 0
    assert dst.read_bytes() == b"payload"


def test_pull_overwrites_an_existing_local_file(monkeypatch, tmp_path):
    """Pulling the same path twice must not need the first copy moved out of the
    way: the second pull replaces it."""
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _PullFakeAdb(content=b"payload"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "foo.bin").write_bytes(b"stale")
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/foo.bin"])
    assert result.exit_code == 0
    assert (tmp_path / "foo.bin").read_bytes() == b"payload"


def test_pull_leaves_no_file_at_all_when_the_device_command_fails(monkeypatch, tmp_path):
    """Regression guard for the empty-file bug: a failed pull must not leave a
    0-byte file, or a stray .gk-part, at the destination."""
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _PullFakeAdb(returncode=1))
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/foo.bin"])
    assert result.exit_code != 0
    assert not (tmp_path / "foo.bin").exists()
    assert not (tmp_path / "foo.bin.gk-part").exists()


class _PullTreeFakeAdb:
    """Answers pull's probe as a directory, then streams a canned tar archive
    off a real local process, the way real adb streams a pull.
    """

    def __init__(self, script: str):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self.popen_calls: list[list[str]] = []
        self._script = script

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"d", b"")

    def popen(self, args, **kwargs) -> subprocess.Popen:
        self.popen_calls.append(args)
        return subprocess.Popen(["sh", "-c", self._script], **kwargs)


class _PullGlobFakeAdb:
    """A wildcard pull never probes; only popen is ever needed."""

    def __init__(self, script: str):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self._script = script

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        raise AssertionError("a wildcard pull must not probe the device")

    def popen(self, args, **kwargs) -> subprocess.Popen:
        return subprocess.Popen(["sh", "-c", self._script], **kwargs)


def _write_tar(path, members: list[tuple[str, bytes | None]]) -> None:
    with tarfile.open(str(path), mode="w") as tar:
        for name, data in members:
            if data is None:
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))


def test_pull_of_a_directory_prints_where_the_tree_landed(monkeypatch, tmp_path):
    archive = tmp_path / "archive.tar"
    _write_tar(archive, [("./sec", None), ("./sec/a.txt", b"hello")])
    monkeypatch.setattr(
        device_mod, "Adb", lambda *a, **k: _PullTreeFakeAdb(f"cat {archive}")
    )
    out = tmp_path / "out"
    out.mkdir()
    result = CliRunner().invoke(app, ["pull", "/system/etc/sec", str(out)])
    assert result.exit_code == 0
    assert str(out / "sec") in result.stdout


def test_pull_of_a_glob_prints_every_path_that_landed(monkeypatch, tmp_path):
    archive = tmp_path / "archive.tar"
    _write_tar(archive, [("./a.db", b"a"), ("./b.db", b"b")])
    monkeypatch.setattr(
        device_mod, "Adb", lambda *a, **k: _PullGlobFakeAdb(f"cat {archive}")
    )
    out = tmp_path / "out"
    out.mkdir()
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/*.db", str(out)])
    assert result.exit_code == 0
    assert result.stdout.split() == [str(out / "a.db"), str(out / "b.db")]


def test_pull_prints_skipped_entries_to_stderr(monkeypatch, tmp_path):
    archive = tmp_path / "archive.tar"
    with tarfile.open(str(archive), mode="w") as tar:
        info = tarfile.TarInfo("./sec")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tar.addfile(info)
        link = tarfile.TarInfo("./sec/lib")
        link.type = tarfile.SYMTYPE
        link.linkname = "/data/app/pkg/lib"
        tar.addfile(link)
    monkeypatch.setattr(
        device_mod, "Adb", lambda *a, **k: _PullTreeFakeAdb(f"cat {archive}")
    )
    out = tmp_path / "out"
    out.mkdir()
    result = CliRunner().invoke(app, ["pull", "/system/etc/sec", str(out)])
    assert result.exit_code == 0
    assert "skipped 1" in result.stderr
    assert "./sec/lib" in result.stderr


def test_pull_of_an_unsafe_path_exits_2_without_touching_adb(monkeypatch):
    adb = _PullFakeAdb()
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: adb)
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/x'; id; echo '"])
    assert result.exit_code == 2
