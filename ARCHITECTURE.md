## 1. Overview

KAAAGLUMN is a persistent memory agent designed for long-running technical work by a single operator. It maintains conversation state across sessions in a local SQLite database, consults specialist models silently when required, and responds only in its own constrained documentarian voice. Its primary function is to act as a stable operational and analytical layer for the WendScope Labs founder rather than a general-purpose conversational partner.

Within the WendScope Labs ecosystem, KAAAGLUMN sits at the coordination layer alongside two other in-development products: WendScope, the computational research platform, and TriAxis, the interpretive engine that will eventually power WendScope's analytical outputs. KAAAGLUMN Basilica is the public hackathon distribution of the same codebase, sharing all core architecture with the private canonical build (`wendscope-cli`) while differing in default model configuration and system prompt sanitization. Sibling projects (Wend***, Wend***, Wend***) remain under WendScope Labs but are in academic-priority holding.

## 2. File Responsibilities

- **`chat.py`** — Primary entrypoint for both CLI and REPL operation. Manages session lifecycle, command parsing, message persistence, and the streaming response loop. Contains the `KAAAGLUMN_SYSTEM_PROMPT` constant (~7,900 characters, ~1,975 tokens) that defines KAAAGLUMN's identity, voice, and analytical stance. Implements slash command handlers (`list_sessions`, `_repl_switch`, `_repl_label`, `show_history`, `_run_tool_turn`, `_parse_tool_command`) and CLI flag handlers (`--new`, `--session`, `--label`, `--oneshot`, `--history`, `--sessions`). Creates and maintains the `messages` and `sessions` tables in `orchestrator.db`. Depends on `models.py` and `foundry_client.py`.
- **`foundry_client.py`** — Single choke point for all model API calls. Determines whether to use the OpenAI-compatible client path or the AzureOpenAI client path based on the `API_MODE` environment variable and endpoint characteristics. Exposes `load_env()`, `require_env()`, `normalize_foundry_base_url()`, `use_foundry_v1()`, and `get_client()`. Reads endpoint and API key values from environment variables referenced in the model registry. Called by `chat.py` and `call_foundry.py`; does not call back into either.
- **`models.py`** — Model registry and configuration. Defines the `MODELS` dictionary mapping registry keys to configuration entries. Each entry specifies `deployment_name`, `endpoint_env_var`, `api_key_env_var`, and `max_tokens`. Sets `DEFAULT_MODEL`. Exposes `get_model(model_name)` and `deployment_name(model_name)`. Currently registers `grok-4-3`, `Kimi-K2.6`, `DeepSeek-V4-Flash`, and `Qwen3.7-Max`. Imported by `chat.py` and `foundry_client.py`.
- **`call_foundry.py`** — Diagnostic one-shot tool. Executes a single Azure AI Foundry / Azure OpenAI chat call with no startup banner, useful for verifying model connectivity outside the REPL. Defines `ONESHOT_MAX_TOKENS = 128` and `call_foundry(prompt, model_name)`. Provides its own `main()` with `argparse` support for `--dry-run` and a positional prompt argument. Imports `get_client`, `load_env`, and `require_env` from `foundry_client.py` and `DEFAULT_MODEL`, `deployment_name` from `models.py`.
- **`.env.example`** — Template documenting required environment variables. Must be copied to `.env` before first run. The `.env` file is gitignored.
- **`.gitignore`** — Excludes `.env`, `*.db`, `*.db-journal`, `.venv/`, `__pycache__/`, editor config directories, and scratch file patterns (`_diff*`, `_apply*`, `_build*`).
- **`requirements.txt`** — Python runtime dependencies (`openai`, `python-dotenv`, `prompt_toolkit`, `sqlite3` via stdlib).
- **`orchestrator.db`** — Local SQLite database. Not tracked in git. Contains `messages` and `sessions` tables. Persistent across restarts.

## 3. Interfaces and Contracts

### Model Registry Entry

Canonical shape of an entry in the `MODELS` dictionary in `models.py`:

```python
MODELS["<RegistryKey>"] = {
    "deployment_name": "<vendor-specific-model-id>",
    "endpoint_env_var": "<ENV_VAR_NAME_FOR_ENDPOINT>",
    "api_key_env_var": "<ENV_VAR_NAME_FOR_API_KEY>",
    "max_tokens": <int>,
}
```

The registry key is a stable identifier used throughout the codebase to refer to a model (e.g. `"grok-4-3"`, `"Kimi-K2.6"`). The `endpoint_env_var` and `api_key_env_var` fields hold the *names* of environment variables, not the values themselves. This indirection lets multiple models share credentials or reference different providers.

### SQLite Schema — `messages` table

```sql
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT NOT NULL,
    session_id TEXT NOT NULL,
    model      TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content    TEXT NOT NULL
);

CREATE INDEX idx_session ON messages(session_id);
CREATE INDEX idx_timestamp ON messages(timestamp);
```

The `role` CHECK constraint is authoritative. `tool` role rows are persisted for audit but filtered from conversational context passed to models.

### SQLite Schema — `sessions` table

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    label        TEXT,
    created_at   TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);
```

The `label` column is nullable. Sessions are created on first message and updated on every `save_message` call. Backfill migration handles legacy sessions created before this table existed.

### Key Function Signatures

```python
# models.py
get_model(model_name: str) -> dict[str, str | int]
deployment_name(model_name: str) -> str

# foundry_client.py
load_env() -> None
require_env(*keys: str) -> list[str]
normalize_foundry_base_url(endpoint: str) -> str
use_foundry_v1(endpoint: str) -> bool
get_client(model_name: str = DEFAULT_MODEL)  # returns (client, mode, base_url, deployment_name)

# chat.py slash command handlers
list_sessions(conn: sqlite3.Connection) -> None
_repl_switch(conn: sqlite3.Connection, prompt: str) -> str | None
_repl_label(conn: sqlite3.Connection, session_id: str, prompt: str) -> None
show_history(limit: int | None = None, session_id: str | None = None,
             conn: sqlite3.Connection | None = None) -> None
_run_tool_turn(conn: sqlite3.Connection, session_id: str, history: list[dict],
               prompt: str) -> int
_parse_tool_command(prompt: str)  # no return type annotation

# call_foundry.py
call_foundry(prompt: str, model_name: str = DEFAULT_MODEL) -> str
```

### `API_MODE` toggle behavior

Read in `use_foundry_v1(endpoint: str) -> bool`. Determines client construction path in `get_client()`:

- If the env var value (lowercased, stripped) is in `{"foundry_v1", "foundry", "v1"}` returns `True`
- Else, returns `True` if the endpoint URL contains `"services.ai.azure.com"`
- Otherwise returns `False`

When `True`: `get_client()` constructs an `OpenAI` client with `base_url` (normalized via `normalize_foundry_base_url`) and `default_headers={"api-key": api_key}`.

When `False`: constructs an `AzureOpenAI` client with `azure_endpoint` and `api_version` (defaulting to `2024-08-01-preview`).

Return tuple from `get_client()` is always `(client, mode, base_url, deployment_name)` where `mode` is `"foundry_v1"` or `"azure"`.

## 4. Environment Variables

The following environment variables are read by the codebase.

### Currently in use

| Name | Read by | Purpose |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | `foundry_client.get_client()` via model registry | Endpoint URL for Azure Foundry-deployed models (Grok 4.3, Kimi K2.6, DeepSeek). |
| `AZURE_OPENAI_API_KEY` | `foundry_client.get_client()` via model registry | Shared API key for Azure Foundry-deployed models. |
| `AZURE_OPENAI_DEPLOYMENT` | `.env.example` template only | Documented as example; the actual deployment name is resolved from the model registry per model. |
| `AZURE_OPENAI_API_VERSION` | `foundry_client.get_client()` | API version for `AzureOpenAI` client construction. Defaults to `"2024-08-01-preview"` if not set. |
| `API_MODE` | `foundry_client.use_foundry_v1()` | Toggles between Foundry v1 (OpenAI-compatible) and legacy AzureOpenAI client construction. Accepts `foundry_v1`, `foundry`, or `v1` (case-insensitive). Falls back to endpoint-based detection when unset. |
| `QWEN_CLOUD_ENDPOINT` | `foundry_client.get_client()` via model registry | Endpoint URL for Alibaba Model Studio (Qwen3.7-Max). |
| `QWEN_CLOUD_API_KEY` | `foundry_client.get_client()` via model registry | API key for Alibaba Model Studio (Qwen3.7-Max). |

### `.env.example` template values

```
AZURE_OPENAI_ENDPOINT=https://wendscopelabs-8267-resource.services.ai.azure.com/
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_DEPLOYMENT=DeepSeek-V4-Flash
# API_MODE=foundry_v1
AZURE_OPENAI_API_VERSION=2024-08-01-preview
QWEN_CLOUD_ENDPOINT=https://ws-chs0atu7f5rtuool.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
QWEN_CLOUD_API_KEY=your_api_key_here
```

The `API_MODE` line is commented out by default. Uncomment when using Foundry v1 endpoints where automatic detection may not apply.

### Cross-cutting toggle naming

`API_MODE` (formerly `AZURE_OPENAI_API_MODE`) controls behavior that applies to any OpenAI-compatible endpoint, not just Azure — Alibaba Model Studio, OpenRouter, or any other OpenAI-compatible provider. Cross-cutting behavior toggles do not carry a vendor prefix for this reason, per the convention in Section 5.

## 5. Naming Conventions

The following conventions govern how new files, functions, variables, environment variables, database schemas, and commands should be named in the KAAAGLUMN codebase. Existing code that predates the formalization of these rules is grandfathered until a rework pass.

### Files and modules

- Python modules use `snake_case.py`: `chat.py`, `foundry_client.py`, `models.py`, `call_foundry.py`.
- Documentation files use `UPPER_SNAKE_CASE.md` when they are canonical references: `README.md`, `ARCHITECTURE.md`, `LICENSE`.
- Scratch and proposal files use a `_v1` (or `_v2`, etc.) suffix during active development: `chat_sessions_v1.py`, `models_qwen_v1.py`. Scratch files are gitignored via `_diff*`, `_apply*`, `_build*` patterns and are deleted after promotion into production files.

### Functions

- Public functions use `snake_case`: `get_model`, `normalize_foundry_base_url`, `use_foundry_v1`, `list_sessions`.
- Private helpers use a leading underscore: `_repl_switch`, `_repl_label`, `_run_tool_turn`, `_parse_tool_command`, `_ensure_sessions_table`.
- The leading underscore is a signal to future modifiers that the function is internal to the module and its signature is not a stable public contract.

### Constants and module-level configuration

- Constants use `UPPER_SNAKE_CASE`: `DEFAULT_MODEL`, `HISTORY_CONTEXT_LIMIT`, `ONESHOT_MAX_TOKENS`, `SCRIPT_DIR`, `DB_PATH`, `SESSION_FILE`, `TOOL_SYSTEM_TEMPLATE`.
- Private module-level constants use a leading underscore: `_REPL_STRIP_CHARS`, `_LIST_HEADER`, `_LIST_SEP`.
- The `KAAAGLUMN_SYSTEM_PROMPT` constant follows the same rule despite its length.

### Environment variables

Environment variables use `UPPER_SNAKE_CASE`. Prefix convention distinguishes between:

- **Vendor-specific credentials**: use the vendor name as the prefix. Examples: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `QWEN_CLOUD_ENDPOINT`, `QWEN_CLOUD_API_KEY`. These variables hold values that only make sense in the context of that vendor's account.
- **Cross-cutting behavior toggles**: do NOT use a vendor prefix even when the toggle was originally introduced for a single vendor. The behavior applies broadly to any provider matching the pattern. Example: `AZURE_OPENAI_API_MODE` was renamed to `API_MODE` because the toggle applies to any OpenAI-compatible endpoint, not just Azure.
- **Version and configuration values that are provider-specific**: keep the vendor prefix. Example: `AZURE_OPENAI_API_VERSION` is Azure-specific and correctly named.

**Rule:** if a variable controls behavior that only applies to one vendor, use the vendor prefix. If a variable controls behavior that could apply to any vendor of a given type (e.g., any OpenAI-compatible provider), do not use a vendor prefix.

### Model registry keys

Registry keys in `MODELS` reflect the vendor's own naming for the model:

- Preserve version numbers and decimal points as the vendor writes them: `grok-4-3`, `Kimi-K2.6`, `DeepSeek-V4-Flash`, `Qwen3.7-Max`.
- Case follows vendor convention. xAI/Grok uses lowercase; Moonshot, DeepSeek, and Alibaba use PascalCase.
- Do not normalize casing. Judges, collaborators, and API calls all expect the vendor's own spelling.

### Registry entry fields

Fields use `snake_case` with descriptive suffixes:

- Values that reference environment variables by name use `_env_var` suffix: `endpoint_env_var`, `api_key_env_var`.
- Values that are literal strings use the direct field name: `deployment_name`.
- Numeric limits use the noun form: `max_tokens`.

### SQLite tables and columns

- Table names use `snake_case`: `messages`, `sessions`.
- Column names use `snake_case`: `session_id`, `last_used_at`, `deployment_name` (where applicable).
- Primary key columns are either `id` (for autoincrement integer keys, as in `messages`) or the meaningful natural key (as `session_id` in `sessions`).
- `CHECK` constraints are used to enforce enum-like columns (e.g., `role IN ('user', 'assistant', 'system', 'tool')`).

### CLI flags

CLI flags use double-dash and lowercase words connected by hyphens: `--new`, `--session`, `--label`, `--oneshot`, `--history`, `--sessions`. Single-letter flags are not currently used. Multi-word flags (should they be added) use hyphenation: `--tool-name`, `--from-session`.

### Slash commands

Slash commands use a leading `/` and lowercase, no punctuation, single words where possible: `/exit`, `/new`, `/sessions`, `/switch`, `/label`, `/history`, `/tool`. Command arguments follow the command name with a single space separator.

## 6. Operator Workflow

The KAAAGLUMN codebase is developed under a specific operator discipline that has been proven across multiple refactors. The discipline was earned rather than designed. Each rule below maps to a class of failure that occurred at least once during KAAAGLUMN's development: unauthorized modifications to production files, structurally broken code that would have shipped without review, smoke tests that failed on environment mismatches, unauthorized commits proposed by an AI collaborator. Each failure produced a rule.

The discipline is not enforced by tooling. It depends on complete state reporting across AI contexts. KAAAGLUMN has no visibility into Cursor's execution harness. Cursor has no visibility into the strategic conversations conducted in Claude. Claude has no visibility into what the operator types directly into KAAAGLUMN's REPL. Each context is partial. The operator is the only participant with visibility into all of them and is therefore responsible for surfacing state across contexts. Rules are followed when state is shared. Failures occur when any context proceeds on assumptions rather than verified information.

### Diff-first proposal

No change lands in production code without a reviewed diff. When a change is being proposed by an AI collaborator (KAAAGLUMN drafting for Cursor, Cursor implementing for the operator), the sequence is:

1. AI collaborator produces a unified diff of the proposed change against the current file
2. Operator reviews the diff before any file is modified
3. Only after explicit operator approval does the change land in the target file

Diffs that are too long to review in a single terminal buffer should be written to a scratch file (e.g. `_diff_preview.txt`) that the operator can read from disk. The scratch file is gitignored and deleted after approval.

### Scratch files for larger changes

Changes that materially rewrite a file must first land in a scratch file, not the target file. Naming convention: `<original_filename>_<purpose>_v1.py`, for example, `chat_streaming_proposal.py`, `chat_sessions_v1.py`, `chat_harden_v1.py`. The scratch file exists to:

- Let the operator see the entire proposed file in one place rather than only the diff
- Let compile checks and unit-testable behavior run against the scratch file without risking the working file
- Provide a rollback point if the change turns out to be wrong

Scratch files are gitignored via the `_diff*`, `_apply*`, `_build*` patterns and are deleted immediately after the change is promoted to production.

### Compile check before smoke test

Every material change to a Python file passes a compile check before any runtime test:

```
.\.venv\Scripts\python.exe -m py_compile <file>
```

Bare `python` is never used in KAAAGLUMN commands. The venv Python is always invoked explicitly, either via the full path or via the `kagu` alias defined in the PowerShell `$PROFILE`. Compile failures are addressed before any smoke test is attempted.

### Live smoke test in real PowerShell

REPL behavior can only be verified in a real Windows PowerShell console. Automated test harnesses that spawn Python subprocesses fail with `NoConsoleScreenBufferError` because `prompt_toolkit` requires an actual TTY. Smoke tests for REPL features are therefore always executed by the operator, in a real terminal, with real Grok/Kimi/Qwen credit spend.

Non-REPL code paths (helper functions, unit-testable logic) may be verified through `--oneshot` mode or standalone unit tests, both of which run correctly in AI collaborator harnesses.

### Git status before and after Cursor sessions

Every Cursor session begins and ends with `git status` verification. Before a session: confirm the working tree is clean or the outstanding changes are known. After a session: confirm only the intended files were modified. Unauthorized modifications (Cursor going off-script) are caught this way. When such modifications occur, they are corrected before proceeding.

### No commit or push without explicit approval

Cursor never commits or pushes on its own initiative. The commit and push commands are always run by the operator, in the operator's own PowerShell session, with the operator's own credentials. Commit messages are drafted by the operator, sometimes with input from KAAAGLUMN.

### `kagu` alias for daily invocation

The `kagu` function is defined in the operator's PowerShell `$PROFILE`:

```powershell
function kagu { & "C:\WendScope\KAAAGLUMN\.venv\Scripts\python.exe" "C:\WendScope\KAAAGLUMN\chat.py" @args }
```

This allows KAAAGLUMN to be invoked from any directory with `kagu`, `kagu --new`, `kagu --sessions`, etc. The alias is a convenience layer only; the underlying Python and script paths must remain valid.

## 7. AI Collaboration Protocol

The KAAAGLUMN codebase is developed by an operator working with multiple AI collaborators, each with distinct responsibilities and boundaries. The operator is the only participant with authority to modify production code, commit changes, or push to any repository.

### Effective date and scope

This protocol is effective July 12, 2026. Behavior in the KAAAGLUMN codebase prior to this date followed a similar discipline but was not formally documented. Deviations from this protocol after the effective date are noted explicitly rather than silently absorbed. When any participant proposes to work outside the protocol, they name the exception, name the reason, and obtain operator approval.

### Roster and roles

The specific AI collaborators filling each role in this protocol have changed over WendScope Labs' history and are expected to change again. The protocol names roles rather than tools. Substitution of one tool for another in a given role does not require amendment of this document, provided the successor tool operates within the same responsibilities and boundaries.

Current roster as of July 12, 2026:

- Strategic reasoning surface: **Claude** (Anthropic)
- Memory layer and Cursor-prompt author: **KAAAGLUMN** (Grok 4.3 as host in private; Qwen 3.7-Max as host in public)
- Code execution surface: **Cursor**
- Web-context and cross-tab reasoning surface: **Copilot** (Microsoft)

Copilot's specific value is contextual awareness of open web pages and browser state that other collaborators cannot see. A substantial portion of WendScope Labs' pivot from earlier planning was conducted across multiple Copilot conversations before formalization in this workflow. Copilot remains active in the roster, primarily for research, verification, and browser-context work that Claude and KAAAGLUMN cannot perform.

Historical roster: Prior collaborator lineups included Perplexity (research), ChatGPT (OpenAI, strategic reasoning), and Gemini (Google, verification). Those tools are no longer part of the active collaboration loop as of the effective date of this protocol, though the operator may return to any of them ad hoc for verification purposes without amendment to this document. Future roster changes will be reflected in updated versions of this document.

Roles are what govern. Current occupants are named for clarity.

### Claude

Claude serves as the strategic reasoning surface. Its responsibilities include architectural review, tradeoff analysis, drafting of specifications, review of proposed changes, and honest assessment of viability and risk. Claude has no direct file access. It cannot read the KAAAGLUMN codebase, cannot execute code, and cannot invoke any other AI collaborator without operator relay.

Claude drafts prompts intended for KAAAGLUMN or Cursor. Prompts intended for downstream execution are presented to the operator in an unambiguous format and are only executed after the operator explicitly pastes them into the target context.

Claude does not decide on behalf of the operator. When multiple defensible paths exist, Claude presents tradeoffs and defers the choice. When the operator requests a recommendation, Claude gives one and names it as such.

### KAAAGLUMN

KAAAGLUMN serves as the memory layer and Cursor-prompt author. Its responsibilities include maintaining conversation state across sessions, drafting Cursor tasks under the operator's specification, and applying the two-register analytical stance defined in its system prompt to any authored work. KAAAGLUMN has no direct file access outside its own SQLite database. It cannot read repository files, cannot execute code, and cannot invoke Cursor directly.

KAAAGLUMN drafts Cursor prompts by translating operator specifications into structured task instructions. The drafts are reviewed by the operator (with or without Claude's assistance) before being pasted into Cursor. KAAAGLUMN does not receive tool outputs directly; specialist tool consultation is silent by design, with the tool's response integrated into the host synthesis before reaching the operator.

KAAAGLUMN's context is limited by the SQLite conversation memory and the token budget of the host model. Large information transfers into KAAAGLUMN's context (e.g., feeding it entire file contents) are possible but expensive in tokens and can degrade response quality. Large transfers should be handled by Cursor's file access instead when feasible.

### Cursor

Cursor serves as the code execution surface. Its responsibilities include reading files, proposing diffs, applying approved changes, running compile checks, executing test commands, and reporting results. Cursor has direct file access to the KAAAGLUMN and kaaaglumn-basilica repositories on the operator's machine and can execute PowerShell commands under the permissions granted by the operator.

Cursor operates under the diff-first discipline defined in Section 6. Every proposed change is presented as a diff (or a scratch file for larger changes) before any target file is modified. Cursor does not commit or push to any repository. Cursor does not modify files outside the scope of an authorized task.

Cursor reports completion using a structured format that names files touched, verifications passed, and any observations discovered during execution. When Cursor encounters ambiguity or a gap in the task specification, it surfaces the question rather than proceeding on assumption.

### The operator

The operator is the only participant authorized to modify production code, commit changes, push to remotes, or grant any AI collaborator new permissions. The operator is responsible for cross-context state reporting as defined in Section 6.

The operator drafts specifications, reviews AI-authored output, and resolves ambiguity when any AI collaborator surfaces a question. The operator's approval is required at every gate: diff review, compile check acceptance, smoke test verification, promotion to production, commit, and push.

### Cross-context handoffs

The workflow for a typical change follows a defined pattern:

1. Operator (possibly with Claude) drafts a specification
2. Claude drafts a prompt for KAAAGLUMN, if KAAAGLUMN's involvement is desired
3. KAAAGLUMN drafts a Cursor prompt following the specification
4. Operator reviews the KAAAGLUMN-drafted prompt, possibly with Claude's review
5. Operator pastes the reviewed prompt to Cursor
6. Cursor proposes the change as a diff or scratch file
7. Operator reviews the proposed change (possibly with Claude's assistance) before approving
8. Cursor applies the approved change and runs verification
9. Operator runs manual smoke tests when required
10. Operator commits and pushes

Simpler changes may collapse steps. Complex changes may add iteration cycles at any gate. Every step is optional at operator discretion except the operator's own authorization gates, which are non-negotiable.

### Reference discipline

All AI collaborators are expected to reference this document when making or reviewing changes to the KAAAGLUMN codebase. Cursor task prompts should explicitly cite the relevant section (e.g., "per Section 3, the model registry entry shape requires the following fields..."). KAAAGLUMN should reference the document when drafting Cursor prompts. Claude should reference the document when reviewing proposed changes.

When any AI collaborator's proposed action would contradict this document, the contradiction is surfaced to the operator before the action is taken. The operator resolves the contradiction by either amending the document or rejecting the proposed action.

## 8. Extension Points

The KAAAGLUMN codebase has defined extension points for common categories of new capability. Additions that match one of these patterns should follow the pattern rather than inventing new structure. Additions that do not match any pattern should be reviewed against Section 5 (Naming Conventions) and Section 6 (Operator Workflow) before implementation.

### Adding a new model

To register a new model for host or tool use, add an entry to the `MODELS` dictionary in `models.py`:

```python
MODELS["Qwen3.7-Max"] = {
    "deployment_name": "qwen3.7-max",
    "endpoint_env_var": "QWEN_CLOUD_ENDPOINT",
    "api_key_env_var": "QWEN_CLOUD_API_KEY",
    "max_tokens": 4096,
}
```

Required fields: `deployment_name`, `endpoint_env_var`, `api_key_env_var`, `max_tokens`. The `endpoint_env_var` and `api_key_env_var` fields hold *names* of environment variables, not values.

To make the new model the default host, update `DEFAULT_MODEL` in `models.py`. To make it available only as a tool, leave `DEFAULT_MODEL` unchanged; users can then invoke it with `/tool <ModelKey> <prompt>`.

If the new model's endpoint is not on Azure Foundry (does not contain `services.ai.azure.com`), the operator must set `API_MODE=foundry_v1` in `.env` to force the OpenAI-compatible client path.

No other files require modification for basic model support. The `check_env` helper in `chat.py` reads the endpoint and api key env vars automatically once the registry entry is present.

### Adding a new slash command

Slash commands are dispatched via sequential `if` statements inside `run_repl()`, not through a dispatch table or function map. Commands with no arguments use exact equality matching (e.g., `if prompt == "/exit"`). Commands with arguments use `startswith` matching (e.g., `if prompt.startswith("/switch")`).

To add a new slash command:

1. **Update the dispatch block** in `run_repl()`. Add a new `if prompt == "/mycommand":` or `if prompt.startswith("/mycommand"):` block among the existing built-in command checks. Each block must end with `continue` to return to the input loop.
2. **Implement the handler** as a function following the private-helper convention (e.g., `_repl_mycommand(conn, session_id, prompt)`). Handlers should follow the signatures of existing handlers like `_repl_switch`, `_repl_label`, `list_sessions`.
3. **Update the REPL banner** by editing the hardcoded string inside `_print_banner()`. The command help text is a single multi-line print statement; add the new command's description to that string.
4. **If the command persists state**, extend the SQLite schema per Section 3 conventions and follow the migration pattern of `_ensure_sessions_table`.

Note: `/tool` is not dispatched in `run_repl()` directly. It is handled inside `_run_turn()` via `prompt.startswith("/tool")`, which routes to `_run_tool_turn`. New commands with similar deferred routing should be documented explicitly.

Existing handlers to use as reference: `list_sessions`, `_repl_switch`, `_repl_label`, `show_history`, `_run_tool_turn`, `_parse_tool_command`.

### Adding a new tool

Tools are invoked via the existing `/tool <ModelKey> <prompt>` pattern. `_run_tool_turn()` is model-agnostic: it parses the tool name from the prompt via `_parse_tool_command(prompt)`, calls `call_model([{"role": "user", "content": inner_prompt}], tool_name)`, then synthesizes the tool output into the host response via the `TOOL_SYSTEM_TEMPLATE`.

To add a new tool:

1. Register the tool's model in `MODELS` (per "Adding a new model" above)
2. The tool is invocable immediately via `/tool <ModelKey> <prompt>`, no changes to `_run_tool_turn` or dispatch code are required

The silent-tool contract from Section 6 applies: specialist tool output does not stream to the terminal. Only the host synthesis after the tool completes is visible. This is enforced by the `model_name != DEFAULT_MODEL` early return in `call_model()`.

### Adding a new CLI flag

CLI flags are parsed in `main()` in `chat.py`. Follow the existing flag conventions defined in Section 5. Mutual exclusivity checks (like `--session` x `--new` and `--new` x `--label`) are enforced explicitly with conditional logic in `main()`; new mutually-exclusive combinations must be added there.

### Adding a new SQLite table

New tables should:

- Follow `snake_case` naming per Section 5
- Include a migration function (following the pattern of `_ensure_sessions_table`) that creates the table if absent and backfills from existing data where meaningful
- Use `CHECK` constraints for enum-like columns
- Add appropriate indexes for expected query patterns via `CREATE INDEX IF NOT EXISTS` statements in `get_db()` (see the two existing indexes on `messages`: `idx_session` on `session_id` and `idx_timestamp` on `timestamp`)

Migrations run automatically on database open via `get_db()`. Never modify the schema of the `messages` table in a breaking way; extend by adding columns with defaults or by adding new tables.

Note: the current `sessions` table has no indexes. If session lookups by label become a performance concern (currently unlikely at operator-scale usage), add `CREATE INDEX IF NOT EXISTS idx_sessions_label ON sessions(label)`.

### Adding a new environment variable

Follow the prefix conventions in Section 5:

- Vendor-specific credentials use the vendor prefix (`QWEN_CLOUD_API_KEY`)
- Cross-cutting toggles do not use a vendor prefix (`API_MODE`)
- Add the variable and an example value to `.env.example`
- Document the variable in Section 4 of this document

Environment variables are read in three places. `foundry_client.py` reads values needed for client construction (`API_MODE`, `AZURE_OPENAI_API_VERSION`, and the endpoint/api-key values referenced by name in the model registry). `chat.py`'s `check_env` helper reads env-var presence via the model registry to detect missing configuration. `call_foundry.py` reads `AZURE_OPENAI_API_KEY` directly for diagnostic display purposes. Whether the separation reflects a deliberate design choice or historical accumulation is undocumented; consolidation to a single source of truth may or may not be warranted depending on that intent.

### Adding a new file

New Python modules follow `snake_case.py` naming and should have a clear single responsibility. Update Section 2 (File Responsibilities) when adding a new module. Update Section 3 (Interfaces and Contracts) if the new module exposes new data structures or function signatures other modules depend on.

### Adding a new documentation file

Canonical reference documents use `UPPER_SNAKE_CASE.md` (per Section 5). This document itself follows that convention. When a new reference document is added, it should be linked from `README.md` and, if it establishes conventions other documents should follow, referenced from Section 7 of this document.
