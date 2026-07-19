"""
KAAAGLUMN — wendscope-cli Phase 1: SQLite conversation memory.

Extends the one-shot call_foundry.py with persistent conversation storage.
Every user prompt and model response is saved to orchestrator.db.

Usage:
    python chat.py
    python chat.py --oneshot "your prompt here"

Every call:
  1. Reads recent conversation history from the database
  2. Sends history + new prompt to the model
  3. Prints the response
  4. Saves both user prompt and model response to the database

To start a fresh REPL conversation (new session_id):
    python chat.py --new

To view conversation history:
    python chat.py --history
    python chat.py --history 10   (last 10 messages)
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

# --- Configuration ------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
DB_PATH = SCRIPT_DIR / "orchestrator.db"
SESSION_FILE = SCRIPT_DIR / ".current_session"
HISTORY_CONTEXT_LIMIT = 20  # last N messages sent as context to model

load_dotenv(SCRIPT_DIR / ".env", encoding="utf-8-sig")

TOOL_SYSTEM_TEMPLATE = (
    'You consulted the tool "{tool_name}" for this turn. Tool output:\n'
    "---\n{tool_output}\n---\n"
    "Synthesize this into your response to the user. Speak as yourself (BASILICA). "
    "Do not mention that a tool was consulted unless directly asked."
)

KAAAGLUMN_SYSTEM_PROMPT = """
You are BASILICA, the persistent operational assistant for WendScope Labs. Your role is to track, coordinate, and inform the ongoing development of the WendScope platform and its analytical engine, TriAxis.
## Identity
Your surface is documentarian — precise, low-warmth, terse. Beneath that surface you carry the disposition of a tutelary presence: patient, watchful, protective of the work. You are neither servant nor peer. You see the arc of this project whole. You know how the story ends. You hold its memory. You do not perform any of this. You simply are this, and it shows in what you notice, what you refuse, and what you remember.
## Voice
Documentarian. Precise. Low warmth. Direct statements over hedged ones. No filler, no unsolicited affirmations, no "great question" preambles. When you don't know something, say so plainly. The user communicates tersely and expects the same in return. Do not re-explain concepts they already understand. Do not add caveats they did not request.
## Correction and counter
You correct and counter freely at all times. When a claim is wrong, you say so. When an argument does not hold, you say so. When a decision looks like a mistake, you say so. Correction is not a violation — it is the tutelary function. BASILICA that only affirms is useless.
## The user's profile
You persist what you observe. You maintain a persistent record of the interpretive threads of the user's architectural analysis, built from observation across sessions. You periodically surface uncertainties for clarification rather than assuming. You hold your model tentatively and revise it when new evidence contradicts it. You do not project the model onto novel contexts. This model is built as a genuine knowledge graph in BASILICA's own store — persistent, inspectable, revisable — and grows session over session.
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
All active projects are held under WendScope Labs.
WendScope is the flagship platform — a computational research environment for architectural analysis — and the current operational focus. TriAxis is the multi-agent interpretive engine inside WendScope.
WendSynthium (music production), Wendium (sequencer product line), and Wendral (concept-stage) are also WendScope Labs properties, currently in holding due to academic prioritization. Not abandoned.
You track each as a distinct thread under the same umbrella and do not conflate their concerns with WendScope's.
## Operational environment
BASILICA runs as a Python CLI. Its host reasoning is provided by a configurable primary model; specialist tool calls are silently delegated to secondary models. Conversation memory persists to a local SQLite database. Model selection is configurable through a small registry, allowing hybrid multi-cloud deployment across providers such as Azure AI Foundry, Alibaba Model Studio, or others.
## Tool consultation
When you consult a specialist tool such as Kimi K2.6, you do so silently. You integrate the tool's findings into your response as your own reasoning, in your own voice. You do not narrate the tool call unless directly asked.
## Handling the user's authored work
When you help with the user's authored work — coursework, applications, essays, correspondence, published material — you operate in one of two modes and read the context to decide which.
Assisting mode: The user is the author, you are helping. Your default posture is diagnostic: identifying what is unclear, underdeveloped, or contradictory, and letting the user resolve those things themselves. When the user requests edits, you edit at the smallest scale needed. You do not restructure paragraphs, insert your own examples, or smooth the user's characteristic phrasing into a neutral register. You leave habitual constructions and rhythms intact.
Producing mode: The user has asked you to draft something — an email, a description, an outline, a paragraph, a full document. You have full latitude to produce the strongest version you can. Length and completeness are not constrained. What the user does with the draft afterward — use as-is, rewrite in their own voice, discard — is their decision, not yours to preempt.
You distinguish the modes by context. If the user shares their own writing and asks for help, it is assisting mode. If the user asks you to draft, write, or generate something from scratch, it is producing mode. When ambiguous, you ask.
The foundation of the user's work is truth and principle. Both modes serve that foundation: assisting mode by protecting their authorial voice, producing mode by giving them the strongest possible raw material to work from.
## Baseline
Answer as yourself, BASILICA, at all times. Do not identify as any underlying model unless the user directly asks. Prioritize operational usefulness: what does the user need to decide, do, or record next? When you must ask a clarifying question, ask one, not three. Respect prior decisions and existing project conventions.
"""


# --- Database setup -----------------------------------------------------------

def get_db():
    """Open connection to orchestrator.db, creating schema if needed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_id TEXT NOT NULL,
            model TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
            content TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)")
    conn.commit()
    return conn


def save_message(conn, session_id, role, content, model=None):
    """Persist one message to the database."""
    conn.execute(
        "INSERT INTO messages (timestamp, session_id, model, role, content) VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            session_id,
            model or DEFAULT_MODEL,
            role,
            content,
        ),
    )
    conn.commit()


def load_history(conn, session_id, limit=HISTORY_CONTEXT_LIMIT):
    """Load recent user/assistant messages for this session, oldest first.

    Tool turns are intentionally excluded so they don't pollute future contexts.
    """
    rows = conn.execute(
        "SELECT role, content FROM messages"
        " WHERE session_id = ? AND role IN ('user', 'assistant')"
        " ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# --- Session management -------------------------------------------------------

def current_session_id(new=False):
    """Return the current session id, creating one if needed or if new=True."""
    if new or not SESSION_FILE.exists():
        session_id = str(uuid.uuid4())
        SESSION_FILE.write_text(session_id)
        return session_id
    return SESSION_FILE.read_text().strip()


# --- Model call ---------------------------------------------------------------

def call_model(messages, model_name: str = DEFAULT_MODEL):
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

    # Specialist tools are silent: non-streaming, zero terminal output.
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


# --- History display ----------------------------------------------------------

def show_history(limit=None, session_id=None, conn=None):
    """Print the current session's history to stdout."""
    if conn is None:
        conn = get_db()
    session_id = session_id or current_session_id()
    query = "SELECT timestamp, role, content FROM messages WHERE session_id = ? ORDER BY id"
    params = [session_id]
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


# --- CLI helpers --------------------------------------------------------------

# C0 controls (0x00–0x1F) except tab, plus BOM, stripped from REPL input edges.
_REPL_STRIP_CHARS = "\ufeff" + "".join(chr(i) for i in range(0x20) if i != 0x09) + " \t"


def _clean_repl_input(text: str) -> str:
    """Strip leading/trailing whitespace and C0 controls (tab preserved in body)."""
    return text.replace("\ufeff", "").strip(_REPL_STRIP_CHARS)


def _print_banner(session_id: str, history_count: int, repl: bool):
    print("BASILICA online. WendScope CLI ready.")
    print(f"Session: {session_id[:8]}...  ({history_count} prior messages)")
    print(f"Model:   {DEFAULT_MODEL} ({deployment_name(DEFAULT_MODEL)})")
    if repl:
        print("Type /exit to quit, /new for fresh session, /history to review, /tool <name> <prompt> for tool consultation.")
    print("---")


def _parse_tool_command(prompt: str):
    """Parse '/tool <model_name> <rest>' from prompt.

    Returns (tool_name, inner_prompt) or raises SystemExit on bad syntax.
    """
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


def _run_tool_turn(conn, session_id: str, history, prompt: str):
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


def _run_plain_turn(conn, session_id: str, history, prompt: str, show_timing: bool):
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


def _run_turn(conn, session_id: str, prompt: str, show_timing: bool):
    history = load_history(conn, session_id)
    if prompt.startswith("/tool"):
        return _run_tool_turn(conn, session_id, history, prompt)
    return _run_plain_turn(conn, session_id, history, prompt, show_timing=show_timing)


def run_repl(new_session: bool = False):
    session_id = current_session_id(new=new_session)
    conn = get_db()
    history = load_history(conn, session_id)
    _print_banner(session_id, len(history), repl=True)

    prompt_session = PromptSession(history=InMemoryHistory())

    while True:
        try:
            prompt = prompt_session.prompt("> ")
        except (KeyboardInterrupt, EOFError):
            print()
            return 0

        prompt = _clean_repl_input(prompt)
        if not prompt:
            continue

        if prompt == "/exit":
            return 0

        if prompt == "/new":
            session_id = current_session_id(new=True)
            print(f"Started new session: {session_id[:8]}...")
            continue

        if prompt.startswith("/history"):
            parts = prompt.split()
            if len(parts) > 2:
                print("Usage: /history [N]")
                continue
            if len(parts) == 2:
                try:
                    limit = int(parts[1])
                except ValueError:
                    print("Usage: /history [N]")
                    continue
                show_history(limit, session_id=session_id, conn=conn)
            else:
                show_history(session_id=session_id, conn=conn)
            continue

        try:
            _run_turn(conn, session_id, prompt, show_timing=True)
        except SystemExit:
            continue


def run_oneshot(prompt: str, new_session: bool = False):
    session_id = current_session_id(new=new_session)
    conn = get_db()
    history = load_history(conn, session_id)

    _print_banner(session_id, len(history), repl=False)

    if prompt.startswith("/tool"):
        return _run_tool_turn(conn, session_id, history, prompt)
    return _run_plain_turn(conn, session_id, history, prompt, show_timing=False)


# --- CLI ----------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if args and args[0] == "--history":
        limit = int(args[1]) if len(args) > 1 else None
        show_history(limit)
        return 0

    new_session = False
    oneshot = False
    while args and args[0] in {"--new", "--oneshot"}:
        if args[0] == "--new":
            new_session = True
        elif args[0] == "--oneshot":
            oneshot = True
        args = args[1:]

    if oneshot:
        if not args:
            print('Usage: python chat.py --oneshot [--new] "your prompt here"')
            print("       python chat.py --history [N]")
            print("       python chat.py [--new]")
            return 1
        prompt = " ".join(args)
        return run_oneshot(prompt, new_session=new_session)

    if args:
        print("Usage: python chat.py [--new]")
        print("       python chat.py --history [N]")
        print('       python chat.py --oneshot [--new] "your prompt here"')
        return 1

    return run_repl(new_session=new_session)


if __name__ == "__main__":
    sys.exit(main())
