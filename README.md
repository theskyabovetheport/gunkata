# gunkata

*Designed by a human. Implemented by an LLM.*

Tools to improve security research workflows for Android devices.

## Layout

Single package, `src/` layout:

- `src/gunkata/core/` — core logic, presentation-free.
- `src/gunkata/cli/` — Typer CLI; installs the `gunkata` console script.

## Development

Managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create .venv, install gunkata + deps
uv run gunkata     # run the CLI
uv run gunkata version
```
