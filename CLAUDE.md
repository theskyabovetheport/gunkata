# CLAUDE.md

Tools to improve security research workflows for Android devices

---

# Documentation

- **State each invariant once, split by job.** README states the *property*;
  CLAUDE.md states the *rule that protects it* plus the guard test's name.
  Never restate one in the other — they drift.
- **A CLAUDE.md invariant is a rule plus its guards**: a bold imperative, at
  most a sentence or two of why, and the names of the tests that pin it. The
  full rationale lives at exactly one durable home — the enforcement site's
  docstring, the module README, an ADR, or the guarding test's docstring — and
  CLAUDE.md *points* there instead of restating it.
- **Cross-cutting rules live only in the root CLAUDE.md.** A module CLAUDE.md
  holds only its *local* rules and points to root for shared ones.
- **A pointer must resolve.** Cite tests by exact name, sections by exact
  heading; a rename that breaks a pointer fixes the pointer in the same commit.
  <Guard with a doc-contract test once the repo has a few modules.>
- **Negative knowledge stays in CLAUDE.md, compressed to a sentence** — a
  design that shipped, was reverted, and would regress if reintroduced. Code
  cannot record what is absent from it, so this is the one rationale a
  pointer cannot serve. **Never leave a tombstone for a decision that never
  shipped**: an option considered and dropped is a changelog entry in the
  wrong place. The line between the two is whether the thing actually
  shipped.
- **A module earns a recipe once a kind repeats.** Write `## Adding a <thing>`
  — the ordered list of edits a correct addition makes, guard tests named — in
  the commit that creates the *second* instance of the kind.
- **An invariant that blocks the task is a question, never a judgement call.**
  Read its pointer first; if it still blocks, stop and ask. Never work around
  one silently. Changing a rule edits its CLAUDE.md entry, its guard test, and
  the code in the same commit.
- **Mark a workaround as a workaround, with its removal condition** — "this is
  a workaround, not a design; when <X> lands, move it; do not entrench it."
- **History questions have no answer in the checkout, by design.** Rationale
  for changes lives in git. Trace with `git log -S<text>`,
  `git show <sha>:<path>`, `git log --follow` — never guess from the tree.
  History answers *why* and *when*, never *what is true now*.
- No other top-level doc files unless the user explicitly asks.
- Deferred work lives in <the tracker>, never in module-local TODO files.
  Resolve an item by closing it in the same commit that resolves it, moving
  its durable half into the owning README.md or CLAUDE.md. Git records what
  changed; the backlog records only what is next. No "recently completed"
  archives.

# General Conventions

- Resolve every persistent path through one shared helper
  (`<package>/common/paths.py`); never re-implement the resolver locally.
  Secrets come only from the environment, never committed.
- **Every atom carries a single identity; aliases are forbidden.** The name a
  thing is stored under is the name it is read under. Every alias is a mapping
  somebody must maintain and eventually forgets.
- **Every served value is honest to the ground, and every failure is loud.**
  A value a caller receives either was observed or is the declared consequence
  of a stated policy — never a library default nobody chose. Loud means a
  refusal naming the path it refused, never a plausible number that flows on.
- **Write nothing before its caller.** A constant, field, parameter, or hook
  with no consumer is a guess nobody re-examines. Add the consumer in the same
  commit, or do not add the code. The question is "what breaks today if I
  leave it out".
- **When two concepts clash, pick the new one and wipe the old** — code,
  tests, docs, wiring. Never demote the loser to a fallback or a compat layer.
- **Reach a Protocol's implementations through a factory, never a registry
  constant.** A hand-maintained tuple cannot fail when someone forgets to
  extend it; a factory raises on an id it cannot resolve.
- **Measure before asserting, when measuring is cheap.** A claim about what
  the data holds is checked, not reasoned to. When the measurement is
  expensive, stop and ask, naming what you would measure, its cost, and what
  each outcome would change.
- **Any question about *code* goes to the language server; search is for
  *text*.** Definitions, references, call graphs: LSP. String literals, env
  vars, config keys, prose: `rg` (honors `.gitignore`; `grep -r` scans ignored
  trees). Pyright needs a `[tool.pyright]` block in `pyproject.toml` or it
  under-reports silently. `goToImplementation` is unsupported — Protocol
  satisfiers have no tool.
- **Explain a cross-component problem with the data-flow graph, never prose
  alone.** One node per component; mark what each *knows* and what it
  *decides*.
- Inline comments answer "why", not "how". No meta-comments describing how the
  code changed — that is what git is for.

# Logging

- Get a logger via stdlib `logging.getLogger(__name__)` at module level —
  never a custom Logger class, never dependency-injected.
- Never configure a handler, formatter, or level inside a module.
  Configuration happens exactly once, in the CLI entry point, before any
  subcommand runs. A module logs; the application configures.
- Use the logger hierarchy for selective verbosity
  (`logging.getLogger("<package>.<module>").setLevel(...)`); never invent a
  parallel mechanism.
- <Optionally: persist every record to a per-component `journal.jsonl` and
  read it back through a `<tool> logs` CLI command — the one supported
  observation surface. A monitoring gap means the logging is inadequate; fix
  that rather than grepping files.>

# CLI

- **The CLI is built on Typer, exposed as the single `gunkata` console script**
  (`gunkata.cli.main:main`). One shared `app`; new commands register on it, never a
  second Typer app or a second entry point.
- **A command body is presentation only** — parse args, call into
  `gunkata.core`, render the result. No logic in the command; that lives in
  core.

# Python Code Conventions

- Prefer `Protocol` over ABC when default method implementations are unlikely.
- Always write class docstrings. Write method/function docstrings unless
  trivial. A docstring that restates its own definition is worse than absent.
- **Docstrings are Google-style, contract first and rationale last.** Summary
  line, then `Args:`, `Returns:`, `Raises:`, then `Design:` for the why.
  `Returns:` states the shape invariant and domain meaning, never the type —
  the annotation already gives the type. Split contract from rationale at the
  *clause*: a `because` inside a contract section is the tell a split was
  missed.
- **A `Raises:` entry is `ExceptionName: condition.`** Prose passes every lint
  and documents no exception at all. Document what a caller must catch,
  including exceptions merely propagated.
- OOP by default: no module-level functions unless the module is a
  helper/utility collection.
- One class per module. Exception: dataclasses tightly coupled to the class —
  the schemas it directly consumes or produces.
- **`__init__.py` holds no logic** — a package docstring only, at most re-exports
  of names defined in sibling modules. Code lives in a named module (a CLI's
  in `main.py`), never in the package marker.
- Schema vs processor: a data schema goes in `types.py`; a processor gets its
  own module. Schemas mirror dependency structure — if B exists only because
  of A, nest B under A.
- **One level of generic nesting is the limit — name the structure.** Good:
  `list[str]`, `dict[str, int]`. Bad: `dict[int, list[tuple[set[str], int]]]`.
  A data shape that needs more gets a `@dataclass`; a callable shape that
  needs more than bare `Callable` gets a `Protocol` with a named `__call__`.
- **Cohering arguments become a type.** When the same cluster of parameters
  recurs across call sites and together describes one entity, introduce a
  dataclass. Domain objects over loose primitives.
- **`if TYPE_CHECKING:` is forbidden — a cycle it would hide is a placement
  error.** Move the type to `types.py` or a third module instead.
- Absolute imports for anything above the current package; relative only for
  siblings. All imports at module top; function-local only for a genuine
  circular import or a legitimately lazy heavy dependency.
- **Name a boolean after the state that carries consequence**; avoid negated
  names (`is_not_x`, `disabled`). Put the positive name on the informative
  state so `not x` never reads as a double negative.
- **Never catch a bare `except Exception` unless justified** — narrow to what
  you expect. A broad catch is only justified at a genuine resilience boundary
  (one bad item must not sink the batch); even then, log the exception with
  context and comment the justification.

# Tests

- `pytest` exclusively. Never import `unittest` — use `pytest.raises`,
  fixtures, `monkeypatch`, `tmp_path`, `capsys`, `caplog`.
- Non-trivial tests carry a docstring: WHAT is tested, WHY, and the expected
  outcome. Trivial tests whose name says it all need none.
- Do not test API conformance (that a method returns a given type, that a
  class has a field).

# Definition of Done

A change is done when the **whole** suite is green — never just the package's:

```bash
<run command, e.g. uv run pytest <package> scripts -q>
```

The per-module run is the inner loop, not the gate — two failure classes are
invisible to it: construction/wiring (guard with a smoke test per CLI
command), and cross-package invariants (a rule stated in one package is
routinely guarded in another).

**`scripts/check.sh` runs every gate this repo has** — lint, docs build, then
the suite. When there is no CI, this script is the whole of it. If the gate
deliberately excludes anything, this section says so, names the owner, and
names the command that runs the excluded part.

# Branches & Worktrees

- **Never check out a branch in the root checkout — always use a worktree.**
  Switching branches at the root silently redirects every subsequent edit.
- **A feature gets a branch and a worktree; the gate is the merge, not the
  commit.** Commit to the branch freely; never merge into the default branch
  without being asked. "Commit this" is not "merge this".
- Verify the base ref before creating a worktree; confirm the current branch
  before committing.
