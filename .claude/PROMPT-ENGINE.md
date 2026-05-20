````md
# Deterministic Prompt Engine / Cognitive Runtime Spec

You are building a **deterministic prompt orchestration engine** for AI-assisted coding.

The goal is to convert messy natural-language developer intent into a **typed, repeatable, constrained, context-aware execution pipeline** that produces high-quality Claude outputs with:
- lower token usage
- less slop
- fewer hallucinations
- better repo-specific consistency
- easier developer experience
- minimal user burden
- easy extensibility

This system sits **above** the repo indexer / retrieval layer and **below** the human developer interface.

---

## 1. Core Vision

The engine must behave like a **compiler for coding intent**.

Human input should be lightweight and natural:

- “fix duplicate SSE delivery”
- “refactor this module safely”
- “add retry logic”
- “find why this test is flaky”
- “make this API more predictable”
- “generate tests for this function”

The engine should convert that into:
1. a normalized task
2. a selected protocol
3. a context budget
4. a retrieval plan
5. a prompt assembly plan
6. a verification plan
7. an execution plan
8. a final Claude request

The user must **not** be forced to write huge YAML every time.

The system must make advanced behavior feel easy.

---

## 2. Design Principles

### 2.1 Determinism over vibes
The same input should produce the same structural plan unless the repository state changes.

### 2.2 Tiny user-facing input, rich internal representation
The user should express intent in simple language or a small DSL.

Internally, the engine should expand that into a full task graph with defaults.

### 2.3 Progressive disclosure
Only ask the user for missing information when absolutely necessary.

Prefer:
- sensible defaults
- protocol inference
- repository-aware heuristics
- local conventions
- task type classification

### 2.4 Strong constraints
The engine should prevent overengineering:
- no random abstractions
- no unrelated refactors
- no broad rewrites unless asked
- no unnecessary file churn
- no speculative architecture changes

### 2.5 Repo-native behavior
The engine must prefer existing repository patterns over generic best practices.

### 2.6 Verifiable output
Every task should end with:
- what changed
- why it changed
- what risks exist
- what tests should run
- what could still be wrong

---

## 3. What This Engine Is Not

This engine is **not**:
- just a prompt template collection
- just a YAML parser
- just a CLI wrapper around Claude
- just a retrieval gateway
- just an agent framework with loops
- just a generic “AI assistant” shell

It is a **task orchestration runtime**.

---

## 4. Main Objectives

The engine must:
- classify task intent automatically
- select a reasoning protocol
- construct a compact but sufficient context bundle
- minimize tokens while preserving correctness
- preserve repository conventions
- produce consistent outputs
- support advanced developer workflows with minimal friction
- make prompt creation feel natural and fast
- make configuration easy for a developer
- support safe experimentation and dry runs
- support future integration with repo index / MCP / retrieval layers

---

## 5. High-Level Architecture

The engine should be organized into these logical layers:

### 5.1 User Intent Layer
Accepts:
- natural language
- short commands
- a tiny DSL
- optional structured options
- optional config overrides

### 5.2 Task Normalization Layer
Converts user intent into:
- task type
- subtask type
- scope
- risk level
- mode
- constraints
- expected output shape

### 5.3 Protocol Selection Layer
Chooses the reasoning protocol based on task type and repository context.

### 5.4 Context Planning Layer
Decides:
- what repo context is needed
- which summaries are enough
- which files/symbols/tests are relevant
- how much detail to include
- what to exclude

### 5.5 Prompt Assembly Layer
Builds the final Claude prompt from:
- system policy
- task protocol
- constraints
- context fragments
- output contract
- verification instructions

### 5.6 Verification Layer
Checks:
- output completeness
- patch validity
- style adherence
- risk flags
- test requirements
- architecture invariants

### 5.7 Feedback / Learning Layer
Stores:
- successful patterns
- failed patterns
- task outcomes
- preference adjustments
- repo conventions
- reusable prompt fragments

---

## 6. Developer Experience Goals

This is critical.

The user experience must feel like:

- “I say what I want in one line”
- the engine fills in the rest intelligently
- I can inspect the plan if I want
- I can override only the parts I care about
- I can keep moving fast

### 6.1 The user should not have to write full YAML every time
YAML should be optional, not mandatory.

Good:
- `ai fix duplicate SSE delivery`
- `ai refactor auth module --surgical`
- `ai test flaky_order_processor`
- `ai explain why this handler is slow`

Better:
- `ai bugfix "duplicate SSE delivery" --scope broker`
- `ai feature "add cursor-based pagination" --mode deep`

Best:
- natural command plus a few flags
- defaults inferred from repo and task type

### 6.2 Simple overrides
The user should be able to override only what matters:
- task type
- mode
- scope
- risk tolerance
- output style
- verification strictness
- context depth

### 6.3 Dry-run and explain modes
The engine should support:
- `--dry-run` to show the plan only
- `--explain` to show why the engine chose a protocol/context
- `--compact` to reduce verbosity
- `--strict` to enforce stronger guardrails

### 6.4 Discoverability
Users should be able to learn:
- available task types
- available modes
- available constraints
- available presets
- available policies
- why a task was classified a certain way

### 6.5 Fast iteration
A developer should be able to:
- run a task
- inspect the plan
- tweak a single field
- rerun
- compare outputs

The system should avoid making the user feel trapped in configuration overhead.

---

## 7. User-Facing Input Formats

Support multiple input styles.

### 7.1 Natural language
Examples:
- “fix the bug where events get delivered twice”
- “make this safer without changing public API”
- “add tests for pagination edge cases”
- “why is this query slow”

### 7.2 Short command syntax
Examples:
- `ai fix "double event delivery"`
- `ai refactor broker --surgical`
- `ai test payment service`
- `ai explain auth middleware`

### 7.3 Tiny structured input
Examples:
```yaml
task: bugfix
goal: duplicate event delivery
mode: surgical
````

### 7.4 Full config file

Only for advanced cases. Should be optional.

---

## 8. Task Taxonomy

The system should classify tasks into a finite but extensible set.

### 8.1 Core categories

* bugfix
* feature
* refactor
* test_generation
* debugging
* explanation
* optimization
* migration
* code_review
* architecture
* documentation
* cleanup
* security
* performance
* reliability
* observability
* dependency_update
* data_migration
* api_change
* cli_change
* config_change
* build_fix
* release_support

### 8.2 Subcategories

Each task type can have subtypes.

Examples:

* bugfix:

  * race_condition
  * null_handling
  * duplicate_event
  * incorrect_state
  * edge_case_failure
  * regression
* feature:

  * endpoint
  * background_job
  * cli_command
  * ui_flow
  * webhook
  * cache_layer
* refactor:

  * internal_cleanup
  * interface_simplification
  * modularization
  * extraction
  * deprecation
* debugging:

  * runtime_error
  * test_flake
  * perf_bottleneck
  * intermittent_issue
  * integration_failure

### 8.3 Task classification must consider

* user wording
* repo structure
* recent diffs
* changed files
* tests touched
* error messages
* stack traces
* historical patterns

---

## 9. Modes / Reasoning Styles

The user should be able to request a mode or let the system infer it.

### 9.1 Suggested modes

* `surgical`: smallest possible change
* `deep`: broader understanding before action
* `fast`: token-lean, quick execution
* `safe`: stronger verification, conservative changes
* `explore`: gather options before choosing
* `strict`: stronger adherence to constraints and structure
* `minimal`: ultra-compact context and output
* `architectural`: focus on design boundaries and invariants
* `debug`: root-cause oriented
* `rewrite`: more willing to reshape internals
* `maintain`: bias toward repo consistency and low churn

### 9.2 Mode selection should affect

* retrieval depth
* context width
* prompt verbosity
* verification strictness
* patch aggressiveness
* output shape

---

## 10. Constraint System

Constraints are the anti-slop backbone.

### 10.1 Core constraints

* minimal_diff
* preserve_public_api
* no_unnecessary_abstractions
* no_unrelated_refactors
* follow_existing_patterns
* preserve_behavior
* minimize_token_usage
* keep_file_churn_low
* avoid_renames_unless_needed
* avoid_new_dependencies
* require_tests
* require_explanation
* require_risk_analysis
* no_guessing
* no_speculative_cleanup
* prefer_existing_helpers
* prefer_local_changes
* avoid_global_state
* avoid_cross_module_spill

### 10.2 Strong constraints for sensitive tasks

* do_not_change_schema_without_migration_plan
* do_not_break_backward_compatibility
* no_api_surface_growth_without_need
* no_logging_noise
* no_behavioral_surprises
* no_performance_regression
* no_security_regression
* no_dead_code_introduction

### 10.3 Constraint behavior

Constraints should compile into:

* prompt instructions
* retrieval filters
* output checks
* validator checks

---

## 11. Context Categories

The engine must know what kinds of context exist and when to use them.

### 11.1 Code context

* directly relevant files
* functions
* classes
* methods
* modules
* interfaces
* constants
* enums
* types
* helpers
* call chains

### 11.2 Structural context

* repo layout
* layering rules
* module ownership
* architecture boundaries
* package dependency graph
* import graph
* service boundaries

### 11.3 Behavioral context

* state transitions
* side effects
* concurrency behavior
* caching behavior
* retry behavior
* failure handling
* event ordering
* idempotency rules

### 11.4 Historical context

* git diff
* recent edits
* past bugs
* previous implementations
* prior refactors
* migration history
* commit patterns

### 11.5 Testing context

* unit tests
* integration tests
* fixtures
* snapshots
* regression tests
* flaky tests
* test helpers
* test data patterns

### 11.6 Domain context

* business terminology
* domain invariants
* workflow states
* data model semantics
* API contracts
* user flows

### 11.7 Operational context

* logs
* metrics
* traces
* alarms
* deployment notes
* runtime errors
* production incident context

### 11.8 Policy context

* coding standards
* architecture rules
* security rules
* style preferences
* lint preferences
* repo-specific conventions

---

## 12. Context Selection Rules

The engine must choose context based on task type.

### 12.1 Bugfix

Prefer:

* recent diffs
* call chains
* error output
* tests around failure path
* related state transitions
* likely regression zones

Avoid:

* broad unrelated modules
* architectural essays
* unnecessary full-file dumps

### 12.2 Feature

Prefer:

* similar existing implementations
* API contracts
* related services
* conventions
* test patterns
* domain models

### 12.3 Refactor

Prefer:

* interfaces
* call sites
* dependency graph
* architecture notes
* usage search
* compatibility risks

### 12.4 Test generation

Prefer:

* source function
* edge cases
* similar tests
* fixtures
* failure modes
* branch coverage targets

### 12.5 Debugging

Prefer:

* logs
* stack traces
* runtime behavior
* recent edits
* reproduction steps
* flaky patterns

### 12.6 Optimization

Prefer:

* hotspots
* profiling output
* loops
* allocations
* query plans
* contention points

### 12.7 Migration

Prefer:

* schema definitions
* compatibility constraints
* rollout strategy
* dual-write considerations
* backfill needs
* rollback plan

---

## 13. Prompt Assembly Architecture

The system should not keep giant handwritten prompts.

Instead, it should build prompts from modules.

### 13.1 Prompt modules

* system policy
* task type policy
* mode policy
* repository policy
* constraints block
* retrieval summary
* selected context
* output contract
* verification instructions
* safety rules
* formatting rules

### 13.2 Prompt assembly must support

* ordering
* deduplication
* truncation
* compression
* prioritization
* token budgeting
* deterministic placement

### 13.3 Prompt assembly should be inspectable

The user should be able to see:

* what was included
* what was omitted
* why it was included
* how much token budget each part used

---

## 14. Output Contracts

Every task should have a structured output shape.

### 14.1 Common output fields

* summary
* task_type
* mode
* assumptions
* selected_context
* plan
* root_cause
* implementation_notes
* files_to_change
* patch
* tests
* risks
* rollback_notes
* follow_ups

### 14.2 Bugfix output

* symptom
* root_cause
* trigger
* affected_code_paths
* fix_strategy
* patch
* tests
* regression_risks

### 14.3 Feature output

* goal
* design_choice
* affected_interfaces
* patch
* tests
* migration_notes
* compatibility_notes

### 14.4 Refactor output

* current_shape
* target_shape
* migration_path
* patch
* compatibility
* risk_analysis

### 14.5 Debugging output

* reproduction
* evidence
* likely_cause
* uncertainty
* next_steps
* patch_if_applicable

### 14.6 Review output

* issues_found
* severity
* rationale
* suggested_changes
* non_issues
* confidence

---

## 15. Verification System

The engine should not trust generation blindly.

### 15.1 Verification categories

* syntax checks
* type checks
* lint checks
* test checks
* schema checks
* architecture checks
* security checks
* compatibility checks
* diff sanity checks
* performance checks
* invariant checks

### 15.2 Verification should answer

* Did the output obey the task contract?
* Did it exceed scope?
* Did it introduce risk?
* Did it miss a required test?
* Did it violate repo style?
* Did it change more than necessary?

### 15.3 Verification should generate warnings for

* too many files changed
* unnecessary renames
* unrelated formatting churn
* missing tests
* ambiguous assumptions
* behavioral risk
* architecture violations

---

## 16. Context Budgeting

Token efficiency matters.

### 16.1 Budget dimensions

* maximum context size
* retrieval depth
* summary depth
* code chunk size
* number of examples
* output verbosity
* verification verbosity

### 16.2 Context priorities

Priority order should generally be:

1. task intent
2. constraints
3. directly relevant code
4. tests
5. architecture rules
6. similar examples
7. secondary context
8. optional notes

### 16.3 Compression strategies

* symbol summaries
* AST summaries
* call-chain summaries
* concise diffs
* file-level summaries
* architecture summaries
* line-level inclusion only when necessary

### 16.4 Avoid

* dumping full unrelated files
* duplicating the same context in multiple forms
* feeding all retrieved results by default
* oversized global instructions
* stale or low-signal context

---

## 17. Progressive Disclosure

The engine should expose context in layers.

### 17.1 Suggested tiers

* Tier 0: user intent
* Tier 1: task classification
* Tier 2: compact context summary
* Tier 3: selected files / symbols
* Tier 4: code excerpts
* Tier 5: full files only if necessary

### 17.2 Usage

Start with summaries and expand only if:

* confidence is low
* user asks for detail
* task is high risk
* multiple candidate paths exist
* context is ambiguous

---

## 18. Repository Conventions / Policy Memory

The engine should learn and reuse repo-specific rules.

### 18.1 Things to store

* architecture rules
* folder ownership
* naming conventions
* test conventions
* error handling style
* logging style
* comment style
* file organization
* API patterns
* migration patterns
* concurrency patterns
* eventing patterns
* state machine rules

### 18.2 Example policy data

* services are thin or thick?
* where business logic lives
* where DB access lives
* where validation lives
* where retries live
* how errors are shaped
* how events are named
* how tests are structured

### 18.3 Do not store

* temporary experimental notes
* one-off debug speculation
* highly transient local preferences unless explicitly user-approved
* private sensitive content
* noisy raw chat history

---

## 19. Learning from Outcomes

The engine should remember outcomes at the task level.

### 19.1 Store

* what task type was used
* what protocol was selected
* what context worked
* what caused failure
* what needed more context
* what was overkill
* what output was accepted
* what got rejected

### 19.2 Use outcome memory to improve

* classification
* prompt assembly
* retrieval choice
* output contract selection
* context budget allocation

---

## 20. Human-Friendly Configuration

This is a major requirement.

### 20.1 Configuration philosophy

Configuration should be:

* small
* layered
* override-friendly
* readable
* composable
* repo-local
* easy to diff
* easy to version control

### 20.2 Recommended config layers

1. global defaults
2. user preferences
3. repo defaults
4. task-type defaults
5. command-line overrides
6. session overrides
7. one-off inline overrides

### 20.3 Avoid

* huge monolithic YAML
* deeply nested config that users never touch
* duplicated settings in many files
* magic values that are hard to discover
* configs that require editing 10 fields for a simple task

### 20.4 Prefer

* presets
* aliases
* inheritance
* shallow overrides
* reusable profiles
* readable names

---

## 21. Suggested User Experience Features

### 21.1 Presets

Provide named presets like:

* `bugfix/minimal`
* `bugfix/safe`
* `feature/surgical`
* `refactor/compatibility`
* `debug/deep`
* `test/coverage-first`

### 21.2 Profiles

Allow profiles such as:

* `fast`
* `balanced`
* `strict`
* `architectural`
* `experimental`

### 21.3 Aliases

Support short aliases for common workflows:

* `fix`
* `feat`
* `ref`
* `dbg`
* `test`
* `review`

### 21.4 Interactive mode

When information is missing, ask only the minimum necessary questions.

Examples:

* “Should this preserve public API?”
* “Do you want surgical or deep mode?”
* “Should I optimize for minimal diff or long-term cleanup?”

### 21.5 Explain mode

Show:

* task classification
* chosen protocol
* selected context
* excluded context
* chosen constraints
* prompt shape
* verification steps

### 21.6 Dry-run mode

Show the compiled plan without invoking Claude.

### 21.7 Strict mode

Require:

* explicit assumptions
* output contract adherence
* test suggestions
* stronger guardrails

---

## 22. What Should Be Easy for the Developer

The engine should make these actions trivial:

* switch task modes
* override constraints
* inspect what context was used
* reuse a previous task’s setup
* convert a one-line intent into a full plan
* tune token budget without editing config files
* switch between fast and safe execution
* add a new task type
* add a new constraint
* add a new output contract
* add a new retrieval strategy
* add a new repo policy rule

---

## 23. What Should Be Hard or Restricted

The engine should discourage:

* giant freeform prompts
* unexplained broad refactors
* silent architecture changes
* unbounded context dumps
* hidden prompt magic
* unclear assumptions
* accidental file churn
* over-generalized abstractions
* tasks that blend too many goals without explicit approval

---

## 24. Suggested Internal Data Model

Use typed internal structures rather than raw prompt blobs.

### 24.1 Task object

* id
* raw_intent
* normalized_intent
* task_type
* sub_type
* mode
* scope
* constraints
* risk_level
* confidence
* output_contract
* retrieval_plan
* context_budget
* verification_plan
* session_state

### 24.2 Retrieval plan

* query
* priority
* file_targets
* symbol_targets
* test_targets
* summary_targets
* excluded_targets
* confidence expectations

### 24.3 Prompt plan

* system_blocks
* task_blocks
* context_blocks
* instructions
* formatting
* safety
* output_schema

### 24.4 Verification plan

* required_checks
* optional_checks
* invariant_checks
* acceptance_criteria
* risk_flags

---

## 25. Error Handling Philosophy

The system should fail clearly and helpfully.

### 25.1 If classification confidence is low

Ask a short clarifying question or provide top 2–3 likely interpretations.

### 25.2 If retrieval is weak

Say what context is missing and why.

### 25.3 If output violates contract

Show the exact contract mismatch.

### 25.4 If task is too broad

Propose decomposition into smaller tasks.

### 25.5 If requested scope is dangerous

Warn and suggest a safer narrower scope.

---

## 26. Anti-Slop Rules

This engine must actively reduce slop.

### 26.1 Avoid

* generic advice not tied to the repo
* excessive theory
* architecture rewrites without need
* duplicated explanation
* random helper abstractions
* speculative “best practices”
* dead-code removal unless explicitly scoped
* style-only churn
* “cleaning up” unrelated files

### 26.2 Prefer

* the smallest correct change
* repo-native patterns
* explicit assumptions
* bounded outputs
* precise reasoning
* concrete files and symbols
* direct test guidance

---

## 27. Extensibility Requirements

The system should support future growth.

### 27.1 Add new task types

Should require minimal change.

### 27.2 Add new constraints

Should be composable, not hardcoded everywhere.

### 27.3 Add new modes

Should map cleanly into retrieval and prompt policies.

### 27.4 Add new output schemas

Should be easy to register and validate.

### 27.5 Add new repo policies

Should be searchable, versioned, and overrideable.

### 27.6 Add new retrieval strategies

Should not require rewriting the entire compiler.

---

## 28. Observability

The system should be inspectable.

Track:

* task classification confidence
* protocol chosen
* context used
* context omitted
* token budget allocation
* prompt size
* output size
* verification results
* acceptance / rejection reason
* user override patterns
* retrieval hit quality

This is essential for improving the engine over time.

---

## 29. Metrics That Matter

Measure:

* average token consumption
* prompt-to-accepted-patch ratio
* number of follow-up clarifications
* context reuse rate
* classification accuracy
* retrieval precision
* verification failure rate
* patch churn
* user override frequency
* output contract compliance
* regression rate after generated changes

---

## 30. Suggested Developer Commands

These are examples of how the UX might feel.

### 30.1 Simple commands

* `ai fix "duplicate SSE delivery"`
* `ai feature "cursor pagination"`
* `ai test "payment flow"`
* `ai debug "flake in integration tests"`

### 30.2 More explicit commands

* `ai fix "duplicate SSE delivery" --mode surgical`
* `ai refactor "auth middleware" --preserve-api`
* `ai feature "webhook retries" --safe`
* `ai explain "why this handler is slow" --deep`

### 30.3 Diagnostics

* `ai plan ...`
* `ai dry-run ...`
* `ai explain-context ...`
* `ai compare-profiles ...`
* `ai inspect-task ...`

---

## 31. Example Workflow

### Input

`ai fix "duplicate SSE delivery" --mode surgical`

### Engine should infer

* task_type: bugfix
* subtype: duplicate_event
* mode: surgical
* constraints:

  * minimal_diff
  * preserve_public_api
  * require_tests
  * no_unrelated_refactors
* context needed:

  * SSE broker code
  * event dispatch path
  * duplicate suppression logic
  * related tests
  * recent changes
* verification:

  * targeted tests
  * regressions around ordering / idempotency
  * patch scope sanity
* output contract:

  * root cause
  * affected files
  * fix strategy
  * tests
  * risks

---

## 32. How to Make YAML Easy

This is very important.

The user should not be exposed to a huge YAML surface by default.

### 32.1 Use presets instead of raw config

* `bugfix/surgical`
* `feature/default`
* `debug/deep`
* `refactor/safe`

### 32.2 Use small override fragments

Example:

```yaml
mode: surgical
constraints:
  - preserve_public_api
```

### 32.3 Use command flags for common choices

Examples:

* `--mode surgical`
* `--safe`
* `--strict`
* `--compact`
* `--no-tests`
* `--dry-run`

### 32.4 Use intelligent defaults

Most of the time, infer:

* task type
* likely mode
* likely constraints
* likely context depth

### 32.5 Use autocomplete / suggestion surfaces

The system should suggest:

* task types
* constraints
* modes
* presets
* output shapes

### 32.6 Use a config generator

Allow:

* `ai init`
* `ai explain defaults`
* `ai show presets`
* `ai show task bugfix`
* `ai show policy`

---

## 33. What This Engine Should Store in Markdown / Config / Data

### 33.1 Store as config

* task type definitions
* constraint definitions
* mode definitions
* output contracts
* policy rules
* preset definitions

### 33.2 Store as learned memory

* repo conventions
* successful patterns
* known pitfalls
* preferred architectures
* recurring task shapes
* common user preferences

### 33.3 Store as runtime state

* active task
* selected context
* partial plan
* retries
* execution results
* validation results

---

## 34. Future Integration with Repo Index / Retrieval Layer

This engine should later connect to repository retrieval using typed semantic queries.

It should never depend on raw database details in the UX layer.

The interface should be something like:

* retrieve context for bugfix
* retrieve similar feature implementations
* retrieve tests for this function
* retrieve architecture notes for this subsystem
* retrieve recent diffs around this module

The retrieval backend can decide whether to use:

* AST index
* SQLite
* symbol graph
* file summaries
* embeddings
* git history

The cognitive engine should only see semantic results, not storage internals.

---

## 35. Acceptance Criteria

This system is successful when:

* a developer can express most tasks in one line
* YAML is optional or minimal
* the engine reliably chooses a good protocol
* prompt size stays reasonable
* retrieval stays task-aware
* outputs are structured and predictable
* slop is noticeably reduced
* repo conventions are preserved
* token usage is lower than manual prompting
* debugging why a task behaved a certain way is easy
* adding new task types or constraints is straightforward

---

## 36. Implementation Priority

Build in this order:

### Phase 1

* task taxonomy
* modes
* constraints
* output contracts
* minimal CLI / intent parser

### Phase 2

* prompt compiler
* context budgeting
* policy registry
* explain/dry-run

### Phase 3

* verification pipeline
* repo policy memory
* presets / profiles
* outcome memory

### Phase 4

* retrieval-layer integration
* progressive disclosure
* advanced task routing
* performance tuning
* observability dashboard

---

## 37. Final Instruction

Design this system so that:

* the user feels powerful without learning a complex config language
* the engine behaves consistently
* the prompts become structured and compact
* the repository’s actual conventions drive the output
* the system can evolve into a full cognitive runtime
* the developer experience stays fast and pleasant
* the complexity lives inside the engine, not on the user’s shoulders

Build it like a compiler, not like a prompt folder.

Build it like a runtime, not like a template zoo.

Build it so that a one-line command can become a reliable, repo-aware, verified engineering action.

```

