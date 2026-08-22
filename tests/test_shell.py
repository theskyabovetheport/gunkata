import io
import os
import shlex
import subprocess
import tarfile

import pytest

from gunkata.shell import PullResult, Shell, ShellError, ShellResult, ShellSettings
from gunkata.su import Su


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


def test_output_concatenates_stdout_and_stderr_with_no_separator():
    result = ShellResult(command="id", stdout="out", stderr="err", rc=0)
    assert result.output == "outerr"


def test_serial_forwards_the_bound_adbs_serial():
    shell = Shell(_SpyAdb(), user="shell", su=Su())
    assert shell.serial == "fake-serial"


def test_su_wraps_command_with_su_binary_and_user():
    shell = Shell(_SpyAdb(), user="root", su=Su())
    assert shell._su("id") == "su root sh -c id"


def test_su_wraps_for_any_user_other_than_shell_with_no_env_var_required():
    """There is no enabled/disabled state: naming any user other than "shell"
    always wraps, with default settings and no GUNKATA_* env var set."""
    shell = Shell(_SpyAdb(), user="operator", su=Su())
    assert shell._su("id") == "su operator sh -c id"


def test_su_sends_the_command_unwrapped_for_the_shell_user():
    """"shell" names adb's own already-unprivileged user, not an su target --
    it is the one identity wrap never touches."""
    shell = Shell(_SpyAdb(), user="shell", su=Su())
    assert shell._su("id") == "id"


def test_wrap_drops_the_placeholder_silently_for_root():
    """"root" is su's own no-argument default -- some su binaries reject an
    explicit user entirely -- so a wrapper-script template with no {user}
    still wraps for "root", dropping the identity rather than raising."""
    su = Su(command="/data/local/tmp/wrapper.sh {command}")
    shell = Shell(_SpyAdb(), user="root", su=su)
    assert shell._su("id") == "/data/local/tmp/wrapper.sh id"


def test_wrap_raises_when_the_command_has_no_user_placeholder():
    """A wrapper-script template with a single fixed identity baked in is a
    legitimate default (see test_custom_command_can_reference_only_the_
    placeholders_it_needs below), but silently dropping a different,
    explicitly named user onto it would run as the wrong identity. Loud
    instead."""
    su = Su(command="/data/local/tmp/wrapper.sh {command}")
    with pytest.raises(ValueError, match="operator"):
        su.wrap("id", "operator")


def test_su_rejects_a_command_template_containing_a_single_quote():
    """A template that quotes {command} itself would double-quote it the
    moment a command needed escaping. Raising at construction means a
    misconfigured GUNKATA_SU_COMMAND fails immediately, rather than
    corrupting some later command silently."""
    with pytest.raises(ValueError, match="single quote"):
        Su(command="su {user} sh -c '{command}'")


def test_custom_command_overrides_the_built_command_line_entirely():
    """A su binary that accepts -c directly, or a wrapper script with its own
    calling convention, needs none of the default's sh hop -- command is the
    single escape hatch for any calling convention. The template writes
    {command} bare: Su.wrap supplies the quoting, not the template."""
    su = Su(command="su {user} -c {command}")
    shell = Shell(_SpyAdb(), user="root", su=su)
    assert shell._su("id") == "su root -c id"


def test_custom_command_places_user_with_ordinary_spacing_when_absent():
    """A template author writes {user} spaced like any other word; wrap
    collapses the run of whitespace an empty user leaves behind, rather
    than requiring the template to omit the space itself."""
    su = Su(command="su {user} -c {command}")
    shell = Shell(_SpyAdb(), user="", su=su)
    assert shell._su("id") == "su -c id"


def test_custom_command_can_reference_only_the_placeholders_it_needs():
    """command always arrives as one shlex-quoted shell word -- the wrapper
    script sees "cmd wifi status" as $1, not three separate positional args."""
    su = Su(command="/data/local/tmp/wrapper.sh {command}")
    shell = Shell(_SpyAdb(), user="root", su=su)
    assert shell._su("cmd wifi status") == "/data/local/tmp/wrapper.sh 'cmd wifi status'"


def test_wrap_escapes_a_command_that_quotes_itself():
    """A command that already contains single quotes (a glob guarded against
    expansion, e.g.) must survive as one argument to the inner shell rather
    than closing the template's quoting early and leaking the rest unquoted --
    see the su-command-quoting invariant in the root CLAUDE.md."""
    shell = Shell(_SpyAdb(), user="root", su=Su())
    assert (
        shell._su("find /data/local/tmp/foobar/ -type f -name '*'")
        == "su root sh -c 'find /data/local/tmp/foobar/ -type f -name '\"'\"'*'\"'\"''"
    )


def test_wrap_escapes_a_command_that_quotes_itself_against_a_custom_template():
    """The same escaping applies to any template, not just the default's --
    the caller's command is safe regardless of which su invocation this
    device is configured with."""
    su = Su(command="/data/local/tmp/su -c {command}")
    shell = Shell(_SpyAdb(), user="root", su=su)
    assert (
        shell._su("find /data/local/tmp/foobar/ -type f -name '*'")
        == "/data/local/tmp/su -c 'find /data/local/tmp/foobar/ -type f -name '\"'\"'*'\"'\"''"
    )


def test_default_user_env_var_is_read_by_shell_settings(monkeypatch):
    """default_user is Device.shell's own defaulting, resolved by ShellSettings
    rather than Su -- see ShellSettings' docstring."""
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "root")
    assert ShellSettings().default_user == "root"


def test_default_user_is_shell_by_default():
    assert ShellSettings().default_user == "shell"


def test_command_env_var_is_read_by_su(monkeypatch):
    monkeypatch.setenv("GUNKATA_SU_COMMAND", "/data/local/tmp/wrapper.sh {command}")
    shell = Shell(_SpyAdb(), user="root", su=Su())
    assert shell._su("id") == "/data/local/tmp/wrapper.sh id"


def test_call_runs_command_and_captures_output():
    adb = _SpyAdb(stdout="hello\n", returncode=0)
    result = Shell(adb, user="root", su=Su())("echo hello")
    assert result.ok
    assert result.stdout == "hello"
    assert adb.calls == [["shell", "su root sh -c 'echo hello'"]]


def test_read_file_returns_raw_bytes():
    adb = _SpyAdb(stdout=b"\x00\x01binary data", returncode=0)
    shell = Shell(adb, user="root", su=Su())
    assert shell.read_file("/data/local/tmp/f") == b"\x00\x01binary data"
    assert adb.calls == [
        [
            "shell",
            "su root sh -c 'if [ -e /data/local/tmp/f ]; then cat /data/local/tmp/f; "
            "else exit 90; fi'",
        ]
    ]


def test_read_file_raises_on_nonzero_returncode():
    adb = _SpyAdb(stdout=b"", returncode=1)
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(RuntimeError):
        shell.read_file("/no/such/file")


def test_read_file_raises_file_not_found_when_the_remote_path_is_missing():
    """A missing path is reported via a sentinel exit status, not by matching cat's
    stderr text, which differs across toybox/busybox/coreutils and can be localized."""
    adb = _SpyAdb(stdout=b"", returncode=Shell._MISSING_FILE_RC)
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(FileNotFoundError):
        shell.read_file("/no/such/file")


def test_write_file_sends_data_and_inherits_owner_by_default():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.write_file("/data/local/tmp/f", b"payload bytes")
    assert adb.calls == [
        ["shell", "su root sh -c 'cat >/data/local/tmp/f'"],
        [
            "shell",
            "su root sh -c 'chown $(stat -c %u:%g $(dirname /data/local/tmp/f)) /data/local/tmp/f'",
        ],
    ]


def test_write_file_can_skip_inheriting_owner():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.write_file("/data/local/tmp/f", b"payload bytes", inherit_owner=False)
    assert adb.calls == [["shell", "su root sh -c 'cat >/data/local/tmp/f'"]]


def test_write_file_raises_on_nonzero_returncode():
    adb = _SpyAdb(returncode=1)
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(RuntimeError):
        shell.write_file("/no/such/dir/f", b"x")


def test_inherit_owner_recursive_by_default():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.inherit_owner("/data/local/tmp/d")
    assert adb.calls == [
        [
            "shell",
            "su root sh -c 'chown -R $(stat -c %u:%g $(dirname /data/local/tmp/d)) "
            "/data/local/tmp/d'",
        ]
    ]


def test_mkdir_creates_and_inherits_owner():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.mkdir("/data/local/tmp/d")
    assert adb.calls == [
        ["shell", "su root sh -c 'mkdir -p /data/local/tmp/d'"],
        [
            "shell",
            "su root sh -c 'chown -R $(stat -c %u:%g $(dirname /data/local/tmp/d)) "
            "/data/local/tmp/d'",
        ],
    ]


def test_touch_creates_and_inherits_owner():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.touch("/data/local/tmp/f")
    assert adb.calls == [
        ["shell", "su root sh -c 'touch /data/local/tmp/f'"],
        [
            "shell",
            "su root sh -c 'chown -R $(stat -c %u:%g $(dirname /data/local/tmp/f)) "
            "/data/local/tmp/f'",
        ],
    ]


def test_dir_exists_true_when_present():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    assert shell.dir_exists("/data/local/tmp") is True
    assert adb.calls == [["shell", "su root sh -c '[ -d /data/local/tmp ]'"]]


def test_dir_exists_false_when_absent():
    adb = _SpyAdb(returncode=1)
    shell = Shell(adb, user="root", su=Su())
    assert shell.dir_exists("/no/such/dir") is False


def test_file_exists_true_when_present():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    assert shell.file_exists("/data/local/tmp/f") is True
    assert adb.calls == [["shell", "su root sh -c '[ -f /data/local/tmp/f ]'"]]


def test_path_exists_true_when_present():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    assert shell.path_exists("/data/local/tmp") is True
    assert adb.calls == [["shell", "su root sh -c '[ -e /data/local/tmp ]'"]]


def test_chown_runs_chown():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.chown("/data/local/tmp/f", "1000", "1000")
    assert adb.calls == [["shell", "su root sh -c 'chown 1000:1000 /data/local/tmp/f'"]]


def test_chown_raises_shell_error_on_failure():
    adb = _SpyAdb(returncode=1, stderr="chown: no such file")
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(ShellError):
        shell.chown("/no/such/file", "1000", "1000")


def test_chmod_runs_chmod():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.chmod("/data/local/tmp/f", "755")
    assert adb.calls == [["shell", "su root sh -c 'chmod 755 /data/local/tmp/f'"]]


def test_chmod_raises_shell_error_on_failure():
    adb = _SpyAdb(returncode=1, stderr="chmod: no such file")
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(ShellError):
        shell.chmod("/no/such/file", "755")


def test_pidof_returns_pids_when_running():
    adb = _SpyAdb(stdout="123 456\n", returncode=0)
    shell = Shell(adb, user="root", su=Su())
    assert shell.pidof("zygote") == [123, 456]


def test_pidof_returns_empty_list_when_not_running():
    adb = _SpyAdb(stdout="", returncode=1)
    shell = Shell(adb, user="root", su=Su())
    assert shell.pidof("nonexistent-proc") == []


def test_read_bytes_returns_raw_unstripped_stdout():
    adb = _SpyAdb(stdout=b"payload\n\x00trailing", returncode=0)
    shell = Shell(adb, user="root", su=Su())
    assert shell.read_bytes("cat somefile") == b"payload\n\x00trailing"
    assert adb.calls == [["shell", "su root sh -c 'cat somefile'"]]


def test_read_bytes_raises_shell_error_on_failure():
    adb = _SpyAdb(returncode=1, stderr="boom")
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(ShellError):
        shell.read_bytes("false")


def test_write_bytes_sends_data_to_the_commands_stdin():
    adb = _SpyAdb(returncode=0)
    shell = Shell(adb, user="root", su=Su())
    shell.write_bytes("cat >somefile", b"payload")
    assert adb.calls == [["shell", "su root sh -c 'cat >somefile'"]]


def test_write_bytes_raises_shell_error_on_failure():
    adb = _SpyAdb(returncode=1, stderr="boom")
    shell = Shell(adb, user="root", su=Su())
    with pytest.raises(ShellError):
        shell.write_bytes("false", b"x")


class _PullFileSpyAdb:
    """Writes canned content to the fd passed as stdout=, the way real adb streams a pull."""

    def __init__(self, content: bytes = b"", returncode: int = 0):
        self.serial = "fake-serial"
        self._content = content
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        kwargs["stdout"].write(self._content)
        return subprocess.CompletedProcess(args, self._returncode, b"", b"")


def test_pull_file_replaces_an_existing_lpath(tmp_path):
    lpath = tmp_path / "dst.bin"
    lpath.write_bytes(b"existing")
    shell = Shell(_PullFileSpyAdb(content=b"payload"), user="root", su=Su())
    shell.pull_file("/data/local/tmp/src.bin", str(lpath))
    assert lpath.read_bytes() == b"payload"


def test_pull_file_leaves_an_existing_lpath_untouched_when_the_pull_fails(tmp_path):
    """Overwriting must stay all-or-nothing: a failed pull leaves the previous
    contents in place rather than a truncated or empty file -- the .gk-part
    plus rename in pull_file's Design note is what buys that."""
    lpath = tmp_path / "dst.bin"
    lpath.write_bytes(b"existing")
    shell = Shell(_PullFileSpyAdb(returncode=1), user="root", su=Su())
    with pytest.raises(ShellError):
        shell.pull_file("/data/local/tmp/src.bin", str(lpath))
    assert lpath.read_bytes() == b"existing"
    assert not (tmp_path / "dst.bin.gk-part").exists()


def test_pull_file_refuses_a_directory_at_lpath(tmp_path):
    """A directory cannot be replaced by the pulled file, and the refusal comes
    before the transfer, so no .gk-part is spooled beside it first."""
    lpath = tmp_path / "dst"
    lpath.mkdir()
    shell = Shell(_PullFileSpyAdb(content=b"payload"), user="root", su=Su())
    with pytest.raises(IsADirectoryError):
        shell.pull_file("/data/local/tmp/src.bin", str(lpath))
    assert not (tmp_path / "dst.gk-part").exists()


def test_pull_file_publishes_via_rename_with_no_partial_file_left_behind(tmp_path):
    lpath = tmp_path / "dst.bin"
    shell = Shell(_PullFileSpyAdb(content=b"payload"), user="root", su=Su())
    shell.pull_file("/data/local/tmp/src.bin", str(lpath))
    assert lpath.read_bytes() == b"payload"
    assert not (tmp_path / "dst.bin.gk-part").exists()


def test_pull_file_leaves_nothing_at_lpath_on_failure(tmp_path):
    """Regression guard: a failed pull that never wrote any bytes must leave
    neither a 0-byte lpath nor an empty .gk-part behind -- see pull_file's
    Design note."""
    lpath = tmp_path / "dst.bin"
    shell = Shell(_PullFileSpyAdb(returncode=1), user="root", su=Su())
    with pytest.raises(ShellError):
        shell.pull_file("/data/local/tmp/src.bin", str(lpath))
    assert not lpath.exists()
    assert not (tmp_path / "dst.bin.gk-part").exists()


def test_pull_file_keeps_a_nonempty_partial_and_warns_on_failure(tmp_path, caplog):
    """A failure after some bytes landed must not throw that data away: the
    .gk-part is kept, and its path logged, rather than silently deleted."""
    lpath = tmp_path / "dst.bin"
    shell = Shell(
        _PullFileSpyAdb(content=b"partial data", returncode=1),
        user="root",
        su=Su(),
    )
    with caplog.at_level("WARNING"), pytest.raises(ShellError):
        shell.pull_file("/data/local/tmp/src.bin", str(lpath))
    tmp_path_on_disk = tmp_path / "dst.bin.gk-part"
    assert not lpath.exists()
    assert tmp_path_on_disk.read_bytes() == b"partial data"
    assert str(tmp_path_on_disk) in caplog.text


class _PushFileSpyAdb:
    """Records every command; answers `[ -d <path> ]` from a canned set of device directories.

    push_file probes the target before writing, so a double with one fixed
    returncode cannot express "the target is not a directory, and the write
    then succeeds".
    """

    _DIR_TEST_PREFIX = "[ -d "
    _DIR_TEST_SUFFIX = " ]"

    def __init__(self, dirs: tuple[str, ...] = ()):
        self.serial = "fake-serial"
        self.commands: list[str] = []
        self._dirs = dirs

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1]
        self.commands.append(command)
        return subprocess.CompletedProcess(args, self._returncode(command), b"", b"")

    def _returncode(self, command: str) -> int:
        if not (
            command.startswith(self._DIR_TEST_PREFIX)
            and command.endswith(self._DIR_TEST_SUFFIX)
        ):
            return 0
        probed = command[len(self._DIR_TEST_PREFIX) : -len(self._DIR_TEST_SUFFIX)]
        return 0 if probed in self._dirs else 1


def test_push_file_writes_dpath_itself_when_it_is_not_a_directory(tmp_path):
    lpath = tmp_path / "src.bin"
    lpath.write_bytes(b"payload")
    adb = _PushFileSpyAdb()
    Shell(adb, user="shell", su=Su()).push_file("/data/local/tmp/dst.bin", str(lpath))
    assert "cat >/data/local/tmp/dst.bin" in adb.commands
    assert "cat >/data/local/tmp/dst.bin/src.bin" not in adb.commands


def test_push_file_lands_under_the_local_basename_when_dpath_is_a_directory(tmp_path):
    """A directory target names where the file goes, not what it is called:
    the local basename completes it, the way cp and adb push do."""
    lpath = tmp_path / "src.bin"
    lpath.write_bytes(b"payload")
    adb = _PushFileSpyAdb(dirs=("/data/local/tmp",))
    Shell(adb, user="shell", su=Su()).push_file("/data/local/tmp", str(lpath))
    assert "cat >/data/local/tmp/src.bin" in adb.commands


def test_push_file_resolves_a_directory_target_with_a_trailing_slash(tmp_path):
    """`gk push src.bin /data/local/tmp/` must not double the separator."""
    lpath = tmp_path / "src.bin"
    lpath.write_bytes(b"payload")
    adb = _PushFileSpyAdb(dirs=("/data/local/tmp/",))
    Shell(adb, user="shell", su=Su()).push_file("/data/local/tmp/", str(lpath))
    assert "cat >/data/local/tmp/src.bin" in adb.commands


def test_push_file_inherits_owner_of_the_resolved_path_not_the_directory(tmp_path):
    """The chown must follow the file that was actually written; aimed at the
    directory target instead it would recursively chown the whole directory."""
    lpath = tmp_path / "src.bin"
    lpath.write_bytes(b"payload")
    adb = _PushFileSpyAdb(dirs=("/data/local/tmp",))
    Shell(adb, user="shell", su=Su()).push_file("/data/local/tmp", str(lpath))
    chown = adb.commands[-1]
    assert chown.startswith("chown ")
    assert chown.endswith(" /data/local/tmp/src.bin")


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
    with Shell(adb, user="root", su=Su()).stream("logcat"):
        pass
    assert adb.calls == [["shell", "su root sh -c logcat"]]


def test_execvp_sh_attaches_an_interactive_su_shell(monkeypatch):
    calls = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    Shell(_SpyAdb(), user="root", su=Su()).execvp_sh()
    assert calls == [
        ("adb", ["adb", "-s", "fake-serial", "shell", "-t", "su root sh -c 'exec sh'"])
    ]


def test_execvp_sh_runs_a_command_instead_of_attaching_when_given_one(monkeypatch):
    """A command execs adb exactly as an interactive attach does, rather than
    being captured and echoed once it finishes: a captured command shows
    nothing until it exits, so one that never exits or draws a UI shows
    nothing at all."""
    calls = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    Shell(_SpyAdb(), user="root", su=Su()).execvp_sh(command="top")
    assert calls == [("adb", ["adb", "-s", "fake-serial", "shell", "-t", "su root sh -c top"])]


def test_execvp_sh_omits_the_pty_flag_when_no_pty_was_asked_for(monkeypatch):
    """Without a pty adb keeps stdout and stderr apart and translates no
    newlines, which is what a caller redirecting either stream needs."""
    calls = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    Shell(_SpyAdb(), user="root", su=Su()).execvp_sh(command="cat /f.bin", pty=False)
    assert calls == [
        ("adb", ["adb", "-s", "fake-serial", "shell", "su root sh -c 'cat /f.bin'"])
    ]


def test_execvp_sh_changes_directory_before_the_command(monkeypatch):
    calls = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    Shell(_SpyAdb(), user="root", su=Su()).execvp_sh(command="ls", directory="/data/local/tmp")
    assert calls == [
        (
            "adb",
            [
                "adb",
                "-s",
                "fake-serial",
                "shell",
                "-t",
                "su root sh -c 'cd /data/local/tmp && ls'",
            ],
        )
    ]


def test_execvp_sh_changes_directory_first(monkeypatch):
    calls = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    Shell(_SpyAdb(), user="root", su=Su()).execvp_sh(directory="/data/local/tmp")
    assert calls == [
        (
            "adb",
            [
                "adb",
                "-s",
                "fake-serial",
                "shell",
                "-t",
                "su root sh -c 'cd /data/local/tmp && exec sh'",
            ],
        )
    ]


def _write_tar(path: str, members: list[tuple[str, bytes | None]]) -> None:
    """Write a real tar file at path; data=None for a directory member."""
    with tarfile.open(path, mode="w") as tar:
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


class _PullSpyAdb:
    """Answers pull's file/directory/missing probe from a canned kind, then
    `cat <dpath>` by writing canned content to the stdout fd -- reuses
    _PushFileSpyAdb's trick of deciding the answer from whether the call
    carries a stdout fd, since capture_output=True never does.
    """

    def __init__(self, content: bytes = b"", returncode: int = 0, kind: str = "f"):
        self.serial = "fake-serial"
        self._content = content
        self._returncode = returncode
        self._kind = kind

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        if "stdout" not in kwargs:
            return subprocess.CompletedProcess(args, 0, self._kind.encode(), b"")
        kwargs["stdout"].write(self._content)
        return subprocess.CompletedProcess(args, self._returncode, b"", b"")

    def popen(self, args, **kwargs):
        raise AssertionError("a plain file pull must not reach tar")


class _TarStreamAdb:
    """popen spawns a real local process, so the pipe, the stderr temp file,
    tarfile's own streaming parse, reaping, and rc mapping are all exercised
    for real rather than assumed.

    script is a plain `sh -c` script deciding what bytes and exit status the
    "device" produces; it does not need to relate to the command Shell built
    -- that command is inspected separately, via calls.
    """

    def __init__(self, script: str):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self.process: subprocess.Popen | None = None
        self._script = script

    def popen(self, args, **kwargs) -> subprocess.Popen:
        self.calls.append(args)
        self.process = subprocess.Popen(["sh", "-c", self._script], **kwargs)
        return self.process

    def __call__(self, *args, **kwargs):
        raise AssertionError("a wildcard pull must not probe the device with sh()")


# --- pull: command construction ---------------------------------------------


def test_pull_tree_builds_the_verbatim_shape_for_a_glob(tmp_path):
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError):
        Shell(adb, user="shell", su=Su()).pull_tree("/data/data/com.foo/*.db", str(tmp_path))
    assert adb.calls == [
        [
            "shell",
            'cd /data/data/com.foo && { set -- ./*.db; [ -e "$1" ] || [ -h "$1" ] '
            '|| exit 90; tar -cf - "$@"; }',
        ]
    ]


def test_pull_tree_builds_the_same_shape_for_a_directory(tmp_path):
    """The glob and directory cases must never fork into two command shapes."""
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError):
        Shell(adb, user="shell", su=Su()).pull_tree("/data/local/tmp/adir", str(tmp_path))
    assert adb.calls == [
        [
            "shell",
            'cd /data/local/tmp && { set -- ./adir; [ -e "$1" ] || [ -h "$1" ] '
            '|| exit 90; tar -cf - "$@"; }',
        ]
    ]


def test_pull_tree_is_su_wrapped_exactly_as_sh_and_stream_are(tmp_path):
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError):
        Shell(adb, user="root", su=Su()).pull_tree("/data/local/tmp/adir", str(tmp_path))
    assert adb.calls == [
        [
            "shell",
            "su root sh -c 'cd /data/local/tmp && { set -- ./adir; "
            '[ -e "$1" ] || [ -h "$1" ] || exit 90; tar -cf - "$@"; }\'',
        ]
    ]


def test_tar_stream_command_template_has_no_single_quote():
    """Su.wrap's template wraps the command in single quotes with no escaping
    of its own; a single quote inside this command would break out of it."""
    assert "'" not in Shell._TAR_STREAM_COMMAND


def test_pull_of_a_glob_never_probes_the_device_first(tmp_path):
    """Decided from syntax alone -- _TarStreamAdb raises if sh() is ever called."""
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError):
        Shell(adb, user="shell", su=Su()).pull("/data/local/tmp/*.db", str(tmp_path))


def test_pull_of_a_plain_file_never_reaches_tar(tmp_path):
    """_PullSpyAdb.popen raises if pull ever reaches tar for a plain file."""
    adb = _PullSpyAdb(content=b"payload")
    Shell(adb, user="shell", su=Su()).pull(
        "/data/local/tmp/f.bin", str(tmp_path / "f.bin")
    )


# --- pull: device-path refusals ---------------------------------------------


@pytest.mark.parametrize(
    "bad_char", ["'", '"', "`", "$", ";", " ", "\\", "\n", "&", "|", "<", ">"]
)
def test_pull_refuses_a_shell_metacharacter(bad_char):
    adb = _SpyAdb()
    with pytest.raises(ValueError, match="unsafe device path"):
        Shell(adb, user="root", su=Su()).pull(f"/data/local/tmp/x{bad_char}y")
    assert adb.calls == []


def test_pull_refuses_a_device_path_ending_in_a_newline():
    """The metacharacter case above puts its newline mid-path, which any
    anchored pattern rejects. A *trailing* newline is the one that slips
    through `match`, since Python's `$` matches just before it -- so this
    pins the `fullmatch` in _check_device_path, not the character class."""
    adb = _SpyAdb()
    with pytest.raises(ValueError, match="unsafe device path"):
        Shell(adb, user="root", su=Su()).pull("/data/local/tmp/x\n")
    assert adb.calls == []


def test_pull_tree_normalizes_a_trailing_slash_to_the_same_command(tmp_path):
    """`gk pull /data/local/tmp/adir/` must pull adir, not refuse for having
    no basename: PurePosixPath normalizes the trailing slash away."""
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError):
        Shell(adb, user="shell", su=Su()).pull_tree("/data/local/tmp/adir/", str(tmp_path))
    assert adb.calls == [
        [
            "shell",
            'cd /data/local/tmp && { set -- ./adir; [ -e "$1" ] || [ -h "$1" ] '
            '|| exit 90; tar -cf - "$@"; }',
        ]
    ]


def test_pull_refuses_a_wildcard_outside_the_last_component():
    """`cd /d*` with several matches errors, but silently succeeds with
    exactly one -- so behavior would depend on how many packages exist."""
    adb = _SpyAdb()
    with pytest.raises(ValueError, match="wildcard outside the last component"):
        Shell(adb, user="root", su=Su()).pull("/data/data/*/databases/x.db")
    assert adb.calls == []


def test_pull_refuses_root_for_having_no_basename():
    adb = _SpyAdb()
    with pytest.raises(ValueError, match="no basename"):
        Shell(adb, user="root", su=Su()).pull("/")
    assert adb.calls == []


def test_pull_refuses_a_relative_path():
    adb = _SpyAdb()
    with pytest.raises(ValueError, match="not absolute"):
        Shell(adb, user="root", su=Su()).pull("data/local/tmp/f")
    assert adb.calls == []


def test_pull_refuses_an_unsafe_path_via_pull_tree_directly(tmp_path):
    """pull_tree is public and reachable without going through pull's own
    validation -- it must guard its own input rather than trust a caller
    that validated already, since it interpolates dpath unescaped."""
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(ValueError, match="unsafe device path"):
        Shell(adb, user="root", su=Su()).pull_tree(
            "/data/local/tmp/x'; id; echo '", str(tmp_path)
        )
    assert adb.calls == []
    assert adb.process is None


@pytest.mark.parametrize(
    "safe_path",
    [
        "/data/app/~~5Hqa==/pkg-1==/base.apk",
        "/x/[ab]?.db",
        "/data/local/tmp/héllo",
    ],
)
def test_pull_accepts_paths_a_tighter_regex_would_have_refused(safe_path):
    """Guards against an over-tight character class: these are real shapes
    (an APK path with ~~ and == segments, a bracket glob, a non-ASCII name)
    that a first-attempt whitelist would wrongly reject."""
    Shell(_SpyAdb(), user="root", su=Su())._check_device_path(safe_path)


# --- pull: streaming and rc mapping ------------------------------------------


def test_pull_tree_lands_a_directory_under_its_own_basename(tmp_path):
    """lpath must not become the tree; the tree lands as a child of it."""
    archive = tmp_path / "archive.tar"
    _write_tar(str(archive), [("./sec", None), ("./sec/a.txt", b"hello")])
    ldir = tmp_path / "out"
    ldir.mkdir()
    adb = _TarStreamAdb(f"cat {archive}")
    result = Shell(adb, user="shell", su=Su()).pull_tree(
        "/system/etc/sec", str(ldir)
    )
    assert result.paths[0] == str(ldir / "sec")
    assert (ldir / "sec" / "a.txt").read_bytes() == b"hello"
    assert not (ldir / "a.txt").exists()


def test_pull_tree_merges_into_a_tree_that_is_already_there(tmp_path):
    """A repeat pull overwrites what it re-lands and leaves everything else,
    matching adb pull -- so a local tree is NOT a faithful snapshot of the
    device's once a file has been deleted there. A survivor is also absent history-ok
    from the result, which reports what this pull landed, not what the
    directory happens to contain.
    """
    archive = tmp_path / "archive.tar"
    _write_tar(str(archive), [("./sec", None), ("./sec/a.txt", b"new")])
    ldir = tmp_path / "out"
    ldir.mkdir()
    landed = ldir / "sec"
    landed.mkdir()
    (landed / "a.txt").write_bytes(b"stale")
    (landed / "deleted_on_device.txt").write_bytes(b"survivor")
    adb = _TarStreamAdb(f"cat {archive}")
    result = Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    assert (landed / "a.txt").read_bytes() == b"new"
    assert (landed / "deleted_on_device.txt").read_bytes() == b"survivor"
    assert str(landed / "deleted_on_device.txt") not in result.paths


def test_pull_tree_refuses_a_destination_that_does_not_exist(tmp_path):
    """A mistyped destination must be a refusal, not a mkdir: creating it would
    report success and leave the tree somewhere nobody looks. Nothing is
    spawned, so the refusal costs no device round trip either."""
    ldir = tmp_path / "does" / "not" / "exist"
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError, match="local destination directory"):
        Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    assert adb.calls == []
    assert not ldir.exists()


def test_pull_tree_refuses_a_local_file_where_the_directory_must_be(tmp_path):
    ldir = tmp_path / "notadir"
    ldir.write_bytes(b"x")
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(NotADirectoryError):
        Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    assert adb.calls == []


def test_pull_of_a_glob_lands_every_match_flat(tmp_path):
    archive = tmp_path / "archive.tar"
    _write_tar(str(archive), [("./a.db", b"aaa"), ("./b.db", b"bbb")])
    ldir = tmp_path / "out"
    ldir.mkdir()
    adb = _TarStreamAdb(f"cat {archive}")
    result = Shell(adb, user="shell", su=Su()).pull(
        "/data/data/com.foo/*.db", str(ldir)
    )
    assert sorted(result.paths) == sorted(
        [str(ldir / "a.db"), str(ldir / "b.db")]
    )
    assert (ldir / "a.db").read_bytes() == b"aaa"
    assert (ldir / "b.db").read_bytes() == b"bbb"


def test_pull_tree_rc_90_raises_file_not_found_never_the_read_error(tmp_path):
    adb = _TarStreamAdb("exit 90")
    with pytest.raises(FileNotFoundError):
        Shell(adb, user="shell", su=Su()).pull_tree(
            "/data/data/com.foo/*.db", str(tmp_path)
        )


def test_pull_tree_rc_2_reports_the_devices_own_message(tmp_path):
    """A missing parent directory's cd failure must not be lost behind the
    broken-stream ReadError it also causes."""
    adb = _TarStreamAdb('echo "sh: cd: No such file or directory" >&2; exit 2')
    with pytest.raises(ShellError) as raised:
        Shell(adb, user="shell", su=Su()).pull_tree(
            "/no/such/dir/*.db", str(tmp_path)
        )
    assert raised.value.rc == 2
    assert "No such file or directory" in raised.value.stderr


def test_pull_tree_rc_0_with_garbage_reraises_the_read_error(tmp_path):
    adb = _TarStreamAdb(
        'printf "garbage, not a tar header at all, 1234567890abcdefgh"; exit 0'
    )
    with pytest.raises(tarfile.ReadError):
        Shell(adb, user="shell", su=Su()).pull_tree(
            "/data/data/com.foo/*.db", str(tmp_path)
        )


def test_pull_tree_rc_1_with_a_complete_archive_keeps_what_landed(tmp_path, caplog):
    """Pins the toybox tar wart as intended behavior: a valid, complete
    archive can still end in rc 1 (it silently refuses a socket), and what
    already landed must survive rather than being discarded."""
    archive = tmp_path / "archive.tar"
    _write_tar(str(archive), [("./sec", None), ("./sec/a.txt", b"hello")])
    ldir = tmp_path / "out"
    ldir.mkdir()
    adb = _TarStreamAdb(f"cat {archive}; exit 1")
    with caplog.at_level("WARNING"), pytest.raises(ShellError) as raised:
        Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    assert raised.value.rc == 1
    assert (ldir / "sec" / "a.txt").read_bytes() == b"hello"
    assert str(ldir / "sec") in caplog.text


def test_pull_tree_skips_and_names_a_refused_member(tmp_path):
    archive = tmp_path / "archive.tar"
    with tarfile.open(str(archive), mode="w") as tar:
        info = tarfile.TarInfo("./sec")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tar.addfile(info)
        link = tarfile.TarInfo("./sec/lib")
        link.type = tarfile.SYMTYPE
        link.linkname = "/data/app/pkg/lib/arm64"
        tar.addfile(link)
    ldir = tmp_path / "out"
    ldir.mkdir()
    adb = _TarStreamAdb(f"cat {archive}")
    result = Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    assert result.skipped == ["./sec/lib"]
    assert not (ldir / "sec" / "lib").exists()


def test_pull_tree_an_escaping_member_lands_nothing_outside_ldir(tmp_path):
    archive = tmp_path / "archive.tar"
    _write_tar(str(archive), [("../escape.txt", b"malicious")])
    ldir = tmp_path / "out"
    ldir.mkdir()
    adb = _TarStreamAdb(f"cat {archive}")
    result = Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    assert result.paths == []
    assert not (tmp_path / "escape.txt").exists()


def test_pull_tree_reaps_the_process_on_the_success_path(tmp_path):
    archive = tmp_path / "archive.tar"
    _write_tar(str(archive), [("./sec", None)])
    adb = _TarStreamAdb(f"cat {archive}")
    Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(tmp_path))
    assert adb.process.poll() is not None


def test_pull_tree_reaps_the_process_on_the_read_error_path(tmp_path):
    adb = _TarStreamAdb('printf "garbage garbage garbage garbage 1234567890"; exit 0')
    with pytest.raises(tarfile.ReadError):
        Shell(adb, user="shell", su=Su()).pull_tree(
            "/data/data/com.foo/*.db", str(tmp_path)
        )
    assert adb.process.poll() is not None


def test_pull_tree_paths_matches_a_real_walk_of_the_destination(tmp_path):
    archive = tmp_path / "archive.tar"
    _write_tar(
        str(archive),
        [("./sec", None), ("./sec/a.txt", b"1"), ("./sec/sub", None), ("./sec/sub/b.txt", b"2")],
    )
    ldir = tmp_path / "out"
    ldir.mkdir()
    adb = _TarStreamAdb(f"cat {archive}")
    result = Shell(adb, user="shell", su=Su()).pull_tree("/system/etc/sec", str(ldir))
    walked = {
        os.path.join(root, name)
        for root, dirs, files in os.walk(ldir)
        for name in dirs + files
    }
    assert set(result.paths) == walked


def test_pull_of_a_plain_file_refuses_a_destination_directory_that_does_not_exist(
    tmp_path,
):
    """The file case must refuse a missing destination the same way the tree
    case does, and name the directory rather than leaking pull_file's internal
    .gk-part spool path from a bare OSError."""
    adb = _PullSpyAdb(content=b"payload")
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError, match="local destination directory"):
        Shell(adb, user="shell", su=Su()).pull(
            "/data/local/tmp/f.bin", str(missing / "f.bin")
        )
    assert not missing.exists()


def test_pull_lands_a_plain_file_under_the_remote_basename_in_an_existing_local_dir(
    tmp_path,
):
    adb = _PullSpyAdb(content=b"payload")
    result = Shell(adb, user="shell", su=Su()).pull(
        "/data/local/tmp/f.bin", str(tmp_path)
    )
    assert result == PullResult(paths=[str(tmp_path / "f.bin")], skipped=[])
    assert (tmp_path / "f.bin").read_bytes() == b"payload"


def test_pull_destination_defaults_to_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    adb = _PullSpyAdb(content=b"payload")
    result = Shell(adb, user="shell", su=Su()).pull("/data/local/tmp/f.bin")
    assert result.paths == [str(tmp_path / "f.bin")]
    assert (tmp_path / "f.bin").read_bytes() == b"payload"


def test_execvp_sh_escapes_a_directory_containing_a_single_quote(monkeypatch):
    """A directory containing its own single quote (an unusual but valid
    path) must survive intact rather than colliding with the quoting this
    method wraps around it."""
    calls = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    directory = "/sdcard/O'Brien"
    Shell(_SpyAdb(), user="root", su=Su()).execvp_sh(directory=directory)
    inner = f"cd {shlex.quote(directory)} && exec sh"
    expected = f"su root sh -c {shlex.quote(inner)}"
    assert calls == [
        ("adb", ["adb", "-s", "fake-serial", "shell", "-t", expected])
    ]


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
        shell.chown(remote_path, "shell", "shell")
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


@pytest.mark.emulator
def test_pull_tree_round_trip_against_real_device(device, tmp_path):
    """A directory pull must land as ldir/<basename>, preserving layout and
    bytes, and ldir itself must never become the tree."""
    shell = device.shell()
    remote_root = "/data/local/tmp/gunkata_test_tree"
    try:
        shell.check_sh(f"mkdir -p {remote_root}/sub")
        shell.write_file(f"{remote_root}/a.txt", b"top level")
        shell.write_file(f"{remote_root}/sub/b.txt", b"nested")
        ldir = tmp_path / "out"
        ldir.mkdir()
        result = shell.pull(remote_root, str(ldir))
        landed = ldir / "gunkata_test_tree"
        assert result.paths[0] == str(landed)
        assert not (ldir / "a.txt").exists()
        assert (landed / "a.txt").read_bytes() == b"top level"
        assert (landed / "sub" / "b.txt").read_bytes() == b"nested"
    finally:
        shell(f"rm -rf {remote_root}")


@pytest.mark.emulator
def test_pull_tree_carries_all_256_byte_values_through_the_tar_stream(device, tmp_path):
    """Pins the riskiest assumption in the design: tar over adb shell is
    binary-clean end to end, not only plain `cat` as pull_file already relies on."""
    shell = device.shell()
    remote_root = "/data/local/tmp/gunkata_test_bytes"
    payload = bytes(range(256))
    try:
        shell.check_sh(f"mkdir -p {remote_root}")
        shell.write_file(f"{remote_root}/all_bytes.bin", payload)
        ldir = tmp_path / "out"
        ldir.mkdir()
        shell.pull(remote_root, str(ldir))
        landed = ldir / "gunkata_test_bytes" / "all_bytes.bin"
        assert landed.read_bytes() == payload
    finally:
        shell(f"rm -rf {remote_root}")


@pytest.mark.emulator
def test_pull_wildcard_lands_only_its_matches_flat_against_real_device(device, tmp_path):
    shell = device.shell()
    remote_root = "/data/local/tmp/gunkata_test_glob"
    try:
        shell.check_sh(f"mkdir -p {remote_root}")
        shell.write_file(f"{remote_root}/keep_a.db", b"a")
        shell.write_file(f"{remote_root}/keep_b.db", b"b")
        shell.write_file(f"{remote_root}/skip.txt", b"nope")
        ldir = tmp_path / "out"
        ldir.mkdir()
        shell.pull(f"{remote_root}/keep_*.db", str(ldir))
        assert sorted(os.listdir(ldir)) == ["keep_a.db", "keep_b.db"]
        assert (ldir / "keep_a.db").read_bytes() == b"a"
        assert (ldir / "keep_b.db").read_bytes() == b"b"
    finally:
        shell(f"rm -rf {remote_root}")


@pytest.mark.emulator
def test_pull_glob_matching_nothing_raises_file_not_found_against_real_device(
    device, tmp_path
):
    """Creates no device state: the pattern is chosen to match nothing under
    an already-existing directory."""
    shell = device.shell()
    with pytest.raises(FileNotFoundError):
        shell.pull(
            "/data/local/tmp/gunkata_test_never_created_*.bin", str(tmp_path)
        )


@pytest.mark.emulator
def test_pull_tree_of_a_missing_parent_reports_the_devices_own_message(device, tmp_path):
    """Creates no device state: cd fails before tar ever runs."""
    shell = device.shell()
    with pytest.raises(ShellError) as raised:
        shell.pull_tree(
            "/data/local/tmp/gunkata_test_missing_parent_xyz/sub", str(tmp_path)
        )
    assert raised.value.rc > 0
    assert raised.value.stderr


@pytest.mark.emulator
def test_pull_tree_symlink_skips_it_loudly_against_real_device(device, tmp_path, caplog):
    shell = device.shell()
    remote_root = "/data/local/tmp/gunkata_test_symlink"
    try:
        shell.check_sh(
            f"mkdir -p {remote_root} && ln -s /system/bin/toybox {remote_root}/link"
        )
        ldir = tmp_path / "out"
        ldir.mkdir()
        with caplog.at_level("WARNING"):
            result = shell.pull(remote_root, str(ldir))
        assert any("link" in name for name in result.skipped)
        assert not (ldir / "gunkata_test_symlink" / "link").exists()
        assert "link" in caplog.text
    finally:
        shell(f"rm -rf {remote_root}")


@pytest.mark.emulator
def test_pull_proc_self_stat_glob_lands_empty_files_against_real_device(device, tmp_path):
    """Pins the pseudo-file trap as known truth: tar takes each member's
    length from its stat size, and /proc reports 0 for these, so the pull
    that works via `cat` (test_read_write_file_round_trip_against_real_device
    style /proc reads) lands empty files here instead. Creates no device
    state: /proc/self is virtual."""
    shell = device.shell()
    result = shell.pull("/proc/self/stat*", str(tmp_path))
    assert result.paths
    for path in result.paths:
        assert os.path.getsize(path) == 0
