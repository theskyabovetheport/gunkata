import io
import subprocess

import pytest
import typer
from typer.testing import CliRunner

from gunkata import main
from gunkata.ps import ProcessEntry


@pytest.fixture(autouse=True)
def _isolated_completion_cache(tmp_path, monkeypatch):
    """Point the completion cache at a per-test file so tests never share state
    with each other or with the real cache used by actual shell completion."""
    monkeypatch.setattr(main, "_completion_cache_path", lambda: tmp_path / "cache.json")


_ADDR_MAPS = "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so\n"

_ADDR_MAPS_WIDE = (
    "1000-2000 r--p 00000000 00:00 0 seg1\n"
    "2000-3000 r--p 00000000 00:00 0 seg2\n"
    "3000-4000 r--p 00000000 00:00 0 seg3\n"
    "4000-5000 r--p 00000000 00:00 0 seg4\n"
    "5000-6000 r--p 00000000 00:00 0 seg5\n"
)


def test_addr_annotates_the_piped_listing_with_the_located_address():
    result = CliRunner().invoke(main.app, ["addr", "0x7f0000+0x10"], input=_ADDR_MAPS)
    assert result.exit_code == 0
    assert result.output == (
        "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so  // contained +0x10 -0xff0\n"
    )


def test_addr_supports_minus_terms_in_the_address_expression():
    result = CliRunner().invoke(main.app, ["addr", "0x7f0020-0x10"], input=_ADDR_MAPS)
    assert result.exit_code == 0
    assert "contained +0x10 -0xff0" in result.output


def test_addr_defaults_to_three_lines_of_context_on_each_side():
    result = CliRunner().invoke(main.app, ["addr", "0x3000"], input=_ADDR_MAPS_WIDE)
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "1000-2000 r--p 00000000 00:00 0 seg1",
        "2000-3000 r--p 00000000 00:00 0 seg2",
        "3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000",
        "4000-5000 r--p 00000000 00:00 0 seg4",
        "5000-6000 r--p 00000000 00:00 0 seg5",
    ]


def test_addr_a_and_b_narrow_the_context_window():
    result = CliRunner().invoke(
        main.app, ["addr", "0x3000", "-A", "0", "-B", "1"], input=_ADDR_MAPS_WIDE
    )
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "2000-3000 r--p 00000000 00:00 0 seg2",
        "3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000",
    ]


def test_addr_requires_the_address_argument():
    result = CliRunner().invoke(main.app, ["addr"], input=_ADDR_MAPS)
    assert result.exit_code == 2


def test_addr_rejects_an_unparseable_address():
    result = CliRunner().invoke(main.app, ["addr", "not-hex"], input=_ADDR_MAPS)
    assert result.exit_code == 2


def test_addr_rejects_a_malformed_maps_line():
    result = CliRunner().invoke(main.app, ["addr", "0x7f0000"], input="not a maps line\n")
    assert result.exit_code == 1


def test_addr_errors_when_stdin_is_a_tty(monkeypatch):
    monkeypatch.setattr(main, "_stdin_is_tty", lambda: True)
    result = CliRunner().invoke(main.app, ["addr", "0x7f0000"], input=_ADDR_MAPS)
    assert result.exit_code == 1
    assert "pipe" in result.output


class _FakeAdb:
    """Stands in for Adb: answers `command -v su` and `ls -1p` canned, counts real device calls.

    Returns bytes for stdout/stderr, matching real Adb (no text=True).
    """

    def __init__(self, ls_output: str, ls_ok: bool = True):
        self.serial = "fake-serial"
        self._ls_output = ls_output
        self._ls_ok = ls_ok
        self.su_check_calls = 0
        self.ls_calls = 0

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            self.su_check_calls += 1
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        self.ls_calls += 1
        returncode = 0 if self._ls_ok else 1
        return subprocess.CompletedProcess(
            args, returncode, self._ls_output.encode(), b""
        )


class _BrokenAdb:
    def __init__(self, *a, **k):
        raise RuntimeError("no adb device connected")


class _ShellFakeAdb:
    """Answers `command -v su` canned; any other command returns a fixed result."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        return subprocess.CompletedProcess(
            args, self._returncode, self._stdout, self._stderr
        )


class _ProcmapsFakeAdb:
    """Answers `command -v su`, `pidof <name>`, `ps -A`, and `cat /proc/<pid>/maps` canned."""

    def __init__(
        self,
        pidof_output: str = "",
        maps: bytes = b"",
        maps_ok: bool = True,
        ps_output: str = "",
    ):
        self.serial = "fake-serial"
        self._pidof_output = pidof_output
        self._maps = maps
        self._maps_ok = maps_ok
        self._ps_output = ps_output

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        if "pidof" in command:
            return subprocess.CompletedProcess(
                args, 0, self._pidof_output.encode(), b""
            )
        if "ps -A" in command:
            return subprocess.CompletedProcess(args, 0, self._ps_output.encode(), b"")
        if "cat /proc" in command:
            if self._maps_ok:
                return subprocess.CompletedProcess(args, 0, self._maps, b"")
            return subprocess.CompletedProcess(
                args, 1, b"", b"No such file or directory\n"
            )
        raise AssertionError(f"unexpected command: {command!r}")


def test_procmaps_prints_maps_for_given_pid(monkeypatch):
    fake = _ProcmapsFakeAdb(maps=b"7f0000-7f1000 r-xp 0 00:00 0 /lib/libc.so\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["procmaps", "-p", "1234"])
    assert result.exit_code == 0
    assert "libc.so" in result.output


def test_procmaps_resolves_pid_by_name(monkeypatch):
    """`-P name` must resolve to the sole matching pid before reading its maps."""
    fake = _ProcmapsFakeAdb(pidof_output="1234\n", maps=b"deadbeef\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["procmaps", "-P", "com.example.app"])
    assert result.exit_code == 0
    assert "deadbeef" in result.output


def test_procmaps_rejects_both_p_and_capital_p():
    result = CliRunner().invoke(
        main.app, ["procmaps", "-p", "1234", "-P", "com.example.app"]
    )
    assert result.exit_code == 2


def test_procmaps_errors_when_name_matches_multiple_processes(monkeypatch):
    """Wiring guard: ProcMaps.AmbiguousProcessError must map to CLI exit 1, not propagate."""
    fake = _ProcmapsFakeAdb(pidof_output="1234 5678\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["procmaps", "-P", "com.example.app"])
    assert result.exit_code == 1


def test_procmaps_errors_when_pid_has_no_proc_entry(monkeypatch):
    fake = _ProcmapsFakeAdb(maps_ok=False)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["procmaps", "-p", "9999"])
    assert result.exit_code == 1


_FZF_ENTRIES = [
    ProcessEntry(pid=1234, name="com.example.app"),
    ProcessEntry(pid=5678, name="com.example.other"),
]


def test_fzf_pick_pid_returns_the_picked_pid(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, "1234\tcom.example.app\n", ""
        ),
    )
    assert main._fzf_pick_pid(_FZF_ENTRIES) == 1234


def test_fzf_pick_pid_returns_none_when_the_user_exits_without_picking(monkeypatch):
    """Esc/Ctrl-C in fzf exits non-zero with empty stdout; that must not raise."""
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 130, "", ""),
    )
    assert main._fzf_pick_pid(_FZF_ENTRIES) is None


def test_fzf_pick_pid_exits_with_an_install_hint_when_fzf_is_missing(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    with pytest.raises(typer.Exit) as raised:
        main._fzf_pick_pid(_FZF_ENTRIES)
    assert raised.value.exit_code == 1


def test_procmaps_with_no_flags_launches_fzf_and_reads_the_picked_pid(monkeypatch):
    fake = _ProcmapsFakeAdb(
        maps=b"deadbeef\n",
        ps_output="USER  PID  PPID S NAME\nu0_a1 1234 567  S com.example.app\n",
    )
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(main, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "1234\tcom.example.app\n", ""),
    )
    result = CliRunner().invoke(main.app, ["procmaps"])
    assert result.exit_code == 0
    assert "deadbeef" in result.output


def test_procmaps_with_no_flags_exits_when_fzf_is_missing(monkeypatch):
    fake = _ProcmapsFakeAdb()
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(main, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    result = CliRunner().invoke(main.app, ["procmaps"])
    assert result.exit_code == 1
    assert "fzf" in result.output


def test_procmaps_with_no_flags_refuses_to_fuzzy_pick_when_stdout_is_not_a_tty(
    monkeypatch,
):
    """Piped/redirected stdout must never trigger fzf; -p/-P are the only way in."""
    fake = _ProcmapsFakeAdb()
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(main, "_stdout_is_tty", lambda: False)
    result = CliRunner().invoke(main.app, ["procmaps"])
    assert result.exit_code == 2
    assert "tty" in result.output


def test_pidof_prints_every_pid_matching_the_given_name(monkeypatch):
    fake = _ProcmapsFakeAdb(pidof_output="1234 5678\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["pidof", "com.example.app"])
    assert result.exit_code == 0
    assert result.output.splitlines() == ["1234", "5678"]


def test_pidof_errors_when_name_matches_no_process(monkeypatch):
    fake = _ProcmapsFakeAdb(pidof_output="")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["pidof", "no.such.app"])
    assert result.exit_code == 1


def test_pidof_launches_fzf_and_prints_the_picked_pid(monkeypatch):
    fake = _ProcmapsFakeAdb(
        ps_output="USER  PID  PPID S NAME\nu0_a1 1234 567  S com.example.app\n",
    )
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "1234\tcom.example.app\n", ""),
    )
    result = CliRunner().invoke(main.app, ["pidof"])
    assert result.exit_code == 0
    assert result.output.strip() == "1234"


def test_pidof_exits_when_fzf_is_missing(monkeypatch):
    fake = _ProcmapsFakeAdb()
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    result = CliRunner().invoke(main.app, ["pidof"])
    assert result.exit_code == 1
    assert "fzf" in result.output


def test_shell_command_runs_a_one_shot_command_and_exits_with_its_rc(monkeypatch):
    """A regression guard: `gunkata shell <cmd>` must run <cmd> and exit, not attach interactively."""
    fake = _ShellFakeAdb(stdout=b"hello\n", returncode=0)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["shell", "echo", "hello"])
    assert result.exit_code == 0
    assert "hello" in result.output


def test_shell_command_returns_the_remote_commands_exit_status(monkeypatch):
    fake = _ShellFakeAdb(stderr=b"nope\n", returncode=3)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["shell", "false"])
    assert result.exit_code == 3


def test_shell_command_execs_into_an_interactive_shell_when_no_command_given(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _ShellFakeAdb())
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    result = CliRunner().invoke(main.app, ["shell"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "adb"


def test_completes_nested_path(monkeypatch):
    monkeypatch.setattr(
        main, "Adb", lambda *a, **k: _FakeAdb("tmp/\nfoo.txt\n")
    )
    results = main._complete_remote_path(None, [], "/data/local/")
    assert results == ["/data/local/tmp/", "/data/local/foo.txt"]


def test_completes_root_path(monkeypatch):
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _FakeAdb("data/\nsdcard/\n"))
    results = main._complete_remote_path(None, [], "/")
    assert results == ["/data/", "/sdcard/"]


def test_completes_relative_path(monkeypatch):
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _FakeAdb("a.txt\nb.txt\n"))
    results = main._complete_remote_path(None, [], "")
    assert results == ["a.txt", "b.txt"]


def test_returns_empty_on_ls_failure(monkeypatch):
    monkeypatch.setattr(
        main, "Adb", lambda *a, **k: _FakeAdb("", ls_ok=False)
    )
    assert main._complete_remote_path(None, [], "/no/such/dir") == []


def test_swallows_no_device_error(monkeypatch):
    """No device attached must never raise into the shell's completion prompt."""
    monkeypatch.setattr(main, "Adb", _BrokenAdb)
    assert main._complete_remote_path(None, [], "/data") == []


def test_second_call_for_same_dir_hits_cache_not_the_device(monkeypatch):
    """Retyping within the same directory must not re-run `command -v su` or `ls`."""
    fake = _FakeAdb("tmp/\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    first = main._complete_remote_path(None, [], "/data/local/t")
    second = main._complete_remote_path(None, [], "/data/local/tm")
    assert first == second == ["/data/local/tmp/"]
    assert fake.su_check_calls == 1
    assert fake.ls_calls == 1


@pytest.mark.emulator
def test_completes_against_real_device():
    """/data/local/tmp is a standard Android writable dir; must appear when completing its prefix."""
    results = main._complete_remote_path(None, [], "/data/local/tm")
    assert any(r.startswith("/data/local/tmp") for r in results)


class _PsFakeAdb:
    """Answers `command -v su` and `ps -A` canned; counts real `ps -A` calls."""

    def __init__(self, ps_output: str):
        self.serial = "fake-serial"
        self._ps_output = ps_output
        self.ps_calls = 0

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        self.ps_calls += 1
        return subprocess.CompletedProcess(args, 0, self._ps_output.encode(), b"")


_PS_OUTPUT = (
    "USER  PID  PPID VSZ RSS WCHAN ADDR S NAME\n"
    "u0_a1 1234 567  1   1   0     0    S com.example.app\n"
    "u0_a2 5678 567  1   1   0     0    S com.example.other\n"
)


def test_completes_process_name(monkeypatch):
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _PsFakeAdb(_PS_OUTPUT))
    assert main._complete_process_name(None, [], "com.example.a") == ["com.example.app"]


def test_process_name_completion_hits_cache_not_the_device(monkeypatch):
    """Retyping within the TTL must not re-run `ps -A`, matching the path completer's caching."""
    fake = _PsFakeAdb(_PS_OUTPUT)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    first = main._complete_process_name(None, [], "com.example.a")
    second = main._complete_process_name(None, [], "com.example.o")
    assert first == ["com.example.app"]
    assert second == ["com.example.other"]
    assert fake.ps_calls == 1


def test_ps_prints_aligned_columns_with_a_header_on_a_tty(monkeypatch, capsys):
    """A terminal reader gets a table; column width follows the widest pid, not a fixed guess."""
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _PsFakeAdb(_PS_OUTPUT))
    monkeypatch.setattr(main.sys.stdout, "isatty", lambda: True)
    main.ps()
    assert capsys.readouterr().out.splitlines() == [
        "PID   NAME",
        "1234  com.example.app",
        "5678  com.example.other",
    ]


def test_ps_prints_unaligned_pid_and_name_when_piped(monkeypatch, capsys):
    """A pipeline gets one space between pid and name -- no header, no column padding."""
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _PsFakeAdb(_PS_OUTPUT))
    monkeypatch.setattr(main.sys.stdout, "isatty", lambda: False)
    main.ps()
    assert capsys.readouterr().out.splitlines() == [
        "1234 com.example.app",
        "5678 com.example.other",
    ]


def test_parse_mem_address_expr_resolves_a_bare_hex_address():
    assert main._parse_mem_address_expr("7f0000") == 0x7F0000


def test_parse_mem_address_expr_accepts_an_optional_0x_prefix():
    assert main._parse_mem_address_expr("0x7f0000") == 0x7F0000


def test_parse_mem_address_expr_applies_a_single_offset():
    assert main._parse_mem_address_expr("0x1000+0x10") == 0x1010


def test_parse_mem_address_expr_chains_multiple_offsets_in_order():
    assert (
        main._parse_mem_address_expr("0x1000+0x100-0x10+0x1")
        == 0x1000 + 0x100 - 0x10 + 0x1
    )


def test_parse_mem_address_expr_rejects_an_empty_expression():
    with pytest.raises(typer.Exit):
        main._parse_mem_address_expr("")


def test_parse_mem_address_expr_rejects_a_non_hex_term():
    with pytest.raises(typer.Exit):
        main._parse_mem_address_expr("0x1000+zz")


class _MemFakeAdb:
    """Answers `command -v su`, `pidof`, the maps read_file wrapper, and `dd` canned."""

    def __init__(
        self,
        maps: bytes,
        dd_stdout: bytes = b"",
        dd_ok: bool = True,
        pidof_output: str = "",
    ):
        self.serial = "fake-serial"
        self._maps = maps
        self._dd_stdout = dd_stdout
        self._dd_ok = dd_ok
        self._pidof_output = pidof_output
        self.calls: list[list[str]] = []
        self.last_input: bytes | None = None

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        if "pidof" in command:
            return subprocess.CompletedProcess(
                args, 0, self._pidof_output.encode(), b""
            )
        if "maps" in command:
            return subprocess.CompletedProcess(args, 0, self._maps, b"")
        if "dd " in command:
            self.last_input = kwargs.get("input")
            returncode = 0 if self._dd_ok else 1
            return subprocess.CompletedProcess(args, returncode, self._dd_stdout, b"")
        raise AssertionError(f"unexpected command: {command!r}")


_MEM_MAPS = b"7f0000000000-7f0000010000 rw-p 00000000 00:00 0\n"


def test_mem_read_writes_raw_bytes_to_stdout_when_piped(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hello")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        main.app,
        ["mem", "read", "-s", "0x7f0000000000", "-e", "0x7f0000000005"],
        input="1234\n",
    )
    assert result.exit_code == 0
    assert result.output == "hello"


def test_mem_read_hexdumps_when_stdout_is_a_tty(monkeypatch, capsys):
    """CliRunner swaps sys.stdout for its own stream, defeating an isatty patch made
    beforehand (see test_ps_prints_aligned_columns_with_a_header_on_a_tty for the same
    reason main.ps() is called directly there); calling mem_read() directly sidesteps it."""
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hi")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(main.sys, "stdin", io.StringIO("1234\n"))
    monkeypatch.setattr(main.sys.stdout, "isatty", lambda: True)
    main.mem_read(
        start="0x7f0000000000", end="0x7f0000000002", pid=None, name=None, user=None
    )
    out = capsys.readouterr().out
    assert "68 69" in out
    assert "hi" in out


def test_mem_read_requires_exactly_one_pid_on_stdin():
    result = CliRunner().invoke(
        main.app, ["mem", "read", "-s", "0x1", "-e", "0x2"], input="1234\n5678\n"
    )
    assert result.exit_code == 1
    assert "expected exactly one pid" in result.output


def test_mem_read_rejects_a_non_numeric_pid():
    result = CliRunner().invoke(
        main.app, ["mem", "read", "-s", "0x1", "-e", "0x2"], input="notapid\n"
    )
    assert result.exit_code == 1


def test_mem_read_rejects_an_unparseable_address():
    result = CliRunner().invoke(
        main.app, ["mem", "read", "-s", "zz", "-e", "0x2"], input="1234\n"
    )
    assert result.exit_code == 2


def test_mem_read_with_p_uses_the_given_pid_without_touching_stdin(monkeypatch):
    """-p must skip stdin entirely, not merely take priority over it."""
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hello")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        main.app, ["mem", "read", "-s", "0x7f0000000000", "-e", "0x7f0000000005", "-p", "1234"]
    )
    assert result.exit_code == 0
    assert result.output == "hello"


def test_mem_read_with_capital_p_resolves_the_name_to_a_pid(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hello", pidof_output="1234\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        main.app,
        ["mem", "read", "-s", "0x7f0000000000", "-e", "0x7f0000000005", "-P", "com.example.app"],
    )
    assert result.exit_code == 0
    assert result.output == "hello"


def test_mem_read_rejects_both_p_and_capital_p():
    result = CliRunner().invoke(
        main.app,
        ["mem", "read", "-s", "0x1", "-e", "0x2", "-p", "1234", "-P", "com.example.app"],
    )
    assert result.exit_code == 2


def test_mem_read_with_capital_p_errors_when_name_matches_multiple_processes(
    monkeypatch,
):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="1234 5678\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        main.app,
        ["mem", "read", "-s", "0x1", "-e", "0x2", "-P", "com.example.app"],
    )
    assert result.exit_code == 1


def test_mem_read_with_capital_p_errors_when_name_matches_nothing(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        main.app,
        ["mem", "read", "-s", "0x1", "-e", "0x2", "-P", "no.such.app"],
    )
    assert result.exit_code == 1


def test_mem_read_reports_an_unmapped_range_loudly(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        main.app, ["mem", "read", "-s", "0x1", "-e", "0x10"], input="1234\n"
    )
    assert result.exit_code == 1
    assert "not fully mapped" in result.output


def test_mem_write_sends_the_files_bytes(monkeypatch, tmp_path):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    result = CliRunner().invoke(
        main.app,
        ["mem", "write", "-s", "0x7f0000000000", "-f", str(payload)],
        input="1234\n",
    )
    assert result.exit_code == 0
    assert fake.last_input == b"payload"


def test_mem_write_with_p_uses_the_given_pid_without_touching_stdin(monkeypatch, tmp_path):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"payload")
    result = CliRunner().invoke(
        main.app, ["mem", "write", "-s", "0x7f0000000000", "-f", str(payload), "-p", "1234"]
    )
    assert result.exit_code == 0
    assert fake.last_input == b"payload"


def test_mem_write_rejects_data_that_would_cross_the_given_end(monkeypatch, tmp_path):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"0123456789")
    result = CliRunner().invoke(
        main.app,
        [
            "mem",
            "write",
            "-s",
            "0x7f0000000000",
            "-e",
            "0x7f0000000005",
            "-f",
            str(payload),
        ],
        input="1234\n",
    )
    assert result.exit_code == 1


def test_mem_write_reports_an_unmapped_range_loudly(monkeypatch, tmp_path):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x")
    result = CliRunner().invoke(
        main.app, ["mem", "write", "-s", "0x1", "-f", str(payload)], input="1234\n"
    )
    assert result.exit_code == 1
    assert "not fully mapped" in result.output
