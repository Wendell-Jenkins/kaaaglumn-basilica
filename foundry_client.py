"""Single choke point for Azure / Foundry OpenAI clients."""

from __future__ import annotations

import os

from models import DEFAULT_MODEL, get_model


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(encoding="utf-8-sig")
    except ImportError:
        pass


def require_env(*keys: str) -> list[str]:
    return [k for k in keys if not os.environ.get(k)]


def normalize_foundry_base_url(endpoint: str) -> str:
    """AI Foundry OpenAI-compatible base URL (…/openai/v1/)."""
    url = endpoint.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    if "services.ai.azure.com" in url and not url.endswith("/openai/v1"):
        url = f"{url}/openai/v1"
    return url + "/"


def use_foundry_v1(endpoint: str) -> bool:
    mode = os.environ.get("AZURE_OPENAI_API_MODE", "").strip().lower()
    if mode in {"foundry_v1", "foundry", "v1"}:
        return True
    return "services.ai.azure.com" in endpoint


def get_client(model_name: str = DEFAULT_MODEL):
    """Return (client, mode, base_url, deployment_name) for the named model."""
    model = get_model(model_name)
    endpoint_key = str(model["endpoint_env_var"])
    api_key_key = str(model["api_key_env_var"])
    endpoint = os.environ[endpoint_key]
    api_key = os.environ[api_key_key].strip()
    deployment = str(model["deployment_name"])

    if use_foundry_v1(endpoint):
        from openai import OpenAI

        base_url = normalize_foundry_base_url(endpoint)
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"api-key": api_key},
        )
        return client, "foundry_v1", base_url, deployment

    from openai import AzureOpenAI

    azure_endpoint = endpoint.rstrip("/") + "/"
    client = AzureOpenAI(
        azure_endpoint=azure_endpoint,
        api_key=api_key,
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
    )
    return client, "azure", azure_endpoint, deployment
