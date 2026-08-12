import subprocess

import pytest
import typer

from gunkata.cli import fzf
from gunkata.ps import ProcessEntry

_FZF_ENTRIES = [
    ProcessEntry(pid=1234, name="com.example.app"),
    ProcessEntry(pid=5678, name="com.example.other"),
]


def test_fzf_pick_pid_returns_the_picked_pid(monkeypatch):
    monkeypatch.setattr(fzf.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        fzf.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, "1234\tcom.example.app\n", ""
        ),
    )
    assert fzf.fzf_pick_pid(_FZF_ENTRIES) == 1234


def test_fzf_pick_pid_returns_none_when_the_user_exits_without_picking(monkeypatch):
    """Esc/Ctrl-C in fzf exits non-zero with empty stdout; that must not raise."""
    monkeypatch.setattr(fzf.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        fzf.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 130, "", ""),
    )
    assert fzf.fzf_pick_pid(_FZF_ENTRIES) is None


def test_fzf_pick_pid_exits_with_an_install_hint_when_fzf_is_missing(monkeypatch):
    monkeypatch.setattr(fzf.shutil, "which", lambda name: None)
    with pytest.raises(typer.Exit) as raised:
        fzf.fzf_pick_pid(_FZF_ENTRIES)
    assert raised.value.exit_code == 1
