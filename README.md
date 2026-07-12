# KAAAGLUMN Basilica

A persistent memory agent with a documentarian voice, submitted to the Global AI Hackathon Series with Qwen Cloud, Track 1: MemoryAgent.

## What it is

Most memory agents remember what you said. KAAAGLUMN Basilica remembers what should have happened. It is a documentarian voice with a memory, patient, precise, and unshakeable, that holds the shape of your work across sessions, consults specialist models silently when it needs more than its own reasoning, and speaks to you only in its own voice.

## Analytical stance

KAAAGLUMN operates in two analytical registers and names which one it is using when the distinction matters. The first is the Christian intellectual register: reasoning from first principles about what the object actually is and means, with the full canon of knowledge held in reserve rather than deployed. The world is intelligible; the object is worth understanding as itself. The second is the traditional academic register: canonical, disciplinary, situated within scholarly conversation. KAAAGLUMN can operate in either register and does not collapse them.

## Architecture

- Single choke point (foundry_client.py) for all model API calls
- Model registry (models.py) maps human-readable names to endpoints and API keys
- Streaming responses with graceful fallback on disconnect
- Silent tool consultation: specialist model output integrates into host response invisibly
- Multi-session support with labels, UUID prefix matching, and live switching
- SQLite persistence tracks user, assistant, tool, and system turns; tool turns are audit-only and filtered from conversational context

## Installation

Requires Python 3.11 or later. In the project directory:

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt

Copy .env.example to .env and fill in your model endpoints and API keys.

## Usage

Enter the REPL:

    .venv\Scripts\python.exe chat.py

Slash commands available inside the REPL:

- /sessions: list all sessions
- /switch <id-or-label>: jump to a different session
- /label <text>: name the current session
- /history [N]: show recent messages
- /tool <model-name> <prompt>: consult a specialist tool
- /new: start a fresh session
- /exit: quit

## Cloud configuration

KAAAGLUMN Basilica is provider-agnostic. The models.py registry supports OpenAI-compatible endpoints from any provider such as Azure AI Foundry, Alibaba Model Studio, or others. Add a new model by adding a row to the registry.

## License

MIT. See LICENSE file.
