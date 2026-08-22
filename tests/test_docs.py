"""Doc-contract tests for the `# History` invariant in the root CLAUDE.md.

The checkout describes what is true now; git describes how it got that way.
These tests are the enforcement half of that rule: they scan tracked text for
prose that only makes sense to a reader who saw the previous version.

Scanning is limited to `git ls-files` output, so ignored trees and build
artifacts are never walked.
"""

import fnmatch
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Paths exempt from the prose scan. CLAUDE.md carries tombstones for designs
#: that shipped and were reverted -- the one rationale git cannot serve. This
#: module quotes every banned phrase it looks for.
EXEMPT_PATHS = frozenset({"CLAUDE.md", "tests/test_docs.py"})

#: Suffix allowlist rather than "decode and hope": lockfiles and vendored data
#: produce phrase hits nobody can act on.
SCANNED_SUFFIXES = frozenset(
    {".py", ".md", ".sh", ".toml", ".yaml", ".yml", ".cfg", ".ini", ".txt"}
)

#: Filenames whose whole purpose is to accumulate history.
HISTORY_FILE_GLOBS = ("CHANGELOG*", "HISTORY*", "MIGRATION*", "TODO.md", "NOTES.md")

#: Same-line escape hatch, so an exemption is visible at the point of use and
#: shows up in review. Deliberately not file-scoped.
EXEMPTION_MARKER = "noqa: history"

#: Each pattern is narrowed to the historical sense of its phrase. "used to" history-ok
#: is restricted to "used to be" -- bare "used to" is overwhelmingly "is used history-ok
#: to parse X". "legacy" is absent on purpose: it names real Android API
#: surface in this repo's domain, so it cannot be distinguished from prose.
HISTORY_PHRASES = (
    re.compile(r"\bwas:", re.IGNORECASE),
    re.compile(r"\bchanged from\b", re.IGNORECASE),
    re.compile(r"\bpreviously\b", re.IGNORECASE),
    re.compile(r"\bformerly\b", re.IGNORECASE),
    re.compile(r"\bused to be\b", re.IGNORECASE),
    re.compile(r"\bno longer\b", re.IGNORECASE),
    re.compile(r"\bin the past\b", re.IGNORECASE),
    re.compile(r"\bas of v(?:ersion)?[\s.]?\d", re.IGNORECASE),
    re.compile(r"\brecently completed\b", re.IGNORECASE),
    re.compile(r"\bbackwards?[ -]compat", re.IGNORECASE),
    re.compile(r"\bkept for compat", re.IGNORECASE),
    re.compile(r"\bTODO\s*\(\s*\d{4}-\d{2}-\d{2}\s*\)", re.IGNORECASE),
)


@pytest.fixture(scope="session")
def tracked_files() -> list[str]:
    """Every path git tracks, repo-relative, POSIX-separated.

    Returns:
        Paths as git reports them; empty only if the repo genuinely tracks
        nothing.

    Raises:
        Failed: `git ls-files` did not succeed, so the scan cannot claim
            coverage it does not have.

    Design: fails rather than skips when git is unavailable. A doc-contract
    test that silently passes in a tarball export is worse than absent -- the
    gate reports green having checked nothing.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"cannot enumerate tracked files under {REPO_ROOT}: "
            f"git ls-files exited {result.returncode}: {result.stderr.strip()}"
        )
    return [name for name in result.stdout.split("\0") if name]


def test_no_history_files_in_tree(tracked_files: list[str]) -> None:
    """Reject files whose whole purpose is to accumulate history.

    A CHANGELOG or a TODO.md is the first thing reached for when asked to
    "document the change", and it is the loudest form of the failure: a second
    source of truth about the past that nothing keeps in sync with git.
    """
    offenders = [
        name
        for name in tracked_files
        if any(
            fnmatch.fnmatch(Path(name).name, glob) for glob in HISTORY_FILE_GLOBS
        )
    ]
    assert not offenders, (
        "history belongs in git, not in tracked files:\n  "
        + "\n  ".join(offenders)
        + "\nDelete these; the commit message is where change is recorded."
    )


def test_no_history_prose_in_tree(tracked_files: list[str]) -> None:
    """Reject comments and prose that describe a previous version of the code.

    A `# was: sync, now async` comment rots on the next edit, and no reader can
    tell a stale one from a current one -- which is why the fix is deletion,
    not correction. Expected outcome: no tracked, non-exempt line matches a
    historical phrase without carrying the same-line exemption marker.
    """
    violations: list[str] = []
    for name in tracked_files:
        if name in EXEMPT_PATHS or Path(name).suffix not in SCANNED_SUFFIXES:
            continue
        path = REPO_ROOT / name
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if EXEMPTION_MARKER in line:
                continue
            for pattern in HISTORY_PHRASES:
                match = pattern.search(line)
                if match:
                    violations.append(f"{name}:{lineno}: {match.group(0)!r}")

    assert not violations, (
        "history belongs in git, not in the checkout:\n  "
        + "\n  ".join(violations)
        + f"\nDelete the line and write it in the commit message, or mark the "
        f"line `{EXEMPTION_MARKER}` if it is current truth."
    )
