"""Xephyr: the nested X server frame that outlives the scrcpy content it hosts."""

import logging
import os
import re
import select
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager

from Xlib import X as xlib_X
from Xlib import Xatom as xlib_Xatom
from Xlib import display as xlib_display
from Xlib import error as xlib_error
from Xlib.ext import xtest

from .settings import ScrcpySettings

logger = logging.getLogger(__name__)

_SETTLE_SECONDS = 0.1
"""Grace given a process that just exited on its own, mirroring shell.py's
own constant of the same name and purpose -- an instantaneous poll() right
after exit can still read "running" for a process the kernel has not yet
finished marking reapable."""


_TESTED_HOST_X_RELEASE = 12101022
"""X.Org 21.1.22, the only host X server release the pointer bound was measured
correct on."""

_TESTED_I3_VERSION = (4, 25, 1)
"""i3 4.25.1, the only i3 the pointer bound was measured correct under.

Neither this nor _TESTED_HOST_X_RELEASE is a fix point. The bound went stale on
X.Org 21.1.12 with i3 4.23 and never on 21.1.22 with i3 4.25.1 -- two samples
differing in both, so which one matters is unknown and everything between them
is untested. check_pointer_reaches_the_screen is what actually observes the
defect; these two only say the ground has not been walked."""

_I3_VERSION = re.compile(r"i3 version (\d+)\.(\d+)(?:\.(\d+))?")

_PLACEHOLDER_BACKGROUND = "#1a1d23"
_PLACEHOLDER_FOREGROUND = "#9aa0a6"
_PLACEHOLDER_FONT = "-adobe-helvetica-bold-r-normal--48-*-*-*-p-*-iso8859-1"
"""How the frame's placeholder is painted. xmessage is an Xaw program, so
this must be an X core font XLFD -- no fontconfig name will do. A *scalable*
family (Type 1, whose XLFDs carry ``-0-0-0-0-``) is named rather than a
bitmap one, which is what makes 48px available at all: the largest latin
bitmap font this server carries is 24px. Verified at 480px, the narrowest
frame the defaults produce, where the message still fits on two lines with
room to spare; an unmatched pattern would cost only size, since xmessage
falls back to its own default font."""


class XephyrUnavailableError(RuntimeError):
    """The Xephyr binary is not on PATH."""


class MatchboxUnavailableError(RuntimeError):
    """The matchbox-window-manager binary is not on PATH."""


class NoDisplayError(RuntimeError):
    """No X server is available for Xephyr to nest inside."""


class FrameDisplayError(RuntimeError):
    """The frame's own X display could not be queried."""


class Xephyr:
    """A nested X server, the frame a WM manages so scrcpy's content never has to be.

    Args:
        title: Window title Xephyr's own frame carries -- the name a window
            manager shows and a user's own rules can match against.
        placeholder: Message shown inside the frame whenever scrcpy is not
            covering it.
        settings: frame size and readiness timeout, resolved from the
            environment. None builds a fresh ScrcpySettings.

    Design:
        The whole mechanism this feature relies on: an ordinary X11 client
        window that simply never exits, so no window manager ever needs to be
        read from or written to -- it keeps this window wherever it already
        put it, the same way it would any other long-lived window.

        The frame opens at the host screen's size, never at a size of its
        own choosing, because Xephyr confines the pointer to whatever the
        screen measured when it started -- see ``_host_screen_size``. A WM is
        free to shrink it from there; growing past that box is what would
        strand clicks, and the host screen is the largest box any WM has to
        give.

        ``-resizeable`` is what makes the frame an ordinary window rather
        than a fixed-size one, and it is load-bearing twice over. Verified
        live: with it, Xephyr sets no WM_NORMAL_HINTS at all and i3 tiles
        the frame like any other window, the nested screen following each
        new tile size through RandR; without it, Xephyr declares a minimum
        size equal to its maximum, which i3 reads as "cannot be resized"
        and floats, and any WM that tiles it anyway exposes outer window
        past the nested screen that Xephyr never paints. So
        the frame simply opens at the host screen's size and is resized from
        there by whatever manages it.

        A second process, matchbox-window-manager, runs *inside* the nested
        display alongside scrcpy -- verified against a live emulator: with no
        window manager in there at all, an X11 client has nothing to size or
        position it against, so scrcpy's own window opened at its own
        preferred size in a corner of the nested screen rather than filling
        it, unaligned with the frame regardless of ``--fullscreen``. matchbox
        keeps its one client maximized against the nested screen's
        current size, resize after resize.

        matchbox is frame-scoped, not scrcpy-scoped: started once here and
        reaped here, so it outlives every relaunch scrcpy itself goes
        through.

        ``screen_size`` exists because scrcpy has to be *replaced* when the
        frame changes size, not merely resized: verified on a real device,
        clicks land progressively too high after a resize -- scrcpy keeps
        mapping them against the geometry it started with -- while a freshly
        launched scrcpy is accurate. ScrcpySession watches this value and
        relaunches on a change.

        The placeholder is what the frame shows in the gap between one scrcpy
        and the next -- measured bare, that gap is a uniform #000000,
        indistinguishable from a dead frame. xmessage carries it, as another
        frame-scoped client matchbox maximizes and stacks below each new
        scrcpy, so it is revealed by scrcpy's exit and covered again by its
        relaunch with nothing to schedule. It is declared optional: it is not
        needed to mirror a device, so a missing binary is logged once and
        skipped rather than refused, which is the one place in this class
        that degrades instead of raising.
    """

    def __init__(
        self,
        title: str,
        placeholder: str,
        settings: ScrcpySettings | None = None,
    ):
        self._title = title
        self._placeholder = placeholder
        self._settings = settings if settings is not None else ScrcpySettings()
        self._process: subprocess.Popen | None = None
        self._matchbox_process: subprocess.Popen | None = None
        self._placeholder_processes: list[subprocess.Popen] = []
        self._display: str | None = None
        self._connection = None

    @property
    def display(self) -> str:
        """This frame's own X display, e.g. ``":7"``.

        Raises:
            RuntimeError: The frame has not been started.
        """
        if self._display is None:
            raise RuntimeError("Xephyr has not been started")
        return self._display

    def poll(self) -> int | None:
        """The frame process's exit code, or None while it is still running.

        Raises:
            RuntimeError: The frame has not been started.
        """
        if self._process is None:
            raise RuntimeError("Xephyr has not been started")
        return self._process.poll()

    @contextmanager
    def running(self) -> Generator["Xephyr", None, None]:
        """Start the frame for the duration of a ``with`` block, reaping it after.

        Yields:
            This frame, running, its display property resolved.

        Raises:
            NoDisplayError: No host X server ($DISPLAY) is available for
                Xephyr to nest inside -- a Wayland session with no XWayland.
            XephyrUnavailableError: The Xephyr binary is not on PATH.
            MatchboxUnavailableError: The matchbox-window-manager binary is
                not on PATH.
            RuntimeError: The frame exited before reporting its display
                number.
        """
        self._start()
        try:
            yield self
        finally:
            self._stop()

    def _start(self) -> None:
        width, height = self._host_screen_size()
        read_fd, write_fd = os.pipe()
        argv = [
            self._settings.xephyr_binary,
            "-resizeable",
            "-title",
            self._title,
            "-screen",
            f"{width}x{height}",
            "-displayfd",
            str(write_fd),
        ]
        try:
            self._process = subprocess.Popen(argv, pass_fds=(write_fd,))
        except OSError as exc:
            os.close(read_fd)
            os.close(write_fd)
            raise XephyrUnavailableError(
                f"{self._settings.xephyr_binary!r} is not on PATH; "
                "install it: apt install xserver-xephyr"
            ) from exc
        os.close(write_fd)
        try:
            self._display = f":{self._read_display_number(read_fd)}"
        finally:
            os.close(read_fd)
        self._connect()
        self._start_matchbox()
        self._start_placeholder()
        logger.info(
            "Xephyr frame started", extra={"title": self._title, "display": self._display}
        )

    def _host_screen_size(self) -> tuple[int, int]:
        """The host X screen's size, which the frame opens at.

        Returns:
            The host screen's pixel dimensions -- the largest rectangle any
            window manager can give the frame, and so the size it must open
            at.

        Raises:
            NoDisplayError: There is no host X server to nest inside.

        Design:
            Measured against a live emulator: Xephyr confines the pointer to
            the screen size it *opened* with and a RandR resize never widens
            that box again. Two clicks 500px apart past the boundary landed on
            the same device pixel. Opening at the host screen's own size is
            what makes the pointer reach every part of the frame, whatever
            size a WM later gives it -- a frame can be shrunk safely, never
            grown past its opening size.
        """
        name = os.environ.get("DISPLAY")
        if not name:
            raise NoDisplayError(
                "no $DISPLAY to nest Xephyr inside; a Wayland session needs "
                "XWayland running for gunkata scrcpy to work"
            )
        try:
            host = xlib_display.Display(name)
        except (xlib_error.DisplayError, OSError) as exc:
            raise NoDisplayError(
                f"could not connect to the host display {name}; a Wayland "
                "session needs XWayland running for gunkata scrcpy to work"
            ) from exc
        try:
            geometry = host.screen().root.get_geometry()
            self._warn_if_the_host_is_untested(host)
            return geometry.width, geometry.height
        finally:
            host.close()

    def _warn_if_the_host_is_untested(self, host) -> None:
        """Warn loudly if the host X server or its i3 is older than was tested.

        Args:
            host: The open connection to the host display, already used for its
                screen size.

        Design:
            An up-front warning, before a resize has the chance to strand any
            clicks -- unlike check_pointer_reaches_the_screen, which can only
            speak once a resize has happened. It claims an untested combination
            rather than a defect, because that is all two samples support: see
            _TESTED_I3_VERSION. Read off the connection this method's caller
            already opened, so no extra round trip.
        """
        release = host.display.info.release_number
        if release < _TESTED_HOST_X_RELEASE:
            logger.warning(
                "the host X server is X.Org %s, older than the 21.1.22 this was "
                "tested against. Clicks in a frame that is later made bigger may "
                "land short of where they were made -- gunkata measures the "
                "pointer's actual reach after every resize and will say so if it "
                "happens.",
                self._release_text(release),
            )
        i3 = self._running_i3_version(host)
        if i3 is not None and i3 < _TESTED_I3_VERSION:
            logger.warning(
                "the running window manager is i3 %s, older than the 4.25.1 this "
                "was tested against. Clicks in a frame that is later made bigger "
                "may land short of where they were made -- gunkata measures the "
                "pointer's actual reach after every resize and will say so if it "
                "happens.",
                ".".join(str(part) for part in i3),
            )

    @staticmethod
    def _release_text(release: int) -> str:
        """An X.Org release number as its dotted version, e.g. 21.1.22."""
        return f"{(release // 100000) % 100}.{(release // 1000) % 100}.{release % 1000}"

    def _running_i3_version(self, host) -> tuple[int, ...] | None:
        """i3's version when i3 is the window manager actually running, else None.

        Args:
            host: The open connection to the host display.

        Returns:
            The version as (major, minor, patch), or None when the running
            window manager is not i3 or will not say -- an i3 merely installed
            beside another WM must not be warned about.

        Design:
            The WM is identified from _NET_SUPPORTING_WM_CHECK rather than from
            the binary being on PATH, and only then is the binary asked for its
            number, which the property does not carry.
        """
        try:
            check = host.screen().root.get_full_property(
                host.intern_atom("_NET_SUPPORTING_WM_CHECK"), xlib_Xatom.WINDOW
            )
            if check is None or not check.value:
                return None
            owner = host.create_resource_object("window", check.value[0])
            name = owner.get_full_property(host.intern_atom("_NET_WM_NAME"), 0)
        except (xlib_error.XError, OSError):
            return None
        if name is None or bytes(name.value).decode("utf-8", "replace") != "i3":
            return None
        try:
            reported = subprocess.run(
                ["i3", "--version"], capture_output=True, text=True, timeout=5
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        found = _I3_VERSION.search(reported)
        if found is None:
            return None
        return tuple(int(part) for part in found.groups() if part is not None)

    def _connect(self) -> None:
        """Open this process's own X connection to the frame, for screen_size.

        Raises:
            FrameDisplayError: The frame's display refused a connection.
        """
        try:
            self._connection = xlib_display.Display(self.display)
        except (xlib_error.DisplayError, OSError) as exc:
            self._stop()
            raise FrameDisplayError(
                f"could not connect to the frame's own display {self.display}"
            ) from exc

    def screen_size(self) -> tuple[int, int]:
        """The nested screen's size right now, as (width, height).

        Returns:
            The frame's current pixel dimensions, which follow the frame
            window's own size for as long as -resizeable is passed.

        Raises:
            RuntimeError: The frame has not been started.
            FrameDisplayError: The frame's display stopped answering.

        Design:
            The root window's geometry is requested each call rather than
            read off ``Display.screen()``, whose width_in_pixels is captured
            in the connection handshake and never updated -- it would report
            the size the frame opened at forever.
        """
        if self._connection is None:
            raise RuntimeError("Xephyr has not been started")
        try:
            geometry = self._connection.screen().root.get_geometry()
        except (xlib_error.XError, OSError) as exc:
            raise FrameDisplayError(
                f"the frame's display {self.display} stopped answering"
            ) from exc
        return geometry.width, geometry.height

    def check_pointer_reaches_the_screen(self) -> bool:
        """Warn loudly if the pointer cannot reach this frame's far corner.

        Returns:
            True when the pointer reaches the screen's last pixel, False when
            something bounds it short of that -- in which case a warning naming
            the bound has already been logged.

        Raises:
            RuntimeError: The frame has not been started.
            FrameDisplayError: The frame's display stopped answering.

        Design:
            Measured on another machine: after a frame is resized, its X server
            can keep bounding the pointer to a smaller rectangle than the
            screen, so clicks past that box land short -- correct at the
            top-left, worse the further out, and permanent until the session is
            restarted. It is not tied to a version (the same Xephyr build
            behaves correctly here), so the bound is measured rather than
            inferred: warp to the last pixel and see where the pointer lands.
            The pointer is put back where it was, and callers run this only
            while scrcpy is down, so nothing reaches the device.
        """
        if self._connection is None:
            raise RuntimeError("Xephyr has not been started")
        width, height = self.screen_size()
        try:
            root = self._connection.screen().root
            before = root.query_pointer()
            xtest.fake_input(
                self._connection, xlib_X.MotionNotify, x=width - 1, y=height - 1
            )
            self._connection.sync()
            landed = root.query_pointer()
            xtest.fake_input(
                self._connection,
                xlib_X.MotionNotify,
                x=before.root_x,
                y=before.root_y,
            )
            self._connection.sync()
        except (xlib_error.XError, OSError) as exc:
            raise FrameDisplayError(
                f"the frame's display {self.display} stopped answering"
            ) from exc
        if (landed.root_x, landed.root_y) == (width - 1, height - 1):
            return True
        logger.warning(
            "the pointer in this frame cannot get past %sx%s inside a %sx%s screen: "
            "clicks beyond that land short of where they were made, worse the "
            "further from the top-left, and no relaunch of scrcpy fixes it. This "
            "is the X server keeping a bound from when the frame was smaller. "
            "Restart this gunkata scrcpy session to clear it, and avoid growing "
            "the frame afterwards.",
            landed.root_x + 1,
            landed.root_y + 1,
            width,
            height,
        )
        return False

    def _start_matchbox(self) -> None:
        env = dict(os.environ, DISPLAY=self._display)
        argv = [self._settings.matchbox_binary, "-use_titlebar", "no"]
        try:
            self._matchbox_process = subprocess.Popen(argv, env=env)
        except OSError as exc:
            self._stop()
            raise MatchboxUnavailableError(
                f"{self._settings.matchbox_binary!r} is not on PATH; "
                "install it: apt install matchbox-window-manager"
            ) from exc

    def _start_placeholder(self) -> None:
        """Paint the frame's placeholder, skipping whichever binary is absent.

        Design:
            Started after matchbox so the message is a client matchbox
            already manages -- it is maximized against the nested screen and
            re-maximized on every resize, which a root pixmap could not be
            (X tiles a pixmap smaller than the root it backs). That maximized
            window is also the whole background: xmessage's own ``-bg`` fills
            the frame, and painting the nested root is not an option anyway
            -- measured, ``xsetroot -solid`` returns 0 against a Xephyr root
            and leaves it black, so the frame is bare black exactly when
            xmessage is the thing that is missing.
        """
        self._run_optional(
            [
                self._settings.xmessage_binary,
                "-buttons",
                "",
                "-bg",
                _PLACEHOLDER_BACKGROUND,
                "-fg",
                _PLACEHOLDER_FOREGROUND,
                "-fn",
                _PLACEHOLDER_FONT,
                self._placeholder,
            ],
            "the frame shows no message while scrcpy is down",
        )

    def _run_optional(self, argv: list[str], consequence: str) -> None:
        """Start argv inside the frame, logging and skipping it if it is not installed.

        Args:
            argv: The command to run, its binary name first.
            consequence: What the caller loses if that binary is absent,
                logged so a bare frame is never a mystery.
        """
        env = dict(os.environ, DISPLAY=self.display)
        try:
            self._placeholder_processes.append(subprocess.Popen(argv, env=env))
        except OSError:
            logger.info(
                "%s is not on PATH, skipping it: %s", argv[0], consequence
            )

    def _read_display_number(self, read_fd: int) -> str:
        """Read the display number -displayfd reports, never blocking past the deadline.

        Design:
            A bare ``os.read`` blocks indefinitely once called -- a deadline
            checked only between calls would not bound a single call that
            never returns. ``select`` is polled instead, so a Xephyr that
            hangs without writing or exiting still surfaces as a timeout
            rather than wedging this call forever.
        """
        deadline = time.monotonic() + self._settings.frame_ready_timeout_seconds
        chunks = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop()
                raise RuntimeError(
                    "Xephyr did not report a display number within "
                    f"{self._settings.frame_ready_timeout_seconds}s"
                )
            ready, _, _ = select.select([read_fd], [], [], remaining)
            if not ready:
                continue
            data = os.read(read_fd, 64)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
        number = b"".join(chunks).strip()
        if not number:
            self._stop()
            raise RuntimeError("Xephyr exited before reporting a display number")
        return number.decode("ascii")

    def _stop(self) -> None:
        # Clients before the server they run against: stopping them first
        # avoids the broken-pipe noise a client sees when its X connection
        # disappears out from under it. The placeholder's own clients go
        # before matchbox, which manages them.
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        for process in self._placeholder_processes:
            self._reap(process)
        self._placeholder_processes.clear()
        self._reap(self._matchbox_process)
        self._matchbox_process = None
        self._reap(self._process)
        self._process = None
        logger.info("Xephyr frame stopped", extra={"title": self._title})

    def _reap(self, process: subprocess.Popen | None) -> None:
        """Stop process, escalating if it ignores the request; a no-op if it never started.

        Design:
            Mirrors shell.py's module-level ``_reap`` policy (settle,
            terminate, grace, kill) but stays a method here: unlike Stream
            and Shell.pull_tree, which are two different classes sharing one
            policy, both processes this reaps belong to this one instance.
        """
        if process is None:
            return
        try:
            process.wait(timeout=_SETTLE_SECONDS)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=self._settings.stop_grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
