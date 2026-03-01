"""
LLM Client Abstraction — provider-agnostic interface for all LLM calls.

Supported providers:
- openai: Standard OpenAI API (default)
- openai_compatible: Any OpenAI-compatible API (DeepSeek, Qwen, Ollama, etc.)
  Set LLM_{TASK}_BASE_URL + LLM_{TASK}_API_KEY in .env to configure.
- anthropic: Anthropic Claude API

Task types → provider+model via config.LLM_MODELS.
Env vars override config (higher priority):
  LLM_{TASK_TYPE}_PROVIDER   e.g. LLM_SYNTHESIS_PROVIDER=anthropic
  LLM_{TASK_TYPE}_MODEL      e.g. LLM_SYNTHESIS_MODEL=claude-opus-4-6
  LLM_{TASK_TYPE}_API_KEY    e.g. LLM_SYNTHESIS_API_KEY=sk-ant-...
  LLM_{TASK_TYPE}_BASE_URL   e.g. LLM_CLASSIFICATION_BASE_URL=http://localhost:11434/v1

Usage:
    from llm_client import llm_complete, is_configured

    text = llm_complete("synthesis", messages, max_tokens=1000, temperature=0.3)
    json_str = llm_complete("classification", messages, max_tokens=200, temperature=0, json_mode=True)

Adding a new provider:
    1. Create a class with a .complete(messages, *, max_tokens, temperature, json_mode) -> str method
    2. Add it to _PROVIDER_ADAPTERS dict below
    3. Set LLM_{TASK_TYPE}_PROVIDER=your_provider_name in .env
"""

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

import config


# ------------------------------------------------------------------
# Provider Adapters
# ------------------------------------------------------------------

class OpenAICompatibleAdapter:
    """
    Adapter for OpenAI and any OpenAI-compatible API.
    Covers: OpenAI, DeepSeek, Qwen, Ollama, LM Studio, etc.
    Set base_url for non-OpenAI endpoints.
    """

    def __init__(self, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        from openai import OpenAI
        self.model = model
        client_kwargs: Dict[str, Any] = {"api_key": api_key or os.getenv("OPENAI_API_KEY")}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = OpenAI(**client_kwargs)

    def complete(
        self,
        messages: List[Dict],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()


class AnthropicAdapter:
    """
    Adapter for Anthropic Claude API.
    Handles system message separation and json_mode via prompt injection.
    """

    def __init__(self, model: str, api_key: Optional[str] = None):
        from anthropic import Anthropic
        self.model = model
        self._client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    def complete(
        self,
        messages: List[Dict],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        # Anthropic takes system separately; extract from messages
        system = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        if json_mode:
            json_instruction = "Output ONLY valid JSON. No markdown, no explanation."
            system = f"{system}\n\n{json_instruction}".strip() if system else json_instruction

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        return response.content[0].text.strip()


# ------------------------------------------------------------------
# Client Factory
# ------------------------------------------------------------------

_PROVIDER_ADAPTERS: Dict[str, type] = {
    "openai": OpenAICompatibleAdapter,
    "openai_compatible": OpenAICompatibleAdapter,  # alias for clarity
    "anthropic": AnthropicAdapter,
}

_client_cache: Dict[str, Any] = {}


def _resolve_config(task_type: str) -> Dict[str, Any]:
    """Resolve provider/model/key/url for a task type. Env vars take priority."""
    task_upper = task_type.upper()
    task_cfg = getattr(config, "LLM_MODELS", {}).get(task_type, {})
    return {
        "provider": os.getenv(f"LLM_{task_upper}_PROVIDER") or task_cfg.get("provider", "openai"),
        "model":    os.getenv(f"LLM_{task_upper}_MODEL")    or task_cfg.get("model", "gpt-3.5-turbo"),
        "api_key":  os.getenv(f"LLM_{task_upper}_API_KEY")  or task_cfg.get("api_key"),
        "base_url": os.getenv(f"LLM_{task_upper}_BASE_URL") or task_cfg.get("base_url"),
    }


def get_client(task_type: str):
    """
    Get the configured LLM adapter for a task type. Clients are cached.

    Resolution order (highest priority first):
      1. Env vars: LLM_{TASK_TYPE}_PROVIDER / _MODEL / _API_KEY / _BASE_URL
      2. config.LLM_MODELS[task_type]
      3. Defaults: provider=openai, model=gpt-3.5-turbo
    """
    if task_type in _client_cache:
        return _client_cache[task_type]

    cfg = _resolve_config(task_type)
    provider = cfg["provider"]

    adapter_cls = _PROVIDER_ADAPTERS.get(provider)
    if adapter_cls is None:
        raise ValueError(
            f"Unknown LLM provider '{provider}' for task '{task_type}'. "
            f"Supported: {sorted(_PROVIDER_ADAPTERS)}"
        )

    if provider == "anthropic":
        adapter = adapter_cls(model=cfg["model"], api_key=cfg["api_key"])
    else:
        adapter = adapter_cls(model=cfg["model"], api_key=cfg["api_key"], base_url=cfg["base_url"])

    _client_cache[task_type] = adapter
    return adapter


def is_configured(task_type: str) -> bool:
    """
    Return True if the required API key is available for this task's provider.
    Used for graceful degradation when no key is set.
    """
    cfg = _resolve_config(task_type)
    provider = cfg["provider"]
    explicit_key = cfg["api_key"]

    if explicit_key:
        return True
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY"))


def llm_complete(
    task_type: str,
    messages: List[Dict],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool = False,
) -> str:
    """
    Unified LLM completion call, routed by task type.

    Args:
        task_type:   'classification', 'extraction', or 'synthesis'
        messages:    [{role, content}, ...] in OpenAI message format
        max_tokens:  Max tokens for completion
        temperature: Sampling temperature (0 = deterministic)
        json_mode:   Request JSON-only output; provider-specific handling

    Returns:
        Response content string
    """
    return get_client(task_type).complete(
        messages, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode
    )


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("LLM Client Abstraction — Configuration Test")
    print("=" * 60)

    for task in ["classification", "extraction", "synthesis"]:
        cfg = _resolve_config(task)
        available = is_configured(task)
        print(f"\n  [{task}]")
        print(f"    provider : {cfg['provider']}")
        print(f"    model    : {cfg['model']}")
        print(f"    base_url : {cfg['base_url'] or '(default)'}")
        print(f"    api_key  : {'configured' if (cfg['api_key'] or is_configured(task)) else 'MISSING'}")
        print(f"    ready    : {'✓' if available else '✗ no API key'}")

    print("\n" + "=" * 60)
    print("Supported providers:", sorted(_PROVIDER_ADAPTERS))
    print("Env var format: LLM_{TASK_TYPE}_{PROVIDER|MODEL|API_KEY|BASE_URL}")
    print("Example: LLM_SYNTHESIS_PROVIDER=anthropic LLM_SYNTHESIS_MODEL=claude-opus-4-6")
    print("=" * 60)
