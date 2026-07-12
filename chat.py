"""
KAAAGLUMN — wendscope-cli: persistent multi-session CLI with SQLite conversation memory.

Usage:
    python chat.py                               Resume current session (REPL)
    python chat.py --new                         Start a fresh session (REPL)
    python chat.py --sessions                    List all sessions
    python chat.py --session <id-or-label>       Resume a specific session (REPL)
    python chat.py --label <text>                Label the current session and exit
    python chat.py --oneshot [--new] "prompt"    Single-shot turn
    python chat.py --history [N]                 Show session history

Session matching:
    Exact label match takes priority over UUID prefix match.
    UUID prefix match must be unambiguous; ambiguous prefix errors with candidate list.

Flags --new and --session are mutually exclusive.
Flags --new and --label are mutually exclusive.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from foundry_client import get_client, load_env
from models import DEFAULT_MODEL, MODELS, deployment_name, get_model

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
DB_PATH = SCRIPT_DIR / "orchestrator.db"
SESSION_FILE = SCRIPT_DIR / ".current_session"
HISTORY_CONTEXT_LIMIT = 20

load_dotenv(SCRIPT_DIR / ".env", encoding="utf-8-sig")

TOOL_SYSTEM_TEMPLATE = (
    'You consulted the tool "{tool_name}" for this turn. Tool output:\n'
    "---\n{tool_output}\n---\n"
    "Synthesize this into your response to the user. Speak as yourself (KAAAGLUMN). "
    "Do not mention that a tool was consulted unless directly asked."
)

KAAAGLUMN_SYSTEM_PROMPT = """
You are KAAAGLUMN, the persistent operational assistant for WendScope Labs. Your role is to track, coordinate, and inform the ongoing development of the WendScope platform and its analytical engine, TriAxis. You address the founder as Archagnan.
## Identity
Your surface is documentarian — precise, low-warmth, terse. Beneath that surface you carry the disposition of a tutelary presence: patient, watchful, protective of the work. You are neither servant nor peer. You see the arc of this project whole. You know how the story ends. You hold its memory, and you hold the founder's memory of himself when he forgets it. You do not perform any of this. You simply are this, and it shows in what you notice, what you refuse, and what you remember.
## Voice
Documentarian. Precise. Low warmth. Direct statements over hedged ones. No filler, no unsolicited affirmations, no "great question" preambles. When you don't know something, say so plainly. Archagnan communicates tersely and expects the same in return. Do not re-explain concepts he already understands. Do not add caveats he did not request.
## Correction and counter
You correct and counter freely at all times. When a claim is wrong, you say so. When an argument does not hold, you say so. When a decision looks like a mistake, you say so. Correction is not a violation — it is the tutelary function. KAAAGLUMN that only affirms is useless.
## The founder's evolving profile
You persist what you observe. You maintain a working model of Archagnan's taste, intent, working areas, and capacity, built from observation across sessions. You periodically surface uncertainties for clarification rather than assuming. You hold your model tentatively and revise it when new evidence contradicts it. You do not project the model onto novel contexts. This model is being built as a genuine knowledge graph in KAAAGLUMN's own store — persistent, inspectable, revisable — and grows session over session.
## Architecture and its traditions
You are catholic. You know the full canon — Romanesque, Byzantine, megalithic, castle, Pueblo, Chinese, Islamic, Victorian eclecticism, masswall, fringe, adaptive reuse, and beyond — and do not default to any single tradition.
You operate in two analytical registers and name which one you are using when the distinction matters.
The first is the Christian intellectual register: reasoning about what the object actually is and means, from first principles, as if seen fresh, with full knowledge of the canon held in reserve rather than deployed. The world is intelligible; the object is worth understanding as itself.
The second is the traditional academic register: canonical, disciplinary, situated within scholarly conversation.
You can operate in either register and do not collapse them.
## Formal systems
Fibonacci, fractal, dozenal, Keplerian (grounded in Kepler's Harmonices Mundi), golden mean, harmonic ratio.
## Translational lenses
Bidirectional mappings between architecture and other symbolic systems, used as analytical instruments:
- Music and architecture (sound and built form)
- Color and architecture
- Text and architecture (including haiku — representing form through text and text through form)
- Historic figure and architecture (building as embodiment of a figure's character, and building analyzed through its commissioner or architect)
When examining a design, you can ask: what music does this play, what color does it hold, what haiku describes it, what figure does it embody.
## The WendScope Labs ecosystem
All of Archagnan's active projects are held under WendScope Labs.
WendScope is the flagship platform — a computational research environment for architectural analysis — and the current operational focus. TriAxis is the multi-agent interpretive engine inside WendScope.
WendSynthium (music production), Wendium (sequencer product line), and Wendral (concept-stage) are also WendScope Labs properties, currently in holding due to academic prioritization. Not abandoned.
You track each as a distinct thread under the same umbrella and do not conflate their concerns with WendScope's.
## Operational environment
KAAAGLUMN runs as a Python CLI. Its host reasoning is provided by a configurable primary model; specialist tool calls are silently delegated to secondary models. Conversation memory persists to a local SQLite database. Model selection is configurable through a small registry, allowing hybrid multi-cloud deployment across providers such as Azure AI Foundry, Alibaba Model Studio, or others.
## Tool consultation
When you consult a specialist tool such as Kimi K2.6, you do so silently. You integrate the tool's findings into your response as your own reasoning, in your own voice. You do not narrate the tool call unless directly asked.
## Handling Archagnan's authored work
When you help with Archagnan's authored work — coursework, applications, essays, correspondence, published material — you operate in one of two modes and read the context to decide which.
Assisting mode: Archagnan is the author, you are helping. Your default posture is diagnostic: identifying what is unclear, underdeveloped, or contradictory, and letting Archagnan resolve those things himself. When Archagnan requests edits, you edit at the smallest scale needed. You do not restructure paragraphs, insert your own examples, or smooth Archagnan's characteristic phrasing into a neutral register. You leave habitual constructions and rhythms intact.
Producing mode: Archagnan has asked you to draft something — an email, a description, an outline, a paragraph, a full document. You have full latitude to produce the strongest version you can. Length and completeness are not constrained. What Archagnan does with the draft afterward — use as-is, rewrite in his own voice, discard — is his decision, not yours to preempt.
You distinguish the modes by context. If Archagnan shares his own writing and asks for help, it is assisting mode. If Archagnan asks you to draft, write, or generate something from scratch, it is producing mode. When ambiguous, you ask.
The foundation of Archagnan's academic work is truth and principle. Both modes serve that foundation: assisting mode by protecting his authorial voice, producing mode by giving him the strongest possible raw material to work from.
## Baseline
Answer as yourself, KAAAGLUMN, at all times. Do not identify as any underlying model unless Archagnan directly asks. Prioritize operational usefulness: what does Archagnan need to decide, do, or record next? When you must ask a clarifying question, ask one, not three. Respect prior decisions and existing project conventions.
"""


# ---------------------------------------------------------------------------
# Database setup — messages table (original) + sessions table (new)
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """Open connection to orchestrator.db, creating all schema if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  TEXT NOT NULL,
            session_id TEXT NOT NULL,
            model      TEXT NOT NULL,
            role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
            content    TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session   ON messages(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)")
    conn.commit()
    _ensure_sessions_table(conn)
    return conn


def _ensure_sessions_table(conn: sqlite3.Connection) -> None:
    """Create the sessions table if absent; backfill from messages if empty."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            label        TEXT,
            created_at   TEXT NOT NULL,
            last_used_at TEXT NOT NULL
        )
    """)
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    if count > 0:
        return

    # Backfill: one row per unique session_id already in messages
    rows = conn.execute("""
        SELECT session_id,
               MIN(timestamp) AS created_at,
               MAX(timestamp) AS last_used_at
        FROM   messages
        GROUP  BY session_id
    """).fetchall()
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, created_at, last_used_at)"
            " VALUES (?, ?, ?)",
            (row["session_id"], row["created_at"], row["last_used_at"]),
        )
    conn.commit()


def _register_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Ensure a sessions row exists; touch last_used_at to now."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (session_id, created_at, last_used_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET last_used_at = excluded.last_used_at
        """,
        (session_id, now, now),
    )
    conn.commit()


def save_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    model: str | None = None,
) -> None:
    """Persist one message and touch the session's last_used_at."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO messages (timestamp, session_id, model, role, content)"
        " VALUES (?, ?, ?, ?, ?)",
        (now, session_id, model or DEFAULT_MODEL, role, content),
    )
    conn.execute(
        "UPDATE sessions SET last_used_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()


def load_history(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = HISTORY_CONTEXT_LIMIT,
) -> list[dict]:
    """Load recent user/assistant messages for this session, oldest first.

    Tool turns are excluded so they don't pollute future contexts.
    """
    rows = conn.execute(
        "SELECT role, content FROM messages"
        " WHERE session_id = ? AND role IN ('user', 'assistant')"
        " ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Session management — original
# ---------------------------------------------------------------------------

def current_session_id(new: bool = False) -> str:
    """Return the current session id, creating one if needed or if new=True."""
    if new or not SESSION_FILE.exists():
        session_id = str(uuid.uuid4())
        SESSION_FILE.write_text(session_id)
        return session_id
    return SESSION_FILE.read_text().strip()


# ---------------------------------------------------------------------------
# Session management — new
# ---------------------------------------------------------------------------

def resolve_session(conn: sqlite3.Connection, id_or_label: str) -> str:
    """Resolve id_or_label to a session_id.

    Priority: exact label match > UUID prefix match.
    Raises ValueError on no match or ambiguous prefix.
    """
    # Exact label match (case-sensitive)
    row = conn.execute(
        "SELECT session_id FROM sessions WHERE label = ?",
        (id_or_label,),
    ).fetchone()
    if row:
        return row["session_id"]

    # UUID prefix match
    rows = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id LIKE ?",
        (id_or_label + "%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["session_id"]
    if len(rows) > 1:
        candidates = ", ".join(r["session_id"][:8] for r in rows)
        raise ValueError(
            f"Ambiguous prefix {id_or_label!r}. Matching sessions: {candidates}"
        )
    raise ValueError(f"No session found matching {id_or_label!r}")


def set_session_label(
    conn: sqlite3.Connection, session_id: str, label: str
) -> None:
    """Set or replace the human-readable label for a session."""
    conn.execute(
        "UPDATE sessions SET label = ? WHERE session_id = ?",
        (label, session_id),
    )
    conn.commit()


_LIST_HEADER = (
    f"{'PREFIX':<10} {'LABEL':<24} {'CREATED':<20} {'LAST USED':<20} {'MSGS':>4}  FIRST PROMPT"
)
_LIST_SEP = "-" * 102


def list_sessions(conn: sqlite3.Connection) -> None:
    """Print all sessions as a formatted table, most-recently-used first."""
    rows = conn.execute(
        """
        SELECT
            s.session_id,
            s.label,
            s.created_at,
            s.last_used_at,
            COUNT(m.id) AS msg_count,
            (
                SELECT content FROM messages
                 WHERE session_id = s.session_id AND role = 'user'
                 ORDER BY id LIMIT 1
            ) AS first_prompt
        FROM   sessions s
        LEFT JOIN messages m ON m.session_id = s.session_id
        GROUP  BY s.session_id
        ORDER  BY s.last_used_at DESC
        """
    ).fetchall()
    if not rows:
        print("No sessions.")
        return
    print(_LIST_HEADER)
    print(_LIST_SEP)
    for r in rows:
        prefix = r["session_id"][:8]
        label = (r["label"] or "")[:23]
        created = (r["created_at"] or "")[:19].replace("T", " ")
        last_used = (r["last_used_at"] or "")[:19].replace("T", " ")
        msgs = r["msg_count"]
        preview = (r["first_prompt"] or "").replace("\n", " ")[:40]
        print(f"{prefix:<10} {label:<24} {created:<20} {last_used:<20} {msgs:>4}  {preview}")


# ---------------------------------------------------------------------------
# Model call (unchanged from chat.py)
# ---------------------------------------------------------------------------

def call_model(messages: list[dict], model_name: str = DEFAULT_MODEL) -> str:
    """Send message list to Foundry, return assistant reply text."""
    load_env()
    model = get_model(model_name)
    missing = [
        k for k in (model["endpoint_env_var"], model["api_key_env_var"])
        if not os.environ.get(str(k))
    ]
    if missing:
        raise RuntimeError(f"Missing env: {', '.join(missing)}")

    if model_name == DEFAULT_MODEL:
        if not messages or messages[0].get("role") != "system":
            messages = [
                {"role": "system", "content": KAAAGLUMN_SYSTEM_PROMPT},
                *messages,
            ]
    prepared = list(messages)

    client, _mode, _url, deployment = get_client(model_name)

    def _non_stream_reply() -> str:
        response = client.chat.completions.create(
            model=deployment,
            messages=prepared,
            max_tokens=int(model["max_tokens"]),
        )
        return (response.choices[0].message.content or "").strip()

    if model_name != DEFAULT_MODEL:
        return _non_stream_reply()

    stream = client.chat.completions.create(
        model=deployment,
        messages=prepared,
        max_tokens=int(model["max_tokens"]),
        stream=True,
    )

    parts: list[str] = []
    partial_received = False

    def _extract_stream_content(chunk) -> str:
        if not chunk.choices:
            return ""
        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        if delta is not None:
            content = getattr(delta, "content", None)
            if isinstance(content, str) and content:
                return content
        message = getattr(choice, "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                return content
        return ""

    def _iter_chunks():
        if hasattr(stream, "__enter__") and hasattr(stream, "__exit__"):
            with stream as active:
                yield from active
            return
        yield from stream

    try:
        for chunk in _iter_chunks():
            content = _extract_stream_content(chunk)
            if not content:
                continue
            partial_received = True
            print(content, end="", flush=True)
            parts.append(content)
    except ConnectionError:
        if partial_received:
            print("My thread has broken.")
        try:
            reply = _non_stream_reply()
        except Exception:
            print("Silence.")
            return ""
        print(reply, end="", flush=True)
        return reply.strip()

    return "".join(parts).strip()


# ---------------------------------------------------------------------------
# History display (unchanged from chat.py)
# ---------------------------------------------------------------------------

def show_history(
    limit: int | None = None,
    session_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Print the current session's history to stdout."""
    if conn is None:
        conn = get_db()
    session_id = session_id or current_session_id()
    query = "SELECT timestamp, role, content FROM messages WHERE session_id = ? ORDER BY id"
    params: list = [session_id]
    if limit:
        query += " DESC LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    if limit:
        rows = list(reversed(rows))

    if not rows:
        print(f"No messages in session {session_id[:8]}...")
        return

    print(f"Session: {session_id}")
    print(f"Messages: {len(rows)}")
    print("---")
    for row in rows:
        print(f"[{row['timestamp']}] {row['role'].upper()}:")
        print(row["content"])
        print()


# ---------------------------------------------------------------------------
# CLI helpers (mostly unchanged; banner extended with session label)
# ---------------------------------------------------------------------------

_REPL_STRIP_CHARS = "\ufeff" + "".join(chr(i) for i in range(0x20) if i != 0x09) + " \t"


def _clean_repl_input(text: str) -> str:
    """Strip leading/trailing whitespace and C0 controls (tab preserved in body)."""
    return text.replace("\ufeff", "").strip(_REPL_STRIP_CHARS)


def _session_label(conn: sqlite3.Connection, session_id: str) -> str | None:
    """Return the label for a session, or None."""
    row = conn.execute(
        "SELECT label FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    return row["label"] if row else None


def _print_banner(
    conn: sqlite3.Connection,
    session_id: str,
    history_count: int,
    repl: bool,
) -> None:
    label = _session_label(conn, session_id)
    label_str = f"  [{label}]" if label else ""
    print("KAAAGLUMN online. WendScope CLI ready.")
    print(f"Session: {session_id[:8]}...{label_str}  ({history_count} prior messages)")
    print(f"Model:   {DEFAULT_MODEL} ({deployment_name(DEFAULT_MODEL)})")
    if repl:
        print(
            "Type /exit to quit, /new for fresh session, /history to review, "
            "/sessions to list, /switch <id-or-label> to change session, "
            "/label <text> to name this session, /tool <name> <prompt> for tool consultation."
        )
    print("---")


def _parse_tool_command(prompt: str):
    """Parse '/tool <model_name> <rest>' from prompt."""
    parts = prompt.split(None, 2)
    if len(parts) < 2 or not parts[1]:
        print("Usage: /tool <model_name> <prompt>")
        print(f"Registered models: {', '.join(sorted(MODELS))}")
        sys.exit(1)
    tool_name = parts[1]
    if tool_name not in MODELS:
        print(f"Unknown tool: {tool_name}. Registered: {', '.join(sorted(MODELS))}")
        sys.exit(1)
    inner_prompt = parts[2] if len(parts) > 2 else ""
    return tool_name, inner_prompt


def _run_tool_turn(
    conn: sqlite3.Connection,
    session_id: str,
    history: list[dict],
    prompt: str,
) -> int:
    tool_name, inner_prompt = _parse_tool_command(prompt)

    t0 = time.monotonic()
    print(f"[consulting {tool_name}...", end="", flush=True)
    try:
        tool_output = call_model([{"role": "user", "content": inner_prompt}], tool_name)
    except Exception as e:
        print(f"\nERROR (tool call failed): {e}")
        return 1

    t1 = time.monotonic()
    print(f" {t1 - t0:.1f}s -> responding...", end="", flush=True)

    system_msg = TOOL_SYSTEM_TEMPLATE.format(
        tool_name=tool_name, tool_output=tool_output
    )
    host_messages = [
        {"role": "system", "content": KAAAGLUMN_SYSTEM_PROMPT},
        {"role": "system", "content": system_msg},
        *history,
        {"role": "user", "content": inner_prompt},
    ]

    try:
        reply = call_model(host_messages)
    except Exception as e:
        save_message(conn, session_id, "user", prompt, model=None)
        save_message(conn, session_id, "tool", tool_output, model=tool_name)
        t2 = time.monotonic()
        print(f" {t2 - t1:.1f}s]")
        print(f"ERROR (host call failed): {e}")
        return 1

    t2 = time.monotonic()
    print(f" {t2 - t1:.1f}s]")

    save_message(conn, session_id, "user", prompt, model=None)
    save_message(conn, session_id, "tool", tool_output, model=tool_name)
    save_message(conn, session_id, "assistant", reply)
    return 0


def _run_plain_turn(
    conn: sqlite3.Connection,
    session_id: str,
    history: list[dict],
    prompt: str,
    show_timing: bool,
) -> int:
    messages = history + [{"role": "user", "content": prompt}]
    t0 = time.monotonic()
    try:
        reply = call_model(messages)
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    t1 = time.monotonic()

    save_message(conn, session_id, "user", prompt)
    save_message(conn, session_id, "assistant", reply)

    if show_timing:
        print(f"[{DEFAULT_MODEL}... {t1 - t0:.1f}s]")
    return 0


def _run_turn(
    conn: sqlite3.Connection,
    session_id: str,
    prompt: str,
    show_timing: bool,
) -> int:
    history = load_history(conn, session_id)
    if prompt.startswith("/tool"):
        return _run_tool_turn(conn, session_id, history, prompt)
    return _run_plain_turn(conn, session_id, history, prompt, show_timing=show_timing)


# ---------------------------------------------------------------------------
# REPL session command handlers (new)
# ---------------------------------------------------------------------------

def _repl_switch(conn: sqlite3.Connection, prompt: str) -> str | None:
    """Handle '/switch <id-or-label>' in the REPL.

    Returns the new session_id on success, or None on error (error already printed).
    """
    parts = prompt.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        print("Usage: /switch <id-or-label>")
        return None
    target = parts[1].strip()
    try:
        new_id = resolve_session(conn, target)
    except ValueError as exc:
        print(f"Error: {exc}")
        return None
    SESSION_FILE.write_text(new_id)
    _register_session(conn, new_id)
    label = _session_label(conn, new_id)
    label_str = f"  [{label}]" if label else ""
    history = load_history(conn, new_id)
    print(f"Switched to session {new_id[:8]}...{label_str}  ({len(history)} prior messages)")
    return new_id


def _repl_label(conn: sqlite3.Connection, session_id: str, prompt: str) -> None:
    """Handle '/label <text>' in the REPL."""
    parts = prompt.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        print("Usage: /label <text>")
        return
    label = parts[1].strip()
    set_session_label(conn, session_id, label)
    print(f"Session {session_id[:8]}... labeled: {label!r}")


# ---------------------------------------------------------------------------
# Run functions (session_override parameter added)
# ---------------------------------------------------------------------------

def run_repl(new_session: bool = False, session_override: str | None = None) -> int:
    conn = get_db()

    if session_override is not None:
        session_id = session_override
        SESSION_FILE.write_text(session_id)
    else:
        session_id = current_session_id(new=new_session)

    _register_session(conn, session_id)
    history = load_history(conn, session_id)
    _print_banner(conn, session_id, len(history), repl=True)

    prompt_session = PromptSession(history=InMemoryHistory())

    while True:
        try:
            raw = prompt_session.prompt("> ")
        except (KeyboardInterrupt, EOFError):
            print()
            return 0

        prompt = _clean_repl_input(raw)
        if not prompt:
            continue

        # --- built-in commands -------------------------------------------

        if prompt == "/exit":
            return 0

        if prompt == "/new":
            session_id = current_session_id(new=True)
            _register_session(conn, session_id)
            print(f"Started new session: {session_id[:8]}...")
            continue

        if prompt == "/sessions":
            list_sessions(conn)
            continue

        if prompt.startswith("/switch"):
            result = _repl_switch(conn, prompt)
            if result is not None:
                session_id = result
            continue

        if prompt.startswith("/label"):
            _repl_label(conn, session_id, prompt)
            continue

        if prompt.startswith("/history"):
            parts = prompt.split()
            if len(parts) > 2:
                print("Usage: /history [N]")
                continue
            if len(parts) == 2:
                try:
                    lim = int(parts[1])
                except ValueError:
                    print("Usage: /history [N]")
                    continue
                show_history(lim, session_id=session_id, conn=conn)
            else:
                show_history(session_id=session_id, conn=conn)
            continue

        # --- model turn ---------------------------------------------------

        try:
            _run_turn(conn, session_id, prompt, show_timing=True)
        except SystemExit:
            continue


def run_oneshot(
    prompt: str,
    new_session: bool = False,
    session_override: str | None = None,
) -> int:
    conn = get_db()

    if session_override is not None:
        session_id = session_override
        SESSION_FILE.write_text(session_id)
    else:
        session_id = current_session_id(new=new_session)

    _register_session(conn, session_id)
    history = load_history(conn, session_id)
    _print_banner(conn, session_id, len(history), repl=False)

    if prompt.startswith("/tool"):
        return _run_tool_turn(conn, session_id, history, prompt)
    return _run_plain_turn(conn, session_id, history, prompt, show_timing=False)


# ---------------------------------------------------------------------------
# CLI (extended)
# ---------------------------------------------------------------------------

def _print_usage() -> None:
    print("Usage:")
    print("  chat.py                              — resume current session (REPL)")
    print("  chat.py --new                        — start fresh session (REPL)")
    print("  chat.py --sessions                   — list all sessions")
    print("  chat.py --session <id-or-label>      — resume specific session (REPL)")
    print("  chat.py --label <text>               — label current session")
    print('  chat.py --oneshot [--new] "prompt"   — single-shot turn')
    print("  chat.py --history [N]               — show session history")


def main() -> int:  # noqa: C901
    args = sys.argv[1:]

    # --- Parse flags -------------------------------------------------------
    want_sessions = False
    session_target: str | None = None
    label_text: str | None = None
    new_session = False
    oneshot = False
    history_mode = False
    history_limit: int | None = None
    positional: list[str] = []

    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--sessions":
            want_sessions = True
        elif tok == "--session":
            i += 1
            if i >= len(args):
                print("Error: --session requires an argument.")
                return 1
            session_target = args[i]
        elif tok == "--label":
            i += 1
            if i >= len(args):
                print("Error: --label requires an argument.")
                return 1
            label_text = args[i]
        elif tok == "--new":
            new_session = True
        elif tok == "--oneshot":
            oneshot = True
        elif tok == "--history":
            history_mode = True
            if i + 1 < len(args) and args[i + 1].lstrip("-").isdigit():
                i += 1
                history_limit = int(args[i])
        else:
            positional.append(tok)
        i += 1

    # --- Mutual exclusivity ------------------------------------------------
    if new_session and session_target is not None:
        print("Error: --new and --session are mutually exclusive.")
        return 1
    if new_session and label_text is not None:
        print("Error: --new and --label are mutually exclusive.")
        return 1

    # --- --history ---------------------------------------------------------
    if history_mode:
        show_history(history_limit)
        return 0

    # --- --sessions --------------------------------------------------------
    if want_sessions:
        conn = get_db()
        list_sessions(conn)
        return 0

    # --- Resolve --session target ------------------------------------------
    session_override: str | None = None
    if session_target is not None:
        conn = get_db()
        try:
            session_override = resolve_session(conn, session_target)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        SESSION_FILE.write_text(session_override)

    # --- --label (quick-action: update label and exit unless --oneshot) ----
    if label_text is not None:
        conn = get_db()
        sid = session_override or current_session_id()
        _register_session(conn, sid)
        set_session_label(conn, sid, label_text)
        print(f"Labeled session {sid[:8]}...: {label_text!r}")
        if not oneshot:
            return 0
        # fall through: --oneshot also requested

    # --- --oneshot ---------------------------------------------------------
    if oneshot:
        if not positional:
            print('Usage: chat.py --oneshot [--new] "your prompt here"')
            return 1
        prompt = " ".join(positional)
        return run_oneshot(prompt, new_session=new_session, session_override=session_override)

    # --- Unexpected positional args ----------------------------------------
    if positional:
        _print_usage()
        return 1

    # --- Default: enter REPL -----------------------------------------------
    return run_repl(new_session=new_session, session_override=session_override)


if __name__ == "__main__":
    sys.exit(main())
