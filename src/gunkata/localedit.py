"""Resolve and launch the user's local editor on a throwaway temp file.

Shared by gunkata.edit (which round-trips a *device* file through it) and
`device note`'s editor mode (which composes free text with nothing remote
involved) -- both need exactly "find an editor, let it edit a temp file,
hand back the bytes", never the surrounding remote/local-only logic.
"""

import os
import subprocess
import tempfile
from pathlib import Path


class EditorNotFoundError(RuntimeError):
    """No editor was given and neither $VISUAL nor $EDITOR is set."""

    def __init__(self):
        super().__init__("no editor: pass --editor, or set $VISUAL or $EDITOR")


def resolve_editor(editor: str | None = None) -> str:
    """Resolve which editor to launch: editor, then $VISUAL, then $EDITOR.

    Raises:
        EditorNotFoundError: None of the three were given.
    """
    resolved = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not resolved:
        raise EditorNotFoundError()
    return resolved


def launch(editor: str, initial: bytes = b"", suffix: str = "") -> bytes:
    """Seed a local temp file with initial, block on editor, return its bytes.

    Args:
        editor: The editor binary to run, already resolved -- this never
            falls back to $VISUAL/$EDITOR itself; see resolve_editor.
        suffix: Appended to the temp file's name, so an editor that branches
            on extension (syntax highlighting, filetype plugins) sees one.

    Returns:
        The temp file's bytes exactly as the editor left them.

    Raises:
        subprocess.CalledProcessError: The editor exited non-zero.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(initial)
        subprocess.run([editor, tmp_path], check=True)
        return Path(tmp_path).read_bytes()
    finally:
        os.remove(tmp_path)
