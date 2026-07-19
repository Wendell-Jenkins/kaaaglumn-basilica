"""Foundry model registry for KAAAGLUMN."""

from __future__ import annotations

DEFAULT_MODEL = "Qwen3.7-Max"

MODELS: dict[str, dict[str, str | int]] = {
    "grok-4-3": {
        "deployment_name": "grok-4.3",
        "endpoint_env_var": "AZURE_OPENAI_ENDPOINT",
        "api_key_env_var": "AZURE_OPENAI_API_KEY",
        "max_tokens": 4096,
    },
    "Kimi-K2.6": {
        "deployment_name": "Kimi-K2.6",
        "endpoint_env_var": "AZURE_OPENAI_ENDPOINT",
        "api_key_env_var": "AZURE_OPENAI_API_KEY",
        "max_tokens": 2048,
    },
    "DeepSeek-V4-Flash": {
        "deployment_name": "DeepSeek-V4-Flash",
        "endpoint_env_var": "AZURE_OPENAI_ENDPOINT",
        "api_key_env_var": "AZURE_OPENAI_API_KEY",
        "max_tokens": 512,
    },
    "Qwen3.7-Max": {
        "deployment_name": "qwen3.7-max",
        "endpoint_env_var": "QWEN_CLOUD_ENDPOINT",
        "api_key_env_var": "QWEN_CLOUD_API_KEY",
        "max_tokens": 4096,
    },
}


def get_model(model_name: str) -> dict[str, str | int]:
    if model_name not in MODELS:
        known = ", ".join(sorted(MODELS))
        raise KeyError(f"Unknown model {model_name!r}. Registered: {known}")
    return MODELS[model_name]


def deployment_name(model_name: str) -> str:
    return str(get_model(model_name)["deployment_name"])
