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
