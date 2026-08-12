# gunkata

*Designed by a human. Implemented by an LLM.*

Tools to improve security research workflows for Android devices.

## Layout

Single package, `src/` layout: `src/gunkata/`. `main.py` holds the Typer CLI
(installs the `gunkata` console script); everything else is library code.

## Development

Managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create .venv, install gunkata + deps
uv run gunkata     # run the CLI
uv run gunkata version
```

Tests marked `emulator` need a live adb-attached device. `scripts/run_emulator.sh`
boots one locally (installing the emulator package, a system image, and the AVD
on first run) and leaves it running:

```bash
scripts/run_emulator.sh
uv run pytest -m emulator
```
