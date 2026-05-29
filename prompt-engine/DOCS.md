# prompt-engine — Developer Reference

The prompt-engine is a **deterministic prompt compiler**. It takes a natural-language goal,
classifies it into a structured task, pulls relevant repo context from the symbol index,
enforces task-appropriate constraints, and emits a structured, budget-capped prompt.
No LLM is invoked by the engine itself.

---

## Table of Contents

1. [How the pipeline works](#1-how-the-pipeline-works)
2. [Installation](#2-installation)
3. [CLI quick reference](#3-cli-quick-reference)
4. [Verb commands](#4-verb-commands)
5. [Flags reference](#5-flags-reference)
6. [Task types](#6-task-types)
7. [Modes](#7-modes)
8. [Constraints](#8-constraints)
9. [Presets](#9-presets)
10. [Profiles](#10-profiles)
11. [Output contracts](#11-output-contracts)
12. [Config file](#12-config-file)
13. [Python API](#13-python-api)
14. [Repo-index integration](#14-repo-index-integration)
15. [Architecture](#15-architecture)
16. [Extending the engine](#16-extending-the-engine)

---

## 1. How the pipeline works

```
natural-language goal
        │
        ▼
  ┌─────────────┐
  │  Classifier  │  intent.py — keyword scoring, mode detection, scope extraction
  └─────────────┘
        │  TaskType + Mode + SubType + Scope + confidence
        ▼
  ┌─────────────┐
  │  Task builder│  intent.build_task() — constraints, budget, retrieval plan, verification plan
  └─────────────┘
        │  Task (fully typed internal model)
        ▼
  ┌─────────────┐
  │  Retrieval   │  retrieval.retrieve() — queries repo-index, ranks symbols, pulls git context
  └─────────────┘
        │  ContextBundle (symbols + git diff + raw_text)
        ▼
  ┌─────────────┐
  │  Compiler    │  compiler.compile_task() — assembles ordered PromptBlocks, enforces budget
  └─────────────┘
        │  PromptPlan (ordered blocks, token estimate)
        ▼
  plan.compile()        → single string   (feed to any LLM)
  plan.to_messages()    → messages list   (OpenAI / Anthropic format)
```

The pipeline is **fully deterministic** — same goal + same index → same prompt every time.
Nothing is sampled or randomized.

### Prompt block structure

Every compiled prompt consists of ordered blocks:

| Priority | Block | Source |
|---|---|---|
| 10 | `system` | Universal policy + mode addendum + repo policy |
| 20 | `task` | Task type, goal, scope, mode, risk level |
| 30 | `constraints` | Constraint list for this task type + mode |
| 40 | `context` | Retrieved symbols + git diff (or placeholder) |
| 50 | `output_contract` | Structured response format for this task type |
| 60 | `verification` | Required checks and warning conditions |

---

## 2. Installation

```bash
# From the repo root
pip install -e prompt-engine/

# Verify
ai --help
ai show tasks
```

The `ai` command is registered via `pyproject.toml` entry point `prompt_engine.cli:app`.

**Optional dependency:** `repo-index` for symbol retrieval. Without it the engine still works —
context blocks fall back to a placeholder that prompts the user to paste context manually.

```bash
pip install -e repo-index/      # enables automatic context retrieval
repo-index build .              # index the current repo
```

---

## 3. CLI quick reference

```
ai fix    GOAL [options]     Fix a bug
ai feat   GOAL [options]     Implement a feature
ai ref    GOAL [options]     Refactor without changing behavior
ai test   GOAL [options]     Generate tests
ai debug  GOAL [options]     Investigate a problem
ai explain GOAL [options]    Explain how code works
ai opt    GOAL [options]     Optimize for performance
ai migrate GOAL [options]    Plan a migration
ai review GOAL [options]     Review code
ai secure GOAL [options]     Fix or audit a security issue
ai clean  GOAL [options]     Remove dead code / stale patterns
ai observe GOAL [options]    Add logging / metrics / tracing

ai run    GOAL [options]     Infer task type automatically
ai plan   GOAL [options]     Show task plan only (no compiled prompt)
ai inspect GOAL [options]    Show compiled prompt

ai show tasks                All task types
ai show task <name>          One task type in detail
ai show modes                All modes
ai show constraints          All constraints
ai show presets              All presets
ai show profiles             All profiles
ai show policy               Active policy

ai init [--force]            Write default global config
```

---

## 4. Verb commands

Each verb maps to a specific `TaskType` with pre-wired defaults. Using a verb is preferred
over `ai run` because it gives a stronger prior — the classifier confidence is 1.0 and the
output contract, default mode, and default constraints are all task-specific.

### `ai fix` — bugfix

```bash
ai fix 'null pointer in UserService.getById when id is 0'
ai fix 'payment double-charge on retry' --preset bugfix/safe
ai fix 'race condition in session cache' --mode deep --scope session
ai fix 'auth regression since v2.3' --explain
```

Default mode: `surgical` | Default risk: `medium`

Default constraints: `minimal_diff`, `preserve_public_api`, `no_unrelated_refactors`,
`require_tests`, `require_explanation`, `require_risk_analysis`, `follow_existing_patterns`,
`no_speculative_cleanup`

Output contract: `symptom`, `root_cause`, `trigger`, `affected_code_paths`, `fix_strategy`,
`patch`, `tests`, `regression_risks`, `assumptions` (optional)

---

### `ai feat` — feature

```bash
ai feat 'add rate limiting to the /auth/token endpoint'
ai feat 'webhook delivery retry with exponential backoff' --preset feature/surgical
ai feat 'background job for stale session cleanup' --scope session --mode deep
```

Default mode: `deep` | Default risk: `medium`

Default constraints: `follow_existing_patterns`, `require_tests`, `require_explanation`,
`no_unnecessary_abstractions`, `avoid_new_dependencies`

Output contract: `goal`, `design_choice`, `affected_interfaces`, `patch`, `tests`,
`compatibility_notes`, `risks`, `migration_notes` (optional)

---

### `ai ref` — refactor

```bash
ai ref 'extract payment logic from OrderService into PaymentService'
ai ref 'decouple auth middleware from route handlers' --preset refactor/compatibility
ai ref 'consolidate the three DB helpers into db_utils' --scope db
```

Default mode: `safe` | Default risk: `medium`

Default constraints: `preserve_public_api`, `preserve_behavior`, `no_unrelated_refactors`,
`require_tests`, `require_risk_analysis`, `keep_file_churn_low`, `follow_existing_patterns`

Output contract: `current_shape`, `target_shape`, `migration_path`, `patch`, `compatibility`,
`risk_analysis`, `tests`

---

### `ai test` — test_generation

```bash
ai test 'generate tests for the retrieval bridge'
ai test 'unit tests for search_symbols_ranked' --scope repo_index
ai test 'integration tests for /auth/token' --preset test/coverage-first
```

Default mode: `surgical` | Default risk: `low`

Default constraints: `follow_existing_patterns`, `require_explanation`, `prefer_existing_helpers`

Output contract: `coverage_plan`, `fixtures`, `tests`, `gaps` (optional)

---

### `ai debug` — debugging

```bash
ai debug 'flaky timeout in the websocket handler'
ai debug 'intermittent 500 on /api/search under concurrent load'
ai debug 'deadlock in session store' --preset debug/deep
```

Default mode: `debug` | Default risk: `low`

Default constraints: `no_guessing`, `require_explanation`, `require_risk_analysis`

Output contract: `reproduction`, `evidence`, `likely_cause`, `uncertainty`, `next_steps`,
`patch_if_applicable` (optional)

---

### `ai explain` — explanation

```bash
ai explain 'how does the composite ranking score work'
ai explain 'walk me through the prompt compilation pipeline'
ai explain 'what does build_call_graph_cached do and why is it keyed by id(conn)'
```

Default mode: `deep` | Default risk: `low`

Default constraints: `no_guessing`, `require_explanation`

Output contract: `summary`, `key_concepts`, `data_flow`, `invariants` (optional),
`gotchas` (optional)

---

### `ai opt` — optimization

```bash
ai opt 'reduce allocations in the hot path of search_symbols_ranked'
ai opt 'the FTS5 query is slow on large indexes' --scope db
ai opt 'build_call_graph rebuilds on every MCP call' --mode surgical
```

Default mode: `deep` | Default risk: `medium`

Default constraints: `preserve_behavior`, `no_performance_regression`, `require_explanation`,
`require_risk_analysis`

Output contract: `bottleneck`, `evidence`, `fix_strategy`, `patch`, `expected_gain`, `risks`

---

### `ai migrate` — migration

```bash
ai migrate 'move from SQLite FTS4 to FTS5'
ai migrate 'rename repo_root column in meta table' --preset migration/careful
ai migrate 'replace the per-connection graph cache with a module-level LRU'
```

Default mode: `safe` | Default risk: `high`

Default constraints: `no_backward_compat_break`, `no_schema_change_without_migration`,
`require_explanation`, `require_risk_analysis`

Output contract: `scope`, `compatibility_constraints`, `migration_steps`, `rollback_plan`,
`backfill_needs`, `risks`, `patch`

---

### `ai review` — code_review

```bash
ai review 'check the new FTS5 migration for safety'
ai review 'audit the MCP server tools for input validation' --preset review/strict
ai review 'look at the graph cache changes before merging'
```

Default mode: `strict` | Default risk: `low`

Default constraints: `no_guessing`, `require_explanation`

Output contract: `issues_found`, `severity_summary`, `rationale`, `suggested_changes`,
`non_issues`, `confidence`

---

### `ai secure` — security

```bash
ai secure 'SQL injection in the symbol search query'
ai secure 'JWT secret is logged in debug output'
ai secure 'audit input validation on all MCP tool parameters' --preset security/strict
```

Default mode: `strict` | Default risk: `high`

Default constraints: `no_security_regression`, `no_guessing`, `require_explanation`,
`require_risk_analysis`, `preserve_behavior`

Output contract: `vulnerability`, `attack_vector`, `affected_paths`, `fix_strategy`, `patch`,
`verification`, `related_risks` (optional)

---

### `ai clean` — cleanup

```bash
ai clean 'remove dead code in the indexer module'
ai clean 'delete unused imports across the prompt_engine package'
ai clean 'clear stale TODO comments in retrieval.py' --scope retrieval
```

Default mode: `surgical` | Default risk: `low`

Default constraints: `follow_existing_patterns`, `no_speculative_cleanup`

Output contract: `summary`, `changes`, `rationale`, `risks`

---

### `ai observe` — observability

```bash
ai observe 'add structured logging to the MCP server tools'
ai observe 'instrument retrieve() with latency and symbol-count metrics'
ai observe 'add a warning log when the graph cache is rebuilt'
```

Default mode: `surgical` | Default risk: `low`

Default constraints: `no_logging_noise`, `follow_existing_patterns`

Output contract: `summary`, `changes`, `rationale`, `risks`

---

## 5. Flags reference

These flags apply to all verb commands and to `ai run`.

### `--mode MODE` / `-m MODE`

Override the default reasoning mode. See [§7 Modes](#7-modes) for what each mode does.

```bash
ai fix 'payment double-charge' --mode deep       # thorough root cause
ai ref 'extract payment service' --mode safe     # conservative refactor
ai feat 'add caching' --mode explore             # compare 2-3 approaches first
```

### `--scope SCOPE` / `-s SCOPE`

Hint the module, service, or file that is the focus. Guides both the FTS retrieval query
and the context window prioritization.

```bash
ai fix 'null pointer' --scope user_service
ai feat 'add rate limiting' --scope 'auth middleware'
ai debug 'flaky test' --scope payment_tests.py
```

### `--preset PRESET`

Apply a named preset. Presets bundle a task type + mode + extra constraints so you don't
have to specify them separately. See [§9 Presets](#9-presets).

```bash
ai fix 'data loss on retry' --preset bugfix/safe
ai ref 'public API cleanup' --preset refactor/compatibility
ai review 'new auth PR' --preset review/strict
```

### `--profile PROFILE`

Apply an execution profile on top of the task type. Profiles set a mode and may add
constraints without specifying a task type. See [§10 Profiles](#10-profiles).

```bash
ai feat 'add webhook support' --profile strict
ai debug 'flaky test' --profile fast
```

### `--explain`

Show the task plan without printing the compiled prompt. Displays:
- Task type, mode, risk, confidence score
- Classification evidence (which keywords matched and their weights)
- Retrieved symbols with call chains
- Active constraints
- Output contract fields
- Token budget breakdown

Use this to verify the engine understood your intent correctly.

```bash
ai fix 'null pointer in auth' --explain
ai run 'the search is broken' --explain          # check what task type it picked
```

### `--dry-run`

Show the full task plan **plus** the compiled prompt below it.
The prompt is exactly what would be sent to an LLM.

```bash
ai feat 'add rate limiting' --dry-run
ai ref 'extract payment service' --dry-run --mode safe
```

### `--compact`

Print only the raw compiled prompt string — no Rich panels, no plan summary.
Useful for piping to an LLM CLI or copying to clipboard.

```bash
ai fix 'null pointer' --compact | pbcopy
ai fix 'null pointer' --compact | llm                  # pipe to any LLM CLI
ai fix 'null pointer' --compact > /tmp/prompt.txt
```

### `--safe`

Shortcut for `--mode safe`. Conservative changes, flag every risk.

```bash
ai ref 'extract service layer' --safe    # same as --mode safe
```

### `--strict`

Shortcut for `--mode strict`. Explicit assumptions, verbose output, no guessing.

```bash
ai review 'new PR' --strict              # same as --mode strict
```

### `--preserve-api`

Add the `preserve_public_api` constraint — no public interface or exported symbol may change.
Applied on top of the default constraints for the task type.

```bash
ai ref 'internal cleanup of db module' --preserve-api
```

### `--no-tests`

Remove the `require_tests` constraint. The output does not need to include or reference tests.

```bash
ai fix 'typo in error message' --no-tests
ai clean 'remove dead code' --no-tests
```

### `--no-retrieve`

Skip the repo-index symbol lookup entirely. The context block will be a placeholder
that prompts the LLM to ask you for the relevant code.

Use when:
- The index hasn't been built yet
- The index is stale and you don't want stale context
- You want to supply context manually in a follow-up message

```bash
ai fix 'null pointer' --no-retrieve
ai test 'write tests for X' --no-retrieve    # you'll paste the source yourself
```

---

## 6. Task types

| Type | CLI verb | Default mode | Default risk |
|---|---|---|---|
| `bugfix` | `fix` | surgical | medium |
| `feature` | `feat` | deep | medium |
| `refactor` | `ref` | safe | medium |
| `test_generation` | `test` | surgical | low |
| `debugging` | `debug` | debug | low |
| `explanation` | `explain` | deep | low |
| `optimization` | `opt` | deep | medium |
| `migration` | `migrate` | safe | high |
| `code_review` | `review` | strict | low |
| `security` | `secure` | strict | high |
| `cleanup` | `clean` | surgical | low |
| `observability` | `observe` | surgical | low |
| `performance` | — | deep | medium |
| `reliability` | — | safe | medium |
| `architecture` | — | architectural | high |
| `documentation` | — | minimal | low |
| `data_migration` | — | safe | critical |

To see the full contract for any type:

```bash
ai show task bugfix
ai show task migration
ai show task security
```

---

## 7. Modes

Modes control three things: **context depth** (how many symbols and tokens to pull),
**constraint set** (which extra constraints are added), and **output verbosity**
(whether optional contract fields are included).

| Mode | Token budget | Retrieval depth | Output | Extra constraints |
|---|---|---|---|---|
| `surgical` | 6 000 | 2 | normal | minimal_diff, no_guessing, keep_file_churn_low |
| `deep` | 16 000 | 4 | verbose | — |
| `fast` | 4 000 | 1 | compact | — |
| `safe` | 10 000 | 3 | normal | preserve_behavior, no_behavioral_surprises, require_risk_analysis |
| `explore` | 8 000 | 2 | normal | — |
| `strict` | 10 000 | 3 | verbose | require_explanation, require_risk_analysis, no_guessing |
| `minimal` | 3 000 | 1 | compact | minimize_token_usage, minimal_diff |
| `architectural` | 12 000 | 3 | verbose | — |
| `debug` | 8 000 | 2 | normal | — |
| `rewrite` | 8 000 | 2 | normal | — |
| `maintain` | 8 000 | 2 | normal | follow_existing_patterns, keep_file_churn_low, avoid_renames_unless_needed |

The mode also adds a one-line addendum to the system block. For example, `surgical` adds:
> SURGICAL MODE: Minimize the diff. One focused change. No scope creep.

```bash
ai show modes    # full table in the terminal
```

---

## 8. Constraints

Constraints are injected into the `constraints` block of the compiled prompt. They are
enforced at the **prompt level** — the LLM is instructed to comply, not the engine itself.

Each constraint is a `Constraint` enum value. The engine deduplicates across task defaults
and mode extras so no constraint appears twice.

| Constraint | Meaning |
|---|---|
| `minimal_diff` | Make the smallest possible change that satisfies the goal |
| `preserve_public_api` | Do not change any public interface or exported symbol |
| `no_unnecessary_abstractions` | No new abstractions unless directly required |
| `no_unrelated_refactors` | Do not refactor code outside the task scope |
| `follow_existing_patterns` | Match the patterns already used in this repo |
| `preserve_behavior` | Do not change observable behavior unless that is the goal |
| `minimize_token_usage` | Keep context and output compact |
| `keep_file_churn_low` | Avoid touching files that don't need to change |
| `avoid_renames_unless_needed` | Do not rename symbols unless required by the fix |
| `avoid_new_dependencies` | Do not introduce new packages or libraries |
| `require_tests` | The output must include or reference tests |
| `require_explanation` | State what you changed and why |
| `require_risk_analysis` | State what could go wrong |
| `no_guessing` | Do not infer facts that aren't supported by evidence |
| `no_speculative_cleanup` | No opportunistic cleanup or style fixes |
| `prefer_existing_helpers` | Use existing utilities before writing new ones |
| `prefer_local_changes` | Fix at the call site, not globally |
| `avoid_global_state` | Do not introduce or expand global mutable state |
| `avoid_cross_module_spill` | Changes should not leak across module boundaries |
| `no_schema_change_without_migration` | Schema changes require a migration plan |
| `no_backward_compat_break` | Do not break existing callers or consumers |
| `no_api_surface_growth` | Do not expand the API surface without clear need |
| `no_logging_noise` | Do not add noisy or low-signal log statements |
| `no_behavioral_surprises` | The system should behave identically from the outside |
| `no_performance_regression` | Do not introduce measurable slowdowns |
| `no_security_regression` | Do not weaken any security invariant |
| `no_dead_code_introduction` | Do not leave unreachable or unused code |

```bash
ai show constraints    # full table in the terminal
```

### How constraints are assembled

```
base_constraints (from task type)
  + mode_extra_constraints (from active mode)
  + forced_extras (from --preserve-api, --preset, always_on_constraints in config)
  - disabled_constraints (from config file)
  - require_tests (if --no-tests)
```

---

## 9. Presets

Presets are named configurations bundling task type + mode + extra/removed constraints.
Use them when you have a recurring workflow pattern.

| Preset | Task type | Mode | Extra constraints |
|---|---|---|---|
| `bugfix/minimal` | bugfix | surgical | minimal_diff, keep_file_churn_low |
| `bugfix/safe` | bugfix | safe | require_risk_analysis, no_behavioral_surprises |
| `bugfix/deep` | bugfix | deep | — |
| `feature/surgical` | feature | surgical | no_unnecessary_abstractions, avoid_new_dependencies |
| `feature/default` | feature | deep | — |
| `refactor/safe` | refactor | safe | preserve_public_api, no_behavioral_surprises |
| `refactor/compatibility` | refactor | safe | no_backward_compat_break, preserve_public_api, no_api_surface_growth |
| `debug/deep` | debugging | debug | — |
| `test/coverage-first` | test_generation | strict | — |
| `security/strict` | security | strict | no_security_regression, no_behavioral_surprises, require_risk_analysis |
| `migration/careful` | migration | safe | no_backward_compat_break, no_schema_change_without_migration |
| `review/strict` | code_review | strict | no_guessing, require_explanation |

```bash
ai show presets    # full table in the terminal
```

---

## 10. Profiles

Profiles are cross-cutting execution settings applied on top of a task type. Unlike presets,
they do not specify a task type — they modify any task with a mode and optional constraint set.

| Profile | Mode | Description |
|---|---|---|
| `fast` | fast | Minimize tokens and response time. Compact output. |
| `balanced` | (task default) | Default balance of thoroughness and speed. |
| `strict` | strict | Strong guardrails, explicit assumptions, verbose output. |
| `architectural` | architectural | Design-boundary and invariant focused. |
| `experimental` | explore | Higher risk tolerance, exploratory output. |

```bash
ai feat 'add webhook support' --profile strict    # strict mode on a feature task
ai debug 'flaky test' --profile fast              # fast mode on a debug task
ai show profiles                                  # full table
```

---

## 11. Output contracts

Every task type has an output contract — the structured fields the LLM must produce.
The contract is injected as the `output_contract` block in the compiled prompt.

In `fast` or `minimal` mode, only required fields are included. In other modes, all fields
(required + optional) are listed with their descriptions.

To see the contract for any task type:

```bash
ai show task bugfix
ai show task migration
ai show task security
```

### Contract field structure

Each field has:
- `name` — the key the LLM should use
- `description` — what belongs in this field
- `required` — whether the field is mandatory (optional fields are marked `(optional)`)

### Default contract (used when no specific contract exists)

`summary`, `changes`, `rationale`, `risks`

---

## 12. Config file

The engine loads config from two sources, merged in order (repo overrides global):

```
~/.config/prompt-engine/config.toml    global defaults
./.prompt-engine.toml                  repo-local overrides  (also checks parent dir)
```

Generate the global config with comments:

```bash
ai init             # writes ~/.config/prompt-engine/config.toml
ai init --force     # overwrite existing
```

### Full config reference

```toml
# ~/.config/prompt-engine/config.toml  or  .prompt-engine.toml

# Default reasoning mode applied to all tasks when no --mode flag is given
# default_mode = "surgical"

# Default execution profile
default_profile = "balanced"   # fast | balanced | strict | architectural | experimental

# Token budget for the context block (symbols + git diff)
max_tokens = 8000

# Symbol retrieval depth — how many call-chain hops to follow
context_depth = 2

# Default constraint behavior
require_tests = true
no_guessing = true
follow_existing_patterns = true

# Arbitrary policy text injected into the system block for every task
# repo_policy = "Services are thin. Business logic lives in the domain layer only."

# Per-task-type mode overrides
[task_mode_overrides]
bugfix = "surgical"
feature = "deep"
migration = "safe"
refactor = "safe"

# Constraints always added regardless of task type
always_on_constraints = [
  "follow_existing_patterns",
  "no_guessing",
]

# Constraints never added (useful for disabling require_tests repo-wide)
disabled_constraints = [
  # "require_tests",
]
```

### `repo_policy`

The `repo_policy` string is injected verbatim into the system block under a
`REPOSITORY POLICY` header for every compiled prompt. Use it to encode project-specific
invariants the LLM must always respect:

```toml
repo_policy = """
Services are thin. Business logic lives in the domain layer only.
Never bypass the repository pattern — no raw SQL outside db/ package.
All public endpoints require authentication via the AuthMiddleware.
"""
```

---

## 13. Python API

### Basic usage

```python
from prompt_engine import classify, build_task, compile_task
from prompt_engine.taxonomy import Mode
from prompt_engine.retrieval import retrieve
from pathlib import Path

# 1. Build a task from natural language
task = build_task(
    raw_intent="add rate limiting to the /auth/token endpoint",
    hint_mode=Mode.SURGICAL,
    hint_scope="auth",
)

# 2. Retrieve repo context
bundle = retrieve(
    plan=task.retrieval_plan,
    budget=task.context_budget,
    repo_root=Path.cwd(),
)

# 3. Compile to a prompt
plan = compile_task(task, bundle=bundle)

# 4a. Single string (paste into any LLM)
prompt_text = plan.compile()

# 4b. Messages format (OpenAI / Anthropic SDK)
messages = plan.to_messages()
# → [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
```

### Classify only (no task building)

```python
from prompt_engine import classify

result = classify("fix the null pointer in UserService")
print(result.task_type)     # TaskType.BUGFIX
print(result.mode)          # Mode.SURGICAL
print(result.confidence)    # 0.9
print(result.evidence)      # ["'fix' → 0.9", "mode 'surgical' is default for bugfix"]
print(result.is_ambiguous)  # False  (confidence >= 0.4)
```

### Inspect what the compiler produces

```python
from prompt_engine import build_task, compile_task

task = build_task("fix the null pointer")
plan = compile_task(task)

for block in plan.included_blocks():
    print(f"{block.role:20} {block.token_estimate:5} tokens  [{block.source}]")

print(plan.total_tokens(), "tokens total")
```

### Force task type + mode

```python
from prompt_engine import build_task
from prompt_engine.taxonomy import TaskType, Mode

task = build_task(
    raw_intent="extract payment logic",
    hint_task_type=TaskType.REFACTOR,
    hint_mode=Mode.SAFE,
    hint_scope="payments",
    preserve_api=True,
    no_tests=False,
)
```

### Load repo config

```python
from prompt_engine.config import load_config
from pathlib import Path

cfg = load_config(repo_root=Path("/path/to/repo"))
print(cfg.repo_policy)
print(cfg.always_on_constraints)
print(cfg.task_mode_overrides)
```

### Build a ContextBudget manually

```python
from prompt_engine.task import ContextBudget
from prompt_engine.taxonomy import Mode

budget = ContextBudget().scale_for_mode(Mode.DEEP)
print(budget.max_tokens)       # 16000
print(budget.retrieval_depth)  # 4
print(budget.output_verbosity) # "verbose"
```

### Build a RetrievalPlan manually

```python
from prompt_engine.task import RetrievalPlan, ContextBudget
from prompt_engine.retrieval import retrieve
from pathlib import Path

plan = RetrievalPlan(
    query="UserService getById",
    symbol_targets=["UserService", "getById"],
    git_history=True,
    include_call_chains=True,
)
budget = ContextBudget(max_tokens=8000, retrieval_depth=3)
bundle = retrieve(plan=plan, budget=budget, repo_root=Path.cwd())

print(bundle.symbol_count)
print(bundle.retrieval_notes)
for sym in bundle.symbols:
    print(sym.name, sym.kind, sym.file_path, sym.start_line)
```

### Use a custom policy registry

```python
from prompt_engine import build_task, compile_task
from prompt_engine.policy import build_registry, PolicyRule
from prompt_engine.taxonomy import TaskType

task = build_task("fix the auth bypass")
registry = build_registry(repo_policy_text="No raw SQL outside db/. Auth is required on all routes.")
registry.add(PolicyRule(
    name="no_third_party_auth",
    description="Do not use third-party auth libraries",
    applies_to=[TaskType.FEATURE, TaskType.SECURITY],
    text="Do not introduce third-party authentication libraries.",
))
plan = compile_task(task, registry=registry)
```

---

## 14. Repo-index integration

The retrieval bridge (`prompt_engine/retrieval.py`) is a soft dependency on `repo-index`.
If `repo-index` is not installed, retrieval silently returns an empty bundle and the context
block becomes a placeholder.

### How retrieval works

1. **Build the call graph once** — `build_call_graph_cached(conn)` builds a NetworkX digraph
   keyed by `id(conn)`. Subsequent calls in the same session are free.

2. **Priority 1 — explicit symbol targets** — if `RetrievalPlan.symbol_targets` is populated,
   these are fetched first at full `retrieval_depth`.

3. **Priority 2 — recently changed symbols** — parsed from `git diff HEAD~3` hunk headers.
   Up to 2 slots are reserved for symbols modified in recent commits, fetched at `depth-1`.

4. **Priority 3 — FTS search** — the remaining slots are filled by full-text search on the
   plan's `query` string. Falls back to individual keywords if the full query matches nothing.

5. **Composite ranking** — FTS results are re-ranked by:
   ```
   composite = -bm25_score + log1p(caller_count)*0.5 + recency*0.3 + path_keyword_bonus*0.4
   ```

6. **Callgraph trimming** — rank-1 symbol keeps the full callgraph. Supporting symbols
   (rank 2+) get their callgraph trimmed to 4 hops to save budget.

7. **Budget cap** — the assembled `raw_text` is hard-trimmed to 55% of `ContextBudget.max_tokens`.

### DB resolution order

```
1. explicit db_path argument to retrieve()
2. REPO_INDEX_DB environment variable
3. ~/.local/share/repo-index/<git_root_name>.db  (if the file exists)
4. ~/.local/share/repo-index/index.db            (default fallback)
```

### Retrieval notes

`ContextBundle.retrieval_notes` contains a list of strings explaining what happened:

```python
bundle.retrieval_notes
# → [
#   "index: 4821 symbols at /home/user/.local/share/repo-index/ai-infra.db",
#   "git: 3 recently-changed symbol(s) detected",
#   "added 2 recently-changed symbol(s) as context",
# ]
```

---

## 15. Architecture

```
prompt-engine/
├── prompt_engine/
│   ├── taxonomy.py      TaskType, Mode, Constraint, RiskLevel enums + descriptions
│   ├── task.py          Task, RetrievalPlan, ContextBudget, PromptBlock, PromptPlan
│   ├── intent.py        Classifier: keyword scoring → IntentResult + build_task()
│   ├── contracts.py     OutputContract per task type (field names + descriptions)
│   ├── policy.py        PolicyRegistry, universal rules, repo-local policy injection
│   ├── compiler.py      compile_task() — assembles PromptBlocks into a PromptPlan
│   ├── retrieval.py     retrieve() — repo-index bridge, symbol fetch, git diff, budget cap
│   ├── budget.py        Token estimation, budget enforcement, compression summary
│   ├── presets.py       Preset + Profile definitions, CLI_VERB_ALIASES
│   ├── config.py        EngineConfig, TOML loader, write_default_config()
│   └── cli.py           Typer app — verb commands, show subcommands, init
└── tests/
    └── test_retrieval.py
```

### Key data flow types

```
classify()        → IntentResult      (task_type, mode, sub_type, scope, confidence, evidence)
build_task()      → Task              (fully populated with constraints, budget, retrieval_plan)
retrieve()        → ContextBundle     (symbols, git_diff, raw_text, token_estimate)
compile_task()    → PromptPlan        (ordered PromptBlocks, total token estimate)
plan.compile()    → str               (single prompt string)
plan.to_messages()→ list[dict]        (OpenAI/Anthropic messages format)
```

### Universal policy rules (always active)

These are injected into every compiled prompt regardless of task type or config:

| Rule | Text |
|---|---|
| `anti_slop` | Do not give generic advice unconnected to this specific codebase. |
| `no_speculation` | Do not invent facts. State uncertainty explicitly. |
| `repo_native` | Match the patterns already present in the repository. |
| `no_churn` | Do not touch files unrelated to the task. Do not rename unless the name is causing the bug. |
| `bounded_scope` | Stay within the stated task scope. If you notice adjacent issues, mention them but do not fix them. |

---

## 16. Extending the engine

### Add a new task type

1. Add the enum value to `taxonomy.py`:
   ```python
   class TaskType(str, Enum):
       ...
       MY_NEW_TYPE = "my_new_type"
   ```

2. Add a description to `TASK_TYPE_DESCRIPTIONS` in `taxonomy.py`.

3. Add default mode, risk, constraints, retrieval priorities, and verification checks
   to the tables in `intent.py`:
   ```python
   _DEFAULT_MODES[TaskType.MY_NEW_TYPE] = Mode.SURGICAL
   _DEFAULT_RISK[TaskType.MY_NEW_TYPE] = RiskLevel.MEDIUM
   _DEFAULT_CONSTRAINTS[TaskType.MY_NEW_TYPE] = [Constraint.REQUIRE_EXPLANATION, ...]
   _RETRIEVAL_PRIORITIES[TaskType.MY_NEW_TYPE] = ["relevant context category 1", ...]
   _VERIFICATION_REQUIRED[TaskType.MY_NEW_TYPE] = ["check 1", "check 2"]
   _TASK_KEYWORDS[TaskType.MY_NEW_TYPE] = [(r"\bkeyword\b", 0.8), ...]
   ```

4. Add an output contract in `contracts.py`:
   ```python
   _MY_NEW_TYPE = OutputContract(
       task_type=TaskType.MY_NEW_TYPE,
       fields=(
           OutputField("summary", "What was done"),
           OutputField("patch", "The code change"),
           OutputField("risks", "What could regress", required=False),
       ),
   )
   _CONTRACTS[TaskType.MY_NEW_TYPE] = _MY_NEW_TYPE
   ```

5. Optionally register a CLI verb in `cli.py`:
   ```python
   _make_task_command(TaskType.MY_NEW_TYPE, "myverb", "Short description of the task")
   ```

### Add a new preset

In `presets.py`, add an entry to `_PRESETS`:

```python
"mytype/focused": Preset(
    name="mytype/focused",
    description="Description of when to use this preset",
    task_type=TaskType.MY_NEW_TYPE,
    mode=Mode.SURGICAL,
    extra_constraints=(Constraint.MINIMAL_DIFF, Constraint.NO_UNRELATED_REFACTORS),
    context_depth=2,
),
```

### Add a new constraint

1. Add to `Constraint` enum in `taxonomy.py`.
2. Add a human-readable description to `CONSTRAINT_DESCRIPTIONS` in `taxonomy.py`.
3. Add it to the relevant `_DEFAULT_CONSTRAINTS` entries in `intent.py`.
4. Add it to `_MODE_EXTRA_CONSTRAINTS` if it should be mode-triggered.

### Add a repo-local policy rule programmatically

```python
from prompt_engine.policy import build_registry, PolicyRule
from prompt_engine.taxonomy import TaskType

registry = build_registry(repo_policy_text="")
registry.add(PolicyRule(
    name="no_orm_bypass",
    description="Prevent raw SQL outside the db layer",
    applies_to=[TaskType.FEATURE, TaskType.BUGFIX, TaskType.REFACTOR],
    text="Never write raw SQL outside the db/ package. Use the repository pattern.",
    priority=30,
))
```

Or just set `repo_policy` in `.prompt-engine.toml` — that text is injected into the
system block for all task types without any code changes.
