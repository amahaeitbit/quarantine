"""One chat() wrapper for every agent: tools and JSON output, model pinned by env."""
import json

import anthropic

from quarantine import config

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if config.LLM_PROVIDER != "anthropic":
            raise RuntimeError(f"LLM_PROVIDER={config.LLM_PROVIDER!r} is not supported; use 'anthropic'.")
        if not config.LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY is not set in .env.")
        _client = anthropic.Anthropic(api_key=config.LLM_API_KEY, timeout=30.0, max_retries=2)
    return _client


def chat(messages: list, system: str | None = None, tools: list | None = None,
         json_schema: dict | None = None, max_tokens: int = 4096):
    """One model call. Returns the SDK Message (read blocks by type, not position)."""
    kwargs = {"model": config.LLM_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if config.LLM_WORKSPACE_ID:  # keys that are not scoped to a workspace must name one
        kwargs["workspace_id"] = config.LLM_WORKSPACE_ID
    output_config = {}
    if config.LLM_EFFORT:
        output_config["effort"] = config.LLM_EFFORT
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    if output_config:
        kwargs["output_config"] = output_config
    # Current Claude models reject temperature=0 and the 1.x SDK dropped the keyword,
    # so it is only sent (through extra_body) when configured for a model that takes it.
    if config.LLM_TEMPERATURE:
        kwargs["extra_body"] = {"temperature": float(config.LLM_TEMPERATURE)}
    response = _get_client().messages.create(**kwargs)
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined this request (stop_reason=refusal).")
    return response


def text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def chat_json(prompt: str, schema: dict, system: str | None = None) -> dict:
    """One call constrained to a JSON schema; returns the parsed object."""
    return json.loads(text_of(chat([{"role": "user", "content": prompt}], system=system, json_schema=schema)))
