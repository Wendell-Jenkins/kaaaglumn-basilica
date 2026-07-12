#!/usr/bin/env python3
# KAAAGLUMN — wendscope-cli diagnostic tool.
# One-shot Azure AI Foundry / Azure OpenAI chat call. No startup banner by design.
"""Azure OpenAI / AI Foundry chat client for wendscope-cli (KAAAGLUMN)."""

from __future__ import annotations

import argparse
import os
import sys

from foundry_client import get_client, load_env, require_env
from models import DEFAULT_MODEL, deployment_name

ONESHOT_MAX_TOKENS = 128


def call_foundry(prompt: str, model_name: str = DEFAULT_MODEL) -> str:
    client, _mode, _url, deployment = get_client(model_name)
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=ONESHOT_MAX_TOKENS,
    )
    return (response.choices[0].message.content or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="wendscope-cli (KAAAGLUMN) — Azure / Foundry chat stub")
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Reply with exactly: wendscope-cli OK",
        help="User message to send",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate env only; do not call the API")
    args = parser.parse_args()

    load_env()

    missing = require_env("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")
    if missing:
        print(f"ERROR: Missing env: {', '.join(missing)}")
        print("Copy .env.example to .env and set your Azure OpenAI values.")
        return 1

    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    _client, mode, url, _deployment = get_client(DEFAULT_MODEL)

    print("OK: AZURE_OPENAI_ENDPOINT set")
    print("OK: AZURE_OPENAI_API_KEY set")
    print(f"OK: key length = {len(api_key.strip())} chars")
    print(f"OK: model = {DEFAULT_MODEL}")
    print(f"OK: deployment = {deployment_name(DEFAULT_MODEL)}")
    print(f"OK: api mode = {mode}")
    print(f"OK: request base = {url}")

    if args.dry_run:
        print("DRY RUN: skipping API call")
        return 0

    try:
        text = call_foundry(args.prompt)
        print("RESPONSE:")
        print(text)
        return 0
    except Exception as exc:
        print(f"API call failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
