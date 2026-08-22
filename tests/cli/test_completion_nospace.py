"""Tests for the dir-aware Bash/Zsh completion patch in completion.py.

See that module's "dir-aware Bash/Zsh completion" section for why this
patch exists: typer's stock completers never act on complete_remote_path's
"dir"/"file" help marker, so a completed directory always gets a trailing
space, blocking a second Tab from continuing into it.
"""

import shutil
import subprocess
from collections import namedtuple

import pytest
from typer._click.shell_completion import get_completion_class
from typer._completion_classes import completion_init

from gunkata.cli import completion

# A minimal stand-in for typer's CompletionItem: format_completion and
# _zsh_compadd_script only ever read .value/.help.
Item = namedtuple("Item", ["value", "help"])


def test_registers_over_typers_stock_bash_and_zsh_completers():
    """completion_init() -- which typer calls on every `app()` -- must
    register our subclasses, not typer's stock ones, or the patch is a
    no-op the moment any command runs."""
    completion_init()
    assert get_completion_class("bash") is completion._NoSpaceBashComplete
    assert get_completion_class("zsh") is completion._NoSpaceZshComplete


class TestNoSpaceBashComplete:
    def test_format_completion_pairs_help_with_value(self):
        result = completion._NoSpaceBashComplete.format_completion(
            None, Item("/data/local/tmp/", "dir")
        )
        assert result == "dir\t/data/local/tmp/"

    def test_format_completion_tolerates_missing_help(self):
        """complete_process_name's candidates carry no help at all -- must
        not literally print "None" into the response line."""
        result = completion._NoSpaceBashComplete.format_completion(
            None, Item("com.example.app", None)
        )
        assert result == "\tcom.example.app"


@pytest.mark.skipif(shutil.which("bash") is None, reason="requires a real bash")
class TestNoSpaceBashScriptAgainstRealBash:
    """Drives the actual generated bash function, standing in for adb with
    a canned executable so this stays hermetic -- no device needed."""

    def _source(self):
        inst = completion._NoSpaceBashComplete(None, {}, "gunkata", "_GUNKATA_COMPLETE")
        return inst.source()

    def _run(self, tmp_path, fake_response: str):
        # Write the canned response as real bytes (a literal tab, a literal
        # newline) rather than embedding it as text into the shell script
        # below -- `printf %s <python repr>` would hand bash the four
        # characters "\", "t" instead of an actual tab.
        response_file = tmp_path / "response.txt"
        response_file.write_text(fake_response)
        fake_prog = tmp_path / "fake_prog"
        fake_prog.write_text(f"#!/usr/bin/env bash\ncat {response_file}\n")
        fake_prog.chmod(0o755)

        script = f"""
compopt_log="(none)"
compopt() {{ compopt_log="compopt $*"; }}
{self._source()}
_gunkata_completion {fake_prog}
printf 'COMPREPLY=%s\\n' "${{COMPREPLY[*]}}"
printf 'COMPOPT=%s\\n' "$compopt_log"
"""
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        ).stdout
        lines = dict(line.split("=", 1) for line in out.splitlines())
        return lines["COMPREPLY"], lines["COMPOPT"]

    def test_single_directory_match_skips_the_space(self, tmp_path):
        reply, compopt_call = self._run(tmp_path, "dir\t/data/local/tmp/\n")
        assert reply == "/data/local/tmp/"
        assert compopt_call == "compopt -o nospace"

    def test_single_file_match_keeps_the_space(self, tmp_path):
        reply, compopt_call = self._run(tmp_path, "file\t/data/local/foo.txt\n")
        assert reply == "/data/local/foo.txt"
        assert compopt_call == "(none)"

    def test_multiple_matches_never_suppress_the_space(self, tmp_path):
        """Bash's nospace option has no per-item granularity across a
        multi-candidate menu, so even an all-directory menu must not set it
        -- only the single-unambiguous-match case is safe to suppress."""
        reply, compopt_call = self._run(
            tmp_path, "dir\t/data/local/tmp/\ndir\t/data/local/cache/\n"
        )
        assert reply == "/data/local/tmp/ /data/local/cache/"
        assert compopt_call == "(none)"


class TestZshCompaddScript:
    def test_dir_gets_its_own_nospace_suffix(self):
        script = completion._zsh_compadd_script([Item("/data/", "dir")])
        assert script == "compadd -S '' -- '/data/'"

    def test_non_dir_keeps_the_default_suffix(self):
        script = completion._zsh_compadd_script([Item("/init", "file")])
        assert script == "compadd -- '/init'"

    def test_preserves_input_order_across_types(self):
        """A file that sorts before every directory (like a device's real
        `/d` next to `/data/`) must stay first: one compadd call per item,
        not one call per type, or grouping by type silently re-orders
        candidates `ls -1p` had already sorted."""
        script = completion._zsh_compadd_script(
            [Item("/d", "file"), Item("/data/", "dir"), Item("/dev/", "dir")]
        )
        assert script == (
            "compadd -- '/d'; compadd -S '' -- '/data/'; compadd -S '' -- '/dev/'"
        )

    def test_quotes_embedded_single_quotes(self):
        script = completion._zsh_compadd_script([Item("weird'name", "file")])
        assert script == "compadd -- 'weird'\\''name'"
