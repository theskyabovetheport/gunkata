"""Edit one device file through a local editor, sudoedit-style."""

import logging
from pathlib import PurePosixPath

# EditorNotFoundError re-exported for callers; see Raises: below.
from gunkata.localedit import EditorNotFoundError, launch, resolve_editor  # noqa: F401

from .shell import Shell

logger = logging.getLogger(__name__)


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
        editor = resolve_editor(self._editor)
        was_missing = False
        try:
            original = self._shell.read_file(dpath)
        except FileNotFoundError:
            original = b""
            was_missing = True

        logger.debug("edit %s: launching %s", dpath, editor)
        edited = launch(editor, initial=original, suffix="-" + PurePosixPath(dpath).name)

        if edited == original:
            return False
        self._shell.write_file(dpath, edited, inherit_owner=was_missing)
        return True
