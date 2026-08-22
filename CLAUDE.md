# CLAUDE.md

# No history outside git

**Never write history into anything but a commit message.** Guarded by
`doctrine test`, run from the pre-commit hook; exempt a line that genuinely
needs a banned phrase with a `history-ok` marker on that line. This governs
code, comments, docstrings, READMEs, docs, config files, and replies. Git
records what changed; nothing else may.

Banned outright — if a sentence only parses for someone who saw the previous
version, delete it:

- "used to", "previously", "formerly" <!-- history-ok -->
- "no longer", "any more", "it is gone" <!-- history-ok -->
- "an earlier version", "this replaced" <!-- history-ok -->
- "X was tried and removed" <!-- history-ok -->
- changelog, "what changed", or "recently completed" sections
- any comment that explains code by describing the code it replaced

Rationale is present tense — a fact about the code that exists:

- ✗ `logger used to be here and is gone: it returned non-zero on some hosts.` <!-- history-ok -->
- ✓ `No logger here: it returns non-zero on hosts with no syslog socket.`

**Rewording past the scan is not a repair.** A present-tense sentence
carrying the same fact is the same violation, and no phrase list can see
it. The test is the source of the claim: true only because of a version
that is gone — delete it, the commit message holds it; true of something
that exists, like data an older build left on disk or a format another
project ships — it is a rule, so write what it forbids now rather than
what happened then. No guard: which of the two a sentence is cannot be
read from its words.

**Negative knowledge is the one exception, and it lives in CLAUDE.md** — one
sentence each, as a rule and never as a story: what must not be reintroduced,
and what it breaks. Code cannot record what is absent from it. The line is
whether the thing actually shipped: an option considered and dropped, or an
intermediate state of the change you are making, earns nothing. No guard:
whether a thing shipped is a reading of the repository's past that no scan
of its present tree can make.

**Be exhaustive in the commit message.** That is the one place history
belongs. No guard: what a message leaves out is visible only to a reader
who knows the change; no hook can measure the absence.

# Work on a branch, in a worktree

- **Create the branch before starting the work.** No guard: the first
  moment a hook can fire is the first commit, when the work has already
  landed on whatever branch was checked out.
- **Create worktrees under `.claude/worktrees/`** — `git worktree add
  .claude/worktrees/<branch> <branch>`, never a sibling directory. No
  guard: a sibling directory is outside this repository, where none of
  its hooks run.
- Verify the base ref before creating a worktree — a local remote can lag the
  local branch. Confirm the current branch before committing.
- **Never check out a branch in the root checkout.** The root holds the
  default branch; every other branch gets its own worktree. No guard: by
  the time a pre-commit hook fires, the checkout has already happened and
  the damage is done.
- **The gate is the merge, not the commit.** Commit to a feature branch
  freely; never merge to the default branch without being asked. "Commit
  this" is not "merge this". No guard: which merges were asked for is
  known only to the person who asked; a hook cannot tell a sanctioned
  merge from a stray one.

# No invented numbers

**Never invent a threshold, a limit, a timeout, a retry count, or a size
cap.** A number that governs behaviour comes from a source outside the
writer's head: a measurement taken on this machine, a documented limit of
what the code talks to, a published standard, or the person who asked for
the work. No guard: a scan reads the literal and cannot tell a measured
number from a plausible one.

- **When no source has the number, ask the person who asked for the
  work** — for the value, or for what to measure to get it — and leave it
  unwritten until the answer comes. No guard: whether anyone was asked is
  known only to the parties of that conversation.
- **Name the source beside the number**, in the present tense: the
  standard, the documented cap, or the measurement and the machine it ran
  on. No guard: the presence of a citation is not its truth, and which
  number it covers only a reader can say.
- Not a threshold, and nothing to ask about: a value the code derives at
  run time from what it read, and a constant the format or the protocol
  fixes whose definition the code names.

# Name it, never copy it

**A rule points at code by name and never restates what the code says.**
A name — `Class.method`, a test, a file, a heading — survives every edit
but a rename, and a rename fixes the pointer in the same commit. A copied
value, path, default, signature, or list of call sites goes stale the
moment the code moves and reads as true until someone acts on it. Guarded
by `doctrine test` (dangling-test-pointer) for the test names it resolves;
the rest has no guard: a copy and a boundary read alike to a scanner.

- **The rename test decides: if an edit that renames nothing can make the
  sentence false, it is a copy.** Delete it, or put the fact beside the
  code and name that place. No guard: whether a sentence still tracks the
  code is a reading of both.
- **A pointer is bare** — the exact name, and nothing about what the
  referent does or holds. A sentence may follow it only if it stays true
  when the referent's internals change but its name and role do not. No
  guard: a gloss and a boundary sentence read alike to a scanner.
- What the tree does not hold stays: a limit of an external tool, the
  consequence of breaking the rule, a fact no reader can derive from the
  code. Exposition belongs in the README, which describes rather than
  enumerates: a list the tree also holds is a copy wherever it sits.

# Be frugal in writing

**Cut the paragraph and reread what remains: where no reader does anything
differently, it does not go in.** This binds text that instructs — a rule,
a docstring, a comment, an error's remedy. The commit message is exempt,
where being exhaustive is the law. No guard: whether a paragraph changes
what someone does is a reading of it and of its reader.

# No legacy code

**Delete what a version that is gone left behind.** A shim keeping an old
call shape alive, a branch reachable only from something already deleted,
a `v2` beside a `v1` nobody calls: git holds it, and the tree carries only
what runs. No guard: a scanner sees a live function whether or not
anything still needs it.

- **What serves something that exists is not legacy.** A reader for data
  on disk, a route a peer still calls, a flag a config still sets — the
  supported case is named in the present tense, and the code stays. No
  guard: which callers exist is a fact about the world, not about the
  tree.
- **Delete rather than deprecate.** Where consumers outside the
  repository make a window unavoidable, the condition that ends it comes
  from them, never from the writer. No guard: whether a consumer exists
  cannot be read from this repository.
- **Legacy stays where the person who asked for the work says it stays.**
  The keeping is one sentence in CLAUDE.md — what is kept, and the
  condition that removes it — written as a rule and never as the story of
  how it got there; silence is not approval. No guard: which keepings were
  sanctioned is known only to the parties of that conversation.

# CLAUDE.md

Tools to improve security research workflows for Android devices

---

# Documentation

- **State each invariant once, split by job.** README states the *property*;
  CLAUDE.md states the *rule that protects it* plus the guard test's name.
  Never restate one in the other — they drift. No guard: whether a fact
  appears in both files is a reading of prose no scanner performs.
- **A CLAUDE.md invariant is a rule plus its guards**: a bold imperative, at
  most a sentence or two of why, and the names of the tests that pin it. The
  full rationale lives at exactly one durable home — the enforcement site's
  docstring, the module README, an ADR, or the guarding test's docstring — and
  CLAUDE.md *points* there instead of restating it. No guard: whether a
  sentence points versus restates the rationale is a judgement only a
  reviewer can make.
- **Cross-cutting rules live only in the root CLAUDE.md.** A module CLAUDE.md
  holds only its *local* rules and points to root for shared ones. No guard:
  this repository carries a single CLAUDE.md, so the rule has nothing to
  violate yet.
- **A pointer must resolve.** Cite tests by exact name, sections by exact
  heading; a rename that breaks a pointer fixes the pointer in the same
  commit. Guarded by `doctrine test` (dangling-test-pointer) for the test
  names a CLAUDE.md cites; a section-heading pointer has no such check yet.
- **A module earns a recipe once a kind repeats.** Write `## Adding a <thing>`
  — the ordered list of edits a correct addition makes, guard tests named — in
  the commit that creates the *second* instance of the kind. No guard:
  whether a second instance of a kind has appeared is a judgement only a
  reviewer makes.
- **An invariant that blocks the task is a question, never a judgement call.**
  Read its pointer first; if it still blocks, stop and ask. Never work around
  one silently. Changing a rule edits its CLAUDE.md entry, its guard test, and
  the code in the same commit. No guard: whether a blocker was actually
  raised and asked about is known only to the parties of that conversation.
- **Mark a workaround as a workaround, with its removal condition** — "this is
  a workaround, not a design; when <X> lands, move it; do not entrench it."
  No guard: recognizing a workaround in code is a judgement a scanner cannot
  make.
- No other top-level doc files unless the user explicitly asks.
- Deferred work lives in <the tracker>, never in module-local TODO files.
  Resolve an item by closing it in the same commit that resolves it, moving
  its durable half into the owning README.md or CLAUDE.md. The backlog
  records only what is next; see `# History` for what it must not record.

# History

**The checkout says what is true now. Git says how it got that way.** Two
rules, firing at different moments — you need both. No guard: this sentence
introduces the two rules below; each carries its own guard or reason.

**Never write history into a tracked file.** Banned in every file you edit:
changelogs, "recently completed" sections (in files *and* in the tracker),
migration notes, dated TODOs, commented-out old code, and any comment of the
form `# was:`, `# changed from`, `# previously`, `# as of v2`, `# no longer`, <!-- history-ok -->
`# kept for compat`. Test: if your line only makes sense to a reader who saw
the previous version, it belongs in the commit message. Delete it and write
it there. Guarded by `test_no_history_prose_in_tree` and
`test_no_history_files_in_tree`, in `tests/test_docs.py`.

**Never answer a "why" or "when" question from the tree.** Trigger phrases:
"why is this like this", "when did this change", "what did this used to do", <!-- history-ok -->
"who decided", "was this intentional". These have no answer in the checkout,
by design. No guard: whether a given answer came from git or was guessed
from the code is legible only to whoever wrote it. Run git:

```bash
git log -S'<exact text>' -- <path>   # when this string appeared/vanished
git log --follow -p -- <path>        # this file's changes, across renames
git log -L<start>,<end>:<path>       # these lines' history
git show <sha>:<path>                # the file as of that commit
```

**If git does not answer it, say "git does not record this."** Do not infer
intent from the code. A reconstructed rationale is indistinguishable from a
real one to the reader, and wrong about half the time. No guard: whether a
stated rationale was reconstructed or read from git is not visible in the
text alone.

**One exception, narrow: negative knowledge lives in CLAUDE.md, compressed to
a sentence** — a design that *shipped and was reverted* and would regress if
reintroduced. Code cannot record what is absent from it, so this is the one
rationale a pointer cannot serve. The test is a single question: was it ever
merged to the default branch? No → not a tombstone; it is a changelog entry
in the wrong place. Do not write it. No guard: whether a design shipped and
was reverted is a fact about history no scan of the present tree can
confirm.

# General Conventions

- Resolve every persistent path through one shared helper
  (`gunkata/common/paths.py`); never re-implement the resolver locally.
  Secrets come only from the environment, never committed.
- **Every atom carries a single identity; aliases are forbidden.** The name a
  thing is stored under is the name it is read under. Every alias is a mapping
  somebody must maintain and eventually forgets. No guard: an alias is
  invisible to a scanner that only ever reads one name at a time.
- **Every served value is honest to the ground, and every failure is loud.**
  A value a caller receives either was observed or is the declared consequence
  of a stated policy — never a library default nobody chose. Loud means a
  refusal naming the path it refused, never a plausible number that flows on.
  No guard: whether a value was observed or is a policy's declared consequence
  is a fact about the code path, not its text.
- **Write nothing before its caller.** A constant, field, parameter, or hook
  with no consumer is a guess nobody re-examines. Add the consumer in the same
  commit, or do not add the code. The question is "what breaks today if I
  leave it out". No guard: whether a new symbol already has a consumer is a
  fact about the diff, not something a static scan resolves in general.
- **A device's persisted settings load exactly once, in `Device.__init__`,
  and the environment outranks them.** Loading in `Adb` instead would charge a
  roster fan-out one file read per serial and let one device's stored values
  reach another; see that constructor's `Design:` note. The same `persisted`
  dict is shared by `Su` and `Shell`'s settings, each ignoring the other's
  keys, rather than each reading the file itself. `DeviceSettingsStore.environment`
  is the only reader — it applies the precedence rule, so no consumer
  re-implements the comparison. Guarded by
  `test_shell_defaults_to_root_when_the_device_persisted_default_user`,
  `test_an_exported_value_outranks_the_persisted_one`, and
  `test_another_devices_settings_do_not_reach_this_one` in
  `tests/test_device.py`; `test_environment_drops_a_key_the_process_already_has`
  in `tests/test_device_settings.py`.
- **`Shell` wraps through su for any user except "shell"; `Device`'s
  `default_user` decides only what a bare `shell()` call resolves to.**
  `Su.wrap` has no separate enabled/disabled flag: it wraps whenever the
  user it's given isn't literally `"shell"` (adb's own already-unprivileged
  identity, never an su target, so wrapping it would ask su for a no-op at
  best and a rejected request at worst) — a *non*-"root" user wrapped
  against a `GUNKATA_SU_COMMAND` template with no `{user}` placeholder
  raises `ValueError` rather than silently dropping it; `"root"` is exempt,
  since it is su's own no-argument default and some su binaries reject an
  explicit user entirely, so dropping the placeholder for it is the correct
  wrap, not a lossy one. `default_user` (env `GUNKATA_SHELL_DEFAULT_USER`,
  default `"shell"`) lives in `ShellSettings` in `shell.py`, not in
  `SuSettings`: it answers "what does a bare `shell()`/CLI call with no
  `-U` default to," not "how to invoke su," and `Shell.__init__` resolves it
  itself via `ShellSettings.resolve_user` — `Device` only ever wires the
  `Su`/`ShellSettings` objects it built once in `__init__` into `Shell`,
  never reaching into either one's fields itself. `has_root` calls the bare
  form rather than `shell(user="root")` for a related reason: it measures
  what `default_user` actually grants, not what an explicit override could
  force. Guarded by `test_shell_wraps_via_su_for_any_explicit_user_other_than_shell`,
  `test_shell_never_wraps_the_shell_user_even_named_explicitly`,
  `test_shell_bare_default_tolerates_a_command_template_without_a_user_placeholder`,
  `test_shell_defaults_to_shell_user_by_default`, and
  `test_shell_defaults_to_the_configured_default_user` in `tests/test_device.py`;
  `test_su_wraps_for_any_user_other_than_shell_with_no_env_var_required`,
  `test_su_sends_the_command_unwrapped_for_the_shell_user`,
  `test_wrap_drops_the_placeholder_silently_for_root`,
  `test_wrap_raises_when_the_command_has_no_user_placeholder`,
  `test_default_user_env_var_is_read_by_shell_settings`, and
  `test_default_user_is_shell_by_default` in `tests/test_shell.py`.
- **A command handed to `Shell` runs exactly as given — su-invocation
  quoting is `Su.wrap`'s own concern, never the caller's.** `Su.wrap`
  substitutes `{command}` via `shlex.quote` unconditionally, so a
  `GUNKATA_SU_COMMAND` template writes the placeholder bare, never
  `'{command}'` -- `Su.wrap` already supplies exactly the quoting needed.
  A template containing a single quote anywhere is rejected loudly at
  `Su.__init__`, rather than silently double-quoting the first time a
  command needs escaping. See `Su.wrap`'s docstring for the full
  rationale. Guarded by `test_wrap_escapes_a_command_that_quotes_itself`,
  `test_wrap_escapes_a_command_that_quotes_itself_against_a_custom_template`,
  and `test_su_rejects_a_command_template_containing_a_single_quote` in
  `tests/test_shell.py`.
- **A device path `Shell.pull` accepts is checked against a whitelist, never
  escaped.** `Shell._SAFE_DEVICE_PATH` is a character whitelist rather than a
  quoting scheme because quoting would defeat the feature: the device's own
  shell has to expand the wildcard, so `dpath` is spliced unquoted into
  `_TAR_STREAM_COMMAND`'s shell syntax. `Su.wrap`'s `shlex.quote` protects the
  su hop, per the rule above — not that splice, since `adb shell` hands the
  assembled command to a shell whether su is involved or not. Matched with
  `fullmatch`, never `match`: Python's `$` also matches just before a trailing
  newline, one character past a whitelist whose whole job is keeping shell
  syntax out. `Shell._check_device_path` is the one enforcement point — called
  by both `pull` and `pull_tree`, since `pull_tree` is public and reachable
  without going through `pull` first — and it also refuses a wildcard outside
  the final path component and a relative or basename-less path. Only `pull`
  and `pull_tree` validate this way; `pull_file`, `push_file`, `read_file`, and
  `write_file` stay unvalidated, so the whitelist is not yet a `Shell`-wide
  invariant. Guarded by `test_pull_refuses_a_shell_metacharacter`,
  `test_pull_refuses_a_device_path_ending_in_a_newline`,
  `test_pull_refuses_a_wildcard_outside_the_last_component`,
  `test_pull_refuses_root_for_having_no_basename`,
  `test_pull_refuses_a_relative_path`,
  `test_pull_refuses_an_unsafe_path_via_pull_tree_directly`, and
  `test_pull_accepts_paths_a_tighter_regex_would_have_refused` in
  `tests/test_shell.py`.
- **A directory pull and a wildcard pull share one device command,
  `Shell._TAR_STREAM_COMMAND`.** Both cd into `dpath`'s parent and tar
  `./<pattern>` — a directory's own name for one, a glob for the other — so
  a tar member's own recorded path, not a branch in this code, decides
  whether it lands flat or nested under a name. Guarded by
  `test_pull_tree_builds_the_verbatim_shape_for_a_glob` and
  `test_pull_tree_builds_the_same_shape_for_a_directory` in
  `tests/test_shell.py`.
- **Exit status 90 means "the requested path does not exist" and nothing
  else**, shared by `read_file`'s `cat`-or-`exit 90` command and
  `_TAR_STREAM_COMMAND`'s `[ -e ] || [ -h ] || exit 90` guard — both read
  off `Shell._MISSING_FILE_RC`, so the sentinel cannot drift between the two
  commands that use it. A `tarfile.ReadError` racing the same rc must never
  be believed over it. Guarded by
  `test_read_file_raises_file_not_found_when_the_remote_path_is_missing` and
  `test_pull_tree_rc_90_raises_file_not_found_never_the_read_error` in
  `tests/test_shell.py`.
- **`pull` never creates or clears a local directory; a tree pull merges into
  whatever is there.** A destination that does not exist is a refusal naming
  it, in all three cases -- a mistyped one would otherwise report success and
  leave the pull where nobody looks, and the file case could not offer the
  convenience anyway, since `pull_file` spools through a sibling its parent
  must already hold. Merging is the consequence: a repeat pull overwrites what
  it re-lands and leaves the rest, so a local tree stops matching the device
  once a file is deleted there. Clearing first would trade a partial tree for
  a deleted one. Guarded by
  `test_pull_tree_refuses_a_destination_that_does_not_exist`,
  `test_pull_of_a_plain_file_refuses_a_destination_directory_that_does_not_exist`,
  and `test_pull_tree_merges_into_a_tree_that_is_already_there` in
  `tests/test_shell.py`.
- **`Stream.close` is idempotent *and* blocking: a second caller waits for
  the first one's reap instead of returning while it is still in flight.**
  Returning on the `_closed` flag alone hands the racing caller a
  `returncode` of None, a `_stopped` still False, and an empty `_stderr`, so
  `_raise_if_failed` reads a command that failed on its own as one that never
  finished. `Logcat.follow_for` is what makes this reachable -- its
  `threading.Timer` closes while the reader iterates -- so the thread-safety
  `Stream` documents is a contract another module depends on, not a local
  nicety. This is also why `_raise_if_failed` carries no `returncode is None`
  branch: the state is unreachable, and admitting it either swallows a real
  failure or reports `rc=None`. See `Stream.close`'s `Design:` note. Guarded by
  `test_close_does_not_return_until_a_racing_close_has_reaped` and
  `test_a_racing_close_neither_swallows_a_failure_nor_invents_one` in
  `tests/test_stream.py`.
- **When two concepts clash, pick the new one and wipe the old** — code,
  tests, docs, wiring. Never demote the loser to a fallback or a compat layer.
  No guard: recognizing which of two clashing concepts is newer is a
  judgement call, not a pattern a scan can make.
- **Reach a Protocol's implementations through a factory, never a registry
  constant.** A hand-maintained tuple cannot fail when someone forgets to
  extend it; a factory raises on an id it cannot resolve. No guard: which
  construction path a caller takes is invisible to a scan of any single file.
- **Measure before asserting, when measuring is cheap.** A claim about what
  the data holds is checked, not reasoned to. When the measurement is
  expensive, stop and ask, naming what you would measure, its cost, and what
  each outcome would change. No guard: whether a claim was actually measured,
  or only reasoned to, is a fact about how it was written, not its text.
- **Any question about *code* goes to the language server; search is for
  *text*.** Definitions, references, call graphs: LSP. String literals, env
  vars, config keys, prose: `rg` (honors `.gitignore`; `grep -r` scans ignored
  trees). Pyright needs a `[tool.pyright]` block in `pyproject.toml` or it
  under-reports silently. `goToImplementation` is unsupported — Protocol
  satisfiers have no tool. No guard: which tool answered a given question is
  not recorded anywhere a scanner reads.
- **Explain a cross-component problem with the data-flow graph, never prose
  alone.** One node per component; mark what each *knows* and what it
  *decides*. No guard: whether an explanation included a graph is a property
  of prose, not of tracked code.
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
- `$GUNKATA_LOG_LEVEL` sets the root logger's level, parsed by `LogSettings`
  and applied once by `gunkata.cli.logging_config.configure_logging` at the
  CLI entry point (`gunkata.cli.main:main`) -- both live together in
  `cli/logging_config.py`, per the settings-colocation rule above, since
  `configure_logging` is `LogSettings`' only consumer. Accepts either a bare
  number or a level name (`DEBUG`, `INFO`, ...), case-insensitively; an
  unrecognized value raises loudly rather than falling back to a default.
  Guarded by `tests/cli/test_logging_config.py`.
- **As a library, gunkata configures nothing global.** Every module logger is
  `logging.getLogger(__name__)`, and every module lives under the `gunkata`
  package, so every logger is a descendant of `"gunkata"` by construction --
  no separate root-name constant is needed to state or guard that. A caller
  embedding gunkata configures the `"gunkata"` logger's level and handlers
  itself, the same way it would any other subsystem.
  `configure_logging`/`$GUNKATA_LOG_LEVEL` is the CLI entry point's own
  convenience, never called from library code, since it reaches past
  gunkata's hierarchy to the real root logger. No `NullHandler` is attached
  on import: `logging.lastResort` already covers an unconfigured caller, and
  `__init__.py` holds no logic to attach one with. Guarded by
  `test_every_logger_descends_from_package_root` in
  `tests/test_logging_config.py`.
- <Optionally: persist every record to a per-component `journal.jsonl` and
  read it back through a `<tool> logs` CLI command — the one supported
  observation surface. A monitoring gap means the logging is inadequate; fix
  that rather than grepping files.>

# CLI

- **The CLI is built on Typer, exposed as the single `gunkata` console script**
  (`gunkata.cli.main:main`). One shared `app`, defined once in `gunkata/cli/app.py`;
  every command module imports it and registers on it, never a second Typer
  app or a second entry point. No guard: a second app or entry point is a
  wiring choice no scan of a single module reveals.
- **`gunkata/cli/` holds one module per command** (`addr.py`, `procmaps.py`,
  ...), named for the command. A command that is itself a group of
  subcommands (`mem read`/`mem write`) gets one module for the group, since
  its subcommands share a sub-app and helpers. Infrastructure more than one
  command needs — completion (`completion.py`), fzf picking (`fzf.py`), tty
  detection (`tty.py`) — gets its own shared module; a command module imports
  what it needs by name so tests can monkeypatch it on that command's own
  namespace. No guard: which module a command's code landed in is a layout
  fact only a reviewer checks.
- **Every command scopes to a device with a bare `Adb()`.** `Adb.__init__`
  resolves which device by priority: an explicit serial argument, then
  `$ANDROID_SERIAL`, else auto-detecting the sole connected device (raising
  on zero or multiple) -- the same environment variable real `adb` itself
  honors. No *subcommand* takes its own serial option. Guarded by
  `test_adb.py`.
- **`gunkata`'s own root callback carries `-s`/`-U`/`-C`, mirroring `adb -s`:
  a global option that must precede the subcommand it affects, rather than
  being repeated on every command that needs it.** `-s` and `-U` set
  `$ANDROID_SERIAL` and `$GUNKATA_SHELL_DEFAULT_USER` for the invocation --
  the same two environment variables `Adb.__init__` and `ShellSettings`
  already resolve on their own, so the root option is equivalent to
  exporting either variable before running `gunkata`, and no subcommand or
  core class gained a new parameter to carry them. `-C` has no such setting:
  it is `gunkata shell`'s own chdir-before-attach value, with exactly one
  consumer, so it travels there via `ctx.obj` rather than becoming a
  `GUNKATA_*` variable no other command would ever read. Guarded by
  `test_root_serial_option_sets_android_serial_before_the_subcommand_runs`
  and `test_root_user_option_sets_the_default_user_env_var_before_the_subcommand_runs`
  in `tests/cli/test_app.py`;
  `test_shell_command_honors_the_root_chdir_option` and
  `test_shell_attaches_in_the_root_chdir_option_when_no_command_is_given` in
  `tests/cli/test_shell.py`.
- **A command body is presentation only** — parse args, call into
  `gunkata.core`, render the result. No logic in the command; that lives in
  core. No guard: whether a command module holds logic beyond parsing and
  rendering is a judgement on its code, not a pattern to grep for.
- **Marshalling user-facing syntax is a CLI concern, not core's.** Parsing a
  CLI-specific string format — an address expression, a name resolved to a
  pid — into the plain value a core class's method takes lives in the command's
  own module under `gunkata/cli/`. A core class stays a lean API: its methods
  take resolved values (`int`, `bytes`, a real object), never a string a user
  typed at it. No guard: whether a core method takes a resolved value or a
  user string is a judgement on its signature, not a fixed pattern.

- **`gunkata shell` always replaces this process with `adb shell`, and asks
  for a device pty only when stdin *and* stdout are terminals.** Capturing a
  command to echo at exit shows nothing until it exits, so a program that
  never exits or draws a UI shows nothing at all; and a pty merges stderr into
  stdout and translates newlines, so a redirected stream must not get one --
  adb's own `-t` consults stdin alone and would. See `Shell.execvp_sh`'s
  `Design:` note. Guarded by
  `test_execvp_sh_runs_a_command_instead_of_attaching_when_given_one` and
  `test_execvp_sh_omits_the_pty_flag_when_no_pty_was_asked_for` in
  `tests/test_shell.py`;
  `test_shell_command_execs_adb_rather_than_capturing_the_command` and
  `test_shell_asks_for_a_pty_only_when_both_streams_are_terminals` in
  `tests/cli/test_shell.py`.

- **`gunkata scrcpy`'s frame outlives the scrcpy content it hosts; only
  scrcpy is ever relaunched.** `ScrcpySession` starts one `Xephyr` for the
  whole session and never a second one -- any scrcpy exit, a device reboot
  included, is followed by awaiting the device and relaunching scrcpy into
  that same frame. This is why the window's position and size need no
  persistence: the frame is an ordinary window no WM ever unmaps or remaps,
  so it stays exactly where it was put. See `ScrcpySession`'s `Design:` note.
  Guarded by `test_a_device_reboot_relaunches_scrcpy_into_the_same_frame` and
  `test_the_frame_dying_ends_the_session_and_reaps_scrcpy` in
  `tests/scrcpy/test_session.py`.
- **scrcpy is launched against the frame's own X display, never the host's,
  with `SDL_VIDEODRIVER=x11` and no `WAYLAND_DISPLAY`.** In a Wayland
  session, SDL can otherwise pick a Wayland backend and open scrcpy's window
  on the host compositor, escaping the frame while appearing to work. See
  `ScrcpySession._launch`'s `Design:` note. Guarded by
  `test_scrcpy_runs_against_the_frame_display_never_the_host` in
  `tests/scrcpy/test_session.py`.
- **No *host* window manager is ever consulted by `gunkata scrcpy`** -- no
  `i3-msg`, `xdotool`, `wmctrl`, `xprop`, or `xwininfo` in any argv it
  builds. This is the entire portability mechanism: the frame persisting
  is what survives a reboot, not anything read from or written to the
  host's WM, so the command behaves identically under a tiling or floating
  WM, X11 or XWayland. `matchbox-window-manager` running *inside* the
  nested display is a different thing entirely -- see the next entry --
  and is deliberately excluded from this guard rather than being what it
  guards against. Guarded by `test_no_window_manager_is_ever_consulted` in
  `tests/scrcpy/test_xephyr.py`.
- **`Xephyr` runs `matchbox-window-manager` inside its own nested display,
  alongside scrcpy.** Verified against a live emulator: with no WM inside
  the nested display at all, scrcpy's SDL window has nothing to size or
  position it against and opens at its own preferred size in a corner,
  never filling the frame regardless of `--fullscreen` -- and unlike the
  host WM above, this is not optional. matchbox is frame-scoped, not
  scrcpy-scoped: `Xephyr._start`/`_stop` own its lifetime, so it outlives
  every scrcpy relaunch rather than being restarted alongside one. See
  `Xephyr`'s `Design:` note. Guarded by
  `test_matchbox_is_started_inside_the_frames_own_display` and
  `test_a_missing_matchbox_binary_names_the_package_and_stops_the_frame`
  in `tests/scrcpy/test_xephyr.py`.
- **scrcpy is launched with no window position or size at all.** The nested
  screen follows whatever size the host WM gives the frame, so any geometry
  named at launch is right only until the first resize; matchbox maximizes
  scrcpy against the nested screen's current size instead. See
  `ScrcpySession._argv`'s `Design:` note. Guarded by
  `test_scrcpy_argv_carries_the_serial_and_extra_args` and
  `test_scrcpy_is_never_given_a_window_geometry` in
  `tests/scrcpy/test_session.py`.
- **`Xephyr` always passes `-resizeable`, and that is what makes the frame
  tile.** Verified live: with it Xephyr sets no `WM_NORMAL_HINTS` and i3
  tiles the frame like any other window, the nested screen following each
  tile size through RandR. **Tombstone: a build that drops `-resizeable`
  shipped once and must not come back** -- Xephyr then declares min size ==
  max size, which i3 auto-floats, and a WM forced to tile it anyway exposes
  outer window past the nested screen that Xephyr never paints, showing
  stale pixels there. See `Xephyr`'s `Design:` note. Guarded by
  `test_the_nested_screen_is_resizeable` in `tests/scrcpy/test_xephyr.py`.
- **The frame opens at the host screen's size, and no option sets that
  size.** Measured against a live emulator: Xephyr confines the pointer to the
  screen size it opened with, and a RandR resize never widens that box -- two
  clicks 500px apart beyond the old boundary landed on the *same* device pixel,
  which reaches the user as clicks that miss by more the further from the
  origin they are. The host screen is the largest rectangle any WM can give the
  frame, so opening there keeps all of it clickable; shrinking is always safe,
  growing past the opening size is what strands clicks. **Tombstone:
  `frame_width`/`frame_height` settings and `-W`/`-H` options shipped and were
  removed for exactly this -- any size a user can choose is a size the WM can
  exceed.** See `Xephyr._host_screen_size`'s `Design:` note. Guarded by
  `test_the_frame_opens_at_the_host_screens_size` and
  `test_no_host_display_is_refused_before_anything_starts` in
  `tests/scrcpy/test_xephyr.py`; `test_scrcpy_takes_no_frame_size_options` in
  `tests/cli/test_scrcpy.py`.
- **The host X server and a running i3 older than the tested versions get a
  loud warning at startup, phrased as untested rather than broken.** Asked for
  explicitly, to warn before a resize can strand clicks -- the measured check
  below can only speak after one. `_TESTED_HOST_X_RELEASE` (X.Org 21.1.22) and
  `_TESTED_I3_VERSION` (4.25.1) are the only versions the bound was measured
  correct on; the stale bound appeared on X.Org 21.1.12 with i3 4.23, so with
  two samples differing in both, neither number is a fix point and everything
  between is untested -- which is why the wording claims no defect. i3 is
  identified from `_NET_SUPPORTING_WM_CHECK`, never from being on PATH, so an
  i3 installed beside another WM is never warned about. Guarded by
  `test_an_old_host_x_server_warns_loudly`, `test_an_old_i3_warns_loudly`,
  `test_an_i3_that_is_not_the_running_wm_is_not_warned_about`, and
  `test_a_tested_host_warns_about_nothing` in `tests/scrcpy/test_xephyr.py`.
- **After every resize, the pointer bound is measured, never inferred from a
  version.** Some X servers keep bounding the pointer to a rectangle from when
  the frame was smaller -- measured on another machine: 1885x687 inside a
  1885x1045 screen, stranding every click past it, permanently for that frame.
  The same Xephyr build (21.1.12) does *not* do this here, and 21.1.12/18/22
  all pass a shrink-then-grow probe locally, so **there is no version test that
  would be honest**: `Xephyr.check_pointer_reaches_the_screen` warps to the last
  pixel, sees where the pointer lands, warns naming the bound, and puts the
  pointer back. `ScrcpySession` calls it on a resize *after* reaping scrcpy, so
  the probe's own motion cannot reach the device. See that method's `Design:`
  note.
  Guarded by `test_a_pointer_bounded_short_of_the_screen_warns_loudly`,
  `test_a_pointer_that_reaches_the_screen_warns_about_nothing`, and
  `test_the_pointer_probe_puts_the_pointer_back` in
  `tests/scrcpy/test_xephyr.py`;
  `test_a_resize_checks_that_the_pointer_still_reaches_the_screen` in
  `tests/scrcpy/test_session.py`.
- **A frame resize replaces scrcpy; it is never left to re-fit itself.**
  Verified on a real device: clicks land progressively too high after the
  frame is resized, because scrcpy keeps mapping them against the geometry it
  started with, while a freshly launched scrcpy is accurate. `ScrcpySession`
  compares `Xephyr.screen_size()` against the size the running scrcpy was
  launched against and relaunches on a change, reusing the path a device drop
  already takes rather than adding a second way to replace scrcpy -- and that
  relaunch must never count toward `launch_failure_limit`, since a resize can
  land moments after a launch. `screen_size` re-reads the root window every
  call, never `Display.screen()`'s handshake-captured `width_in_pixels`. See
  `ScrcpySession._await_exit`'s `Design:` note. Guarded by
  `test_a_frame_resize_relaunches_scrcpy` and
  `test_a_resize_relaunch_is_not_counted_as_a_launch_failure` in
  `tests/scrcpy/test_session.py`;
  `test_screen_size_reports_the_frames_current_size` and
  `test_a_frame_display_that_refuses_a_connection_is_named` in
  `tests/scrcpy/test_xephyr.py`.
- **The frame's placeholder is the one thing in `gunkata scrcpy` that
  degrades instead of raising.** Measured: an empty nested screen is a
  uniform `#000000`, indistinguishable from a dead frame, so `xmessage`
  carries a message naming the device, started *after* matchbox so matchbox
  maximizes it and re-maximizes it on every resize. Its own `-bg` is the
  whole background, since `xsetroot -solid` returns 0 against a Xephyr root
  and leaves it black -- also measured, which is why nothing here paints the
  nested root. The binary is not needed to mirror a device, so its absence
  is logged once and skipped -- the declared policy that keeps this from
  being a library default nobody chose. See
  `Xephyr._start_placeholder`'s `Design:` note. Guarded by
  `test_the_placeholder_is_painted_inside_the_frame`,
  `test_the_placeholder_is_started_after_matchbox`, and
  `test_a_missing_placeholder_binary_is_logged_and_skipped` in
  `tests/scrcpy/test_xephyr.py`;
  `test_the_frames_placeholder_names_the_device` in
  `tests/scrcpy/test_session.py`.
- **SIGTERM and SIGHUP are treated the same as Ctrl-C for the duration of
  `gunkata scrcpy`'s own run.** Verified live: a plain `kill <pid>` on the
  unpatched command left Xephyr, matchbox, and scrcpy all orphaned, since
  neither signal has SIGINT's default translation into a Python exception --
  their default action ends the process immediately, skipping every
  `finally` `ScrcpySession.run` unwinds through. The command installs
  handlers that raise `KeyboardInterrupt` for the call's duration only,
  restoring whatever handler was there before in a `finally`, so nothing
  leaks into the rest of the process. See `cli/scrcpy.py`'s inline comment.
  Guarded by `test_scrcpy_treats_sigterm_the_same_as_a_keyboard_interrupt` and
  `test_scrcpy_restores_the_previous_sigterm_handler_after_running` in
  `tests/cli/test_scrcpy.py`.
- **`ScrcpyRepo.resolve` returns a path to keep, not a temp file to
  push-and-delete like `frida.repo.ServerRepo.extracted`.** The scrcpy binary
  is re-executed by this host for the life of the session rather than pushed
  to a device, so extraction is idempotent -- a second `resolve` of the same
  version/arch is a pure filesystem check, no archive lookup, no network. A
  freshly downloaded archive's SHA-256 is checked against the release's own
  `SHA256SUMS.txt` before extraction; `frida.repo.ServerRepo` has no matching
  step, since its binary is pushed to a device and never executed by this
  host at all. See `ScrcpyRepo`'s `Design:` note. Guarded by
  `test_a_second_resolve_does_not_re_extract` and
  `test_a_checksum_mismatch_removes_the_archive_and_refuses` in
  `tests/scrcpy/test_repo.py`.

## Adding a command

1. Create `gunkata/cli/<command>.py`; `from gunkata.cli.app import app`, define
   the function, decorate with `@app.command()`.
2. Import shared infrastructure (`completion.complete_process_name`,
   `fzf.fzf_pick_pid`, `tty.stdout_is_tty`/`stdin_is_tty`) by name, not the
   whole module, so a test can monkeypatch the command module's own reference.
3. Register the module in `gunkata/cli/main.py`'s import list — a command with
   no consumer there never runs; Typer only sees modules main.py imports.
4. Add `tests/cli/test_<command>.py`, mirroring the module it tests (see
   `test_addr.py`, `test_procmaps.py`).

## Adding a subcommand group

For a command that is itself a group (`mem read`/`mem write`, `device
name`/`device tag add`/`device tag remove`):

1. Create `gunkata/cli/<group>.py` with its own `<group>_app = typer.Typer(...)`,
   then `app.add_typer(<group>_app, name="<group>")`. A subcommand of the
   group that is itself a group (`device tag`) gets its own nested `typer.Typer`
   the same way, added to `<group>_app` instead of `app`.
2. Decorate each subcommand with `@<group>_app.command("<name>")` (or the
   nested sub-app's). Shared helpers used by more than one subcommand live as
   module-level functions in the same file, not duplicated per subcommand —
   see `mem.py`'s `_resolve_mem_pid`.
3. Register the module in `gunkata/cli/main.py`'s import list, same as a
   single-command module.
4. Add `tests/cli/test_<group>.py` covering every subcommand, mirroring
   `test_mem.py`/`test_device.py`.

# Python Code Conventions

- Prefer `Protocol` over ABC when default method implementations are unlikely.
- Always write class docstrings. Write method/function docstrings unless
  trivial. A docstring that restates its own definition is worse than absent.
- **Docstrings are Google-style, contract first and rationale last.** Summary
  line, then `Args:`, `Returns:`, `Raises:`, then `Design:` for the why.
  `Returns:` states the shape invariant and domain meaning, never the type —
  the annotation already gives the type. Split contract from rationale at the
  *clause*: a `because` inside a contract section is the tell a split was
  missed. No guard: no linter in this repo parses docstring prose for a
  misplaced rationale.
- **A `Raises:` entry is `ExceptionName: condition.`** Prose passes every lint
  and documents no exception at all. Document what a caller must catch,
  including exceptions merely propagated. No guard: no linter in this repo
  checks a `Raises:` entry against the exceptions a function actually raises.
- OOP by default: no module-level functions unless the module is a
  helper/utility collection.
- One class per module. Exception: dataclasses tightly coupled to the class —
  the schemas it directly consumes or produces.
- **`__init__.py` holds no logic** — a package docstring only, at most re-exports
  of names defined in sibling modules. Code lives in a named module (a
  command's own module under `gunkata/cli/`), never in the package marker.
  No guard: no linter in this repo distinguishes a re-export from logic in
  an `__init__.py`.
- Schema vs processor: a data schema goes in `types.py`; a processor gets its
  own module. Schemas mirror dependency structure — if B exists only because
  of A, nest B under A.
- **A settings class is colocated with its sole consumer** — `ShellSettings`
  and `SuSettings` live in `shell.py`/`su.py` beside `Shell`/`Su`, `LogSettings`
  in `cli/logging_config.py` beside `configure_logging`. Once a second
  consumer needs it, colocation would force one consumer's module to import
  the other's — move it out to its own `settings.py` instead, the way
  `FridaSettings` serves both `FridaServer` and `ServerRepo` from
  `frida/settings.py`. No guard: whether a settings class has gained a
  second consumer is a fact about the import graph no CLAUDE.md rule tracks.
- **One level of generic nesting is the limit — name the structure.** Good:
  `list[str]`, `dict[str, int]`. Bad: `dict[int, list[tuple[set[str], int]]]`.
  A data shape that needs more gets a `@dataclass`; a callable shape that
  needs more than bare `Callable` gets a `Protocol` with a named `__call__`.
  No guard: no linter in this repo counts generic nesting depth.
- **Cohering arguments become a type.** When the same cluster of parameters
  recurs across call sites and together describes one entity, introduce a
  dataclass. Domain objects over loose primitives. No guard: recognizing a
  recurring cluster of parameters as one entity is a judgement call.
- **`if TYPE_CHECKING:` is forbidden — a cycle it would hide is a placement
  error.** Move the type to `types.py` or a third module instead. No guard:
  no linter in this repo forbids the `TYPE_CHECKING` import guard.
- Absolute imports for anything above the current package; relative only for
  siblings. All imports at module top; function-local only for a genuine
  circular import or a legitimately lazy heavy dependency.
- **Name a boolean after the state that carries consequence**; avoid negated
  names (`is_not_x`, `disabled`). Put the positive name on the informative
  state so `not x` never reads as a double negative. No guard: no linter in
  this repo flags a negated boolean name.
- **Never catch a bare `except Exception` unless justified** — narrow to what
  you expect. A broad catch is only justified at a genuine resilience boundary
  (one bad item must not sink the batch); even then, log the exception with
  context and comment the justification. No guard: no linter in this repo is
  configured to flag a bare `except Exception`.

# Tests

- `pytest` exclusively. Never import `unittest` — use `pytest.raises`,
  fixtures, `monkeypatch`, `tmp_path`, `capsys`, `caplog`.
- Non-trivial tests carry a docstring: WHAT is tested, WHY, and the expected
  outcome. Trivial tests whose name says it all need none.
- **Every test gets an isolated `GUNKATA_ROOT`.** Guarded by the autouse
  `isolated_gunkata_root` fixture in `tests/conftest.py`, whose docstring says
  why. A test that reads the developer's own persisted device settings passes
  or fails according to whose machine ran it; an emulator test that needs a
  setting stores it under `tmp_path` itself, as
  `test_completes_against_real_device` does.
- Do not test API conformance (that a method returns a given type, that a
  class has a field).

# Definition of Done

A change is done when the **whole** suite is green — never just the package's:

```bash
scripts/check.sh
```

The per-module run is the inner loop, not the gate — two failure classes are
invisible to it: construction/wiring (guard with a smoke test per CLI
command), and cross-package invariants (a rule stated in one package is
routinely guarded in another).

**Every gate this repo has is run from `scripts/check.sh`: ruff, then an
`mkdocs build --strict`, then the suite.** When there is no CI, this script
is the whole of it. No guard: whether it was actually run before calling a
change done is known only to whoever ran it.

**`scripts/check.sh` deselects `-m emulator` tests; the maintainer owns
running them separately, `uv run pytest -m emulator` against a device
`scripts/run_emulator.sh` boots** — no CI or gate here has a real device to
target. No guard: which tests are marked `emulator` is a fact about the
suite, not about this script.

# Branches & Worktrees

- **Never check out a branch in the root checkout — always use a worktree.**
  Switching branches at the root silently redirects every subsequent edit.
  No guard: by the time a pre-commit hook fires, the checkout has already
  happened and the damage is done.
- **Create worktrees under `.claude/worktrees/`, never as a sibling of the
  repo.** A sibling directory (`../gunkata-<branch>`) is easy to lose track
  of and easy to `rm -rf` by mistake when tidying up the parent directory.
  No guard: a sibling directory is outside this repository, where none of
  its hooks run.
- **A feature gets a branch and a worktree; the gate is the merge, not the
  commit.** Commit to the branch freely; never merge into the default branch
  without being asked. "Commit this" is not "merge this". No guard: which
  merges were asked for is known only to the person who asked; a hook cannot
  tell a sanctioned merge from a stray one.
- Verify the base ref before creating a worktree; confirm the current branch
  before committing.

# Publishing

- **Never publish this package to PyPI (or any other index) without the
  maintainer's explicit, per-release approval.** `uv publish`, `twine upload`, a
  release workflow, or any equivalent is forbidden until the maintainer says so
  for that specific upload. A green build, a version bump, or approval of an
  earlier release is never approval for the next one. An uploaded version can
  never be replaced, only yanked — so the gate is before the upload, not after.
  No guard: whether a specific upload had the maintainer's approval is known
  only to the parties of that conversation.
