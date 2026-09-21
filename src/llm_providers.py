"""Free-tier LLM provider chain with automatic failover.

Tries providers in configured order; on failure (missing key, HTTP error,
quota/429, bad output) the SAME prompt + user context is forwarded to the
next provider so the answer keeps full context regardless of which model
ultimately answers.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

from config import Config


class ProviderError(Exception):
    """Raised when a provider fails; the router moves to the next one."""


def _post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int = 60,
) -> Dict[str, Any]:
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise ProviderError(f"network error: {exc}") from exc
    if resp.status_code == 429:
        raise ProviderError("rate limited (429)")
    if resp.status_code >= 400:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ProviderError("invalid JSON response") from exc


# ---------------------------------------------------------------- providers

def call_gemini(prompt: str) -> str:
    if not Config.GEMINI_API_KEY:
        raise ProviderError("GEMINI_API_KEY not set")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{Config.GEMINI_MODEL_NAME}:generateContent"
    )
    data = _post_json(
        url,
        {"x-goog-api-key": Config.GEMINI_API_KEY},
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        },
    )
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"unexpected response shape: {exc}") from exc


def _openai_compatible(base_url: str, api_key: str, model: str, prompt: str) -> str:
    data = _post_json(
        f"{base_url}/chat/completions",
        {"Authorization": f"Bearer {api_key}"},
        {
            "model": model,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"unexpected response shape: {exc}") from exc


def call_groq(prompt: str) -> str:
    if not Config.GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY not set")
    return _openai_compatible(
        "https://api.groq.com/openai/v1",
        Config.GROQ_API_KEY,
        Config.GROQ_MODEL_NAME,
        prompt,
    )


def call_cerebras(prompt: str) -> str:
    if not Config.CEREBRAS_API_KEY:
        raise ProviderError("CEREBRAS_API_KEY not set")
    return _openai_compatible(
        "https://api.cerebras.ai/v1",
        Config.CEREBRAS_API_KEY,
        Config.CEREBRAS_MODEL_NAME,
        prompt,
    )


def call_mistral(prompt: str) -> str:
    if not Config.MISTRAL_API_KEY:
        raise ProviderError("MISTRAL_API_KEY not set")
    return _openai_compatible(
        "https://api.mistral.ai/v1",
        Config.MISTRAL_API_KEY,
        Config.MISTRAL_MODEL_NAME,
        prompt,
    )


def call_cloudflare(prompt: str) -> str:
    if not Config.CLOUDFLARE_API_KEY or not Config.CLOUDFLARE_ACCOUNT_ID:
        raise ProviderError("CLOUDFLARE_API_KEY/CLOUDFLARE_ACCOUNT_ID not set")
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{Config.CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/{Config.CLOUDFLARE_MODEL_NAME}"
    )
    data = _post_json(
        url,
        {"Authorization": f"Bearer {Config.CLOUDFLARE_API_KEY}"},
        {"messages": [{"role": "user", "content": prompt}]},
    )
    try:
        return data["result"]["response"]
    except (KeyError, TypeError) as exc:
        raise ProviderError(f"unexpected response shape: {exc}") from exc


def call_ollama(prompt: str) -> str:
    if not Config.OLLAMA_BASE_URL:
        raise ProviderError("OLLAMA_BASE_URL not set")
    try:
        resp = requests.post(
            f"{Config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": Config.OLLAMA_MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    # Default num_predict (~128) truncates JSON mid-string,
                    # and default num_ctx (2048) truncates the INPUT prompt
                    # (market data + headlines exceed it) -> raise both.
                    "num_predict": int(os.getenv('OLLAMA_NUM_PREDICT', '2048')),
                    "num_ctx": int(os.getenv('OLLAMA_NUM_CTX', '8192')),
                },
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json()["response"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise ProviderError(f"ollama error: {exc}") from exc


# ------------------------------------------------------------------ router

# Default priority: quality first, then fastest free tiers, local last.
PROVIDERS = {
    "gemini": call_gemini,
    "groq": call_groq,
    "cerebras": call_cerebras,
    "mistral": call_mistral,
    "cloudflare": call_cloudflare,
    "ollama": call_ollama,
}


class LLMRouter:
    """Forward the same prompt + user context down the free-tier chain."""

    def __init__(self, order: Optional[List[str]] = None):
        raw = order or [p.strip() for p in Config.LLM_PROVIDER_ORDER.split(",") if p.strip()]
        self.chain = [(name, PROVIDERS[name]) for name in raw if name in PROVIDERS]
        self.last_used: Optional[str] = None

    def generate(self, prompt: str, max_retries_per_provider: int = 1) -> str:
        if not self.chain:
            raise ProviderError("no LLM provider configured")
        errors: List[str] = []
        for name, fn in self.chain:
            for attempt in range(max_retries_per_provider + 1):
                try:
                    text = fn(prompt)
                    if text and text.strip():
                        self.last_used = name
                        return text
                    raise ProviderError("empty response")
                except ProviderError as exc:
                    errors.append(f"{name}: {exc}")
                    if attempt < max_retries_per_provider:
                        time.sleep(2 ** attempt)
        raise ProviderError("all providers failed :: " + " | ".join(errors))
