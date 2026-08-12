"""Edit one device file through a local editor, sudoedit-style."""

import logging
import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from .shell import Shell

logger = logging.getLogger(__name__)


class EditorNotFoundError(RuntimeError):
    """No editor was given and neither $VISUAL nor $EDITOR is set."""

    def __init__(self):
        super().__init__(
            "no editor: pass --editor, or set $VISUAL or $EDITOR"
        )


class Edit:
    """Edits one device file by round-tripping it through a local editor.

    Design:
        Modeled on sudoedit rather than an in-place remote edit: the file is
        pulled to a local temp path, a local editor blocks on it, and the
        result is pushed back only if its bytes changed. This keeps the
        device file untouched -- and the editor never aware it is remote --
        for the whole time the user is thinking, rather than exposing a
        partially-written file on the device mid-edit.
    """

    def __init__(self, shell: Shell, editor: str | None = None):
        self._shell = shell
        self._editor = editor

    def run(self, dpath: str) -> bool:
        """Edit dpath via a local editor, writing it back if it changed.

        Args:
            dpath: Path on the device to edit. Need not already exist; a
                missing path starts as an empty buffer and is created on
                save, provided its parent directory exists.

        Returns:
            Whether the file's bytes differ from what was read, i.e.
            whether a write-back happened.

        Raises:
            EditorNotFoundError: No editor was given and neither $VISUAL nor
                $EDITOR is set.
            ShellError: The underlying device read or write failed.

        Design:
            Only a newly created file gets chowned to its parent directory's
            owner. Rewriting an existing file's content in place preserves
            its inode and so its existing owner already; forcing a chown on
            every save would override that owner if it legitimately differs
            from its directory's, which create-on-write has no such prior
            owner to protect.
        """
        editor = self._resolve_editor()
        was_missing = False
        try:
            original = self._shell.read_file(dpath)
        except FileNotFoundError:
            original = b""
            was_missing = True

        suffix = "-" + PurePosixPath(dpath).name
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(original)
            logger.debug("edit %s: launching %s on %s", dpath, editor, tmp_path)
            subprocess.run([editor, tmp_path], check=True)
            edited = Path(tmp_path).read_bytes()
        finally:
            os.remove(tmp_path)

        if edited == original:
            return False
        self._shell.write_file(dpath, edited, inherit_owner=was_missing)
        return True

    def _resolve_editor(self) -> str:
        editor = self._editor or os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            raise EditorNotFoundError()
        return editor
