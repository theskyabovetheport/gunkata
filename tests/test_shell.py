import subprocess

import pytest

from gunkata.shell import Shell
from gunkata.types import ShellError, ShellResult


class _SpyAdb:
    """Records the args it was called with; returns a canned CompletedProcess.

    stdout/stderr accept str for readability at call sites; real Adb (no
    text=True since the sh()/pull_file/etc. fix) returns bytes, so str inputs
    are encoded to match.
    """

    def __init__(
        self, stdout: str | bytes = "", stderr: str | bytes = "", returncode: int = 0
    ):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self._stdout = stdout.encode() if isinstance(stdout, str) else stdout
        self._stderr = stderr.encode() if isinstance(stderr, str) else stderr
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=self._returncode,
            stdout=self._stdout,
            stderr=self._stderr,
        )


def test_ok_true_on_zero_returncode():
    assert ShellResult(command="id", stdout="", stderr="", rc=0).ok


def test_ok_false_on_nonzero_returncode():
    assert not ShellResult(command="id", stdout="", stderr="", rc=1).ok


def test_output_joins_stdout_and_stderr():
    result = ShellResult(command="id", stdout="out", stderr="err", rc=0)
    assert result.output == "out\nerr"


def test_su_wraps_command_with_su_binary_and_user():
    shell = Shell(_SpyAdb(), user="root", su_binary="su")
    assert shell._su("id") == "su root sh -c 'id'"


def test_su_omits_user_token_when_user_is_none():
    """Some su wrappers (non-standard builds) don't accept a username at all."""
    shell = Shell(_SpyAdb(), user=None, su_binary="su")
    assert shell._su("id") == "su sh -c 'id'"


def test_call_runs_command_and_captures_output():
    adb = _SpyAdb(stdout="hello\n", returncode=0)
    result = Shell(adb, user="shell", su_binary="su")("echo hello")
    assert result.ok
    assert result.stdout == "hello"
    assert adb.calls == [["shell", "su shell sh -c 'echo hello'"]]


def test_read_file_returns_raw_bytes():
    adb = _SpyAdb(stdout=b"\x00\x01binary data", returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.read_file("/data/local/tmp/f") == b"\x00\x01binary data"
    assert adb.calls == [["shell", "su root sh -c 'cat /data/local/tmp/f'"]]


def test_read_file_raises_on_nonzero_returncode():
    adb = _SpyAdb(stdout=b"", returncode=1)
    shell = Shell(adb, user="root", su_binary="su")
    with pytest.raises(RuntimeError):
        shell.read_file("/no/such/file")


def test_write_file_sends_data_and_returns_on_success():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    shell.write_file("/data/local/tmp/f", b"payload bytes")
    assert adb.calls == [["shell", "su root sh -c 'cat >/data/local/tmp/f'"]]


def test_write_file_raises_on_nonzero_returncode():
    adb = _SpyAdb(returncode=1)
    shell = Shell(adb, user="root", su_binary="su")
    with pytest.raises(RuntimeError):
        shell.write_file("/no/such/dir/f", b"x")


def test_dir_exists_true_when_present():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.dir_exists("/data/local/tmp") is True
    assert adb.calls == [["shell", "su root sh -c '[ -d /data/local/tmp ]'"]]


def test_dir_exists_false_when_absent():
    adb = _SpyAdb(returncode=1)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.dir_exists("/no/such/dir") is False


def test_file_exists_true_when_present():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.file_exists("/data/local/tmp/f") is True
    assert adb.calls == [["shell", "su root sh -c '[ -f /data/local/tmp/f ]'"]]


def test_path_exists_true_when_present():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.path_exists("/data/local/tmp") is True
    assert adb.calls == [["shell", "su root sh -c '[ -e /data/local/tmp ]'"]]


def test_chown_runs_chown():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    shell.chown("/data/local/tmp/f", "1000:1000")
    assert adb.calls == [["shell", "su root sh -c 'chown 1000:1000 /data/local/tmp/f'"]]


def test_chown_raises_shell_error_on_failure():
    adb = _SpyAdb(returncode=1, stderr="chown: no such file")
    shell = Shell(adb, user="root", su_binary="su")
    with pytest.raises(ShellError):
        shell.chown("/no/such/file", "1000:1000")


def test_chmod_runs_chmod():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    shell.chmod("/data/local/tmp/f", "755")
    assert adb.calls == [["shell", "su root sh -c 'chmod 755 /data/local/tmp/f'"]]


def test_chmod_raises_shell_error_on_failure():
    adb = _SpyAdb(returncode=1, stderr="chmod: no such file")
    shell = Shell(adb, user="root", su_binary="su")
    with pytest.raises(ShellError):
        shell.chmod("/no/such/file", "755")


def test_pidof_returns_pids_when_running():
    adb = _SpyAdb(stdout="123 456\n", returncode=0)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.pidof("zygote") == ["123", "456"]


def test_pidof_returns_empty_list_when_not_running():
    adb = _SpyAdb(stdout="", returncode=1)
    shell = Shell(adb, user="root", su_binary="su")
    assert shell.pidof("nonexistent-proc") == []


class _PopenSpyAdb:
    """Records the args a streaming spawn was given; runs a trivial local process."""

    def __init__(self):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []

    def popen(self, args, **kwargs) -> subprocess.Popen:
        self.calls.append(args)
        return subprocess.Popen(["true"], **kwargs)


def test_stream_wraps_the_command_in_su_exactly_as_sh_does():
    """A command must reach the device identically whether awaited or followed.

    Only delivery differs between sh() and stream(); if the su wrapping drifted
    between them, a command would mean two different things.
    """
    adb = _PopenSpyAdb()
    with Shell(adb, user="root", su_binary="su").stream("logcat"):
        pass
    assert adb.calls == [["shell", "su root sh -c 'logcat'"]]


@pytest.mark.emulator
def test_stream_against_real_device(device):
    assert list(device.shell().stream("echo streamed")) == ["streamed"]


@pytest.mark.emulator
def test_call_against_real_device_captures_output(device):
    """Against a live device, sh('id') must capture stdout, not leak it to the terminal."""
    result = device.shell().sh("id")
    assert result.ok
    assert "uid=" in result.stdout


@pytest.mark.emulator
def test_push_pull_round_trip_against_real_device(device, tmp_path):
    """push() must land bytes on-device unchanged, and pull() must retrieve them back."""
    payload = b"gunkata push/pull round trip\n"
    local_src = tmp_path / "src.bin"
    local_src.write_bytes(payload)
    local_dst = tmp_path / "dst.bin"
    remote_path = "/data/local/tmp/gunkata_test_push_pull"

    shell = device.shell()
    try:
        shell.push_file(remote_path, str(local_src))
        shell.pull_file(remote_path, str(local_dst))
        assert local_dst.read_bytes() == payload
    finally:
        shell(f"rm -f {remote_path}")


@pytest.mark.emulator
def test_read_write_file_round_trip_against_real_device(device):
    """write_file() must land bytes on-device unchanged, and read_file() must retrieve them back."""
    payload = b"gunkata read/write round trip\n"
    remote_path = "/data/local/tmp/gunkata_test_read_write"

    shell = device.shell()
    try:
        shell.write_file(remote_path, payload)
        assert shell.read_file(remote_path) == payload
    finally:
        shell(f"rm -f {remote_path}")


@pytest.mark.emulator
def test_dir_file_path_exists_against_real_device(device, tmp_path):
    shell = device.shell()
    assert shell.dir_exists("/data/local/tmp")
    assert not shell.dir_exists("/no/such/dir")

    local_src = tmp_path / "src.bin"
    local_src.write_bytes(b"exists test\n")
    remote_path = "/data/local/tmp/gunkata_test_exists"
    try:
        shell.push_file(remote_path, str(local_src))
        assert shell.file_exists(remote_path)
        assert shell.path_exists(remote_path)
        assert not shell.file_exists("/data/local/tmp/gunkata_test_exists_absent")
    finally:
        shell(f"rm -f {remote_path}")


@pytest.mark.emulator
def test_chown_chmod_against_real_device(device, tmp_path):
    local_src = tmp_path / "src.bin"
    local_src.write_bytes(b"chown chmod test\n")
    remote_path = "/data/local/tmp/gunkata_test_chown_chmod"

    shell = device.shell()
    try:
        shell.push_file(remote_path, str(local_src), inherit_owner=False)
        shell.chown(remote_path, "shell:shell")
        assert shell(f"stat -c %U:%G {remote_path}").stdout == "shell:shell"
        shell.chmod(remote_path, "640")
        assert shell(f"stat -c %a {remote_path}").stdout == "640"
    finally:
        shell(f"rm -f {remote_path}")


@pytest.mark.emulator
def test_pidof_against_real_device(device):
    """adbd is always running on a device we're connected to over adb."""
    shell = device.shell()
    assert shell.pidof("adbd") != []
    assert shell.pidof("definitely-not-a-real-process-name") == []


@pytest.mark.emulator
def test_inherit_owner_matches_parent_directory(device, tmp_path):
    """inherit_owner must chown the target to its parent directory's uid:gid."""
    local_src = tmp_path / "src.bin"
    local_src.write_bytes(b"owner test\n")
    remote_path = "/data/local/tmp/gunkata_test_inherit_owner"

    shell = device.shell()
    try:
        shell.push_file(remote_path, str(local_src), inherit_owner=False)
        shell.inherit_owner(remote_path)
        parent_owner = shell(f"stat -c %u:%g $(dirname {remote_path})").stdout.strip()
        file_owner = shell(f"stat -c %u:%g {remote_path}").stdout.strip()
        assert file_owner == parent_owner
    finally:
        shell(f"rm -f {remote_path}")
