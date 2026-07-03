"""
Bring-your-own-key (BYOK) configuration for Aritiq.

Aritiq ships no API keys. To audit novel documents you supply your own model
key from any supported provider. There are two ways to do it:

1. A ``.env`` file in the project root (recommended). Copy ``.env.example`` to
   ``.env`` and fill in your provider and key:

       ARITIQ_PROVIDER=anthropic
       ANTHROPIC_API_KEY=sk-ant-...

2. Plain environment variables, e.g. ``export ANTHROPIC_API_KEY=...``.

Supported providers and the key each one reads:

    anthropic  ->  ANTHROPIC_API_KEY
    openai     ->  OPENAI_API_KEY
    gemini     ->  GEMINI_API_KEY
    groq       ->  GROQ_API_KEY

Two provider-agnostic overrides are also honored, checked first, in order:

    ARITIQ_API_KEY_VAR   name of the env var that holds your key, e.g.
                         ARITIQ_API_KEY_VAR=MY_SECRET  (then MY_SECRET=sk-...)
    ARITIQ_API_KEY       the key value itself, e.g. ARITIQ_API_KEY=sk-...

These let you keep a key under whatever variable name your environment already
uses (CI secrets, a shared vault, etc.) without renaming it. When neither is
set, the provider-specific variable above is used.

The verifier itself uses no model and needs no key; a key is only required to
extract claims from documents that are not one of the bundled examples.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; env vars still work without it.
    def load_dotenv(*_args, **_kwargs) -> bool:  # type: ignore
        return False


# provider -> the environment variable holding that provider's key.
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
}

DEFAULT_PROVIDER = "anthropic"

_loaded = False


def load(*, override: bool = False) -> None:
    """Load a ``.env`` file (if present) into the process environment.

    Idempotent: safe to call from every entry point (backend, CLI, demos).
    """
    global _loaded
    if _loaded and not override:
        return
    load_dotenv(override=override)
    _loaded = True


def provider() -> str:
    """The configured provider, defaulting to ``anthropic``."""
    return (os.environ.get("ARITIQ_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def key_var_for(prov: Optional[str] = None) -> str:
    """Name of the env var that holds the given provider's key."""
    return PROVIDER_KEYS.get((prov or provider()), "")


def api_key(prov: Optional[str] = None) -> Optional[str]:
    """The API key for the given (or configured) provider, if set."""
    custom_var_name = os.environ.get("ARITIQ_API_KEY_VAR")
    if custom_var_name:
        key = os.environ.get(custom_var_name.strip())
        if key:
            return key

    custom_key = os.environ.get("ARITIQ_API_KEY")
    if custom_key:
        return custom_key

    var = key_var_for(prov)
    return os.environ.get(var) if var else None


def has_key(prov: Optional[str] = None) -> bool:
    """True when a key is available for the given (or configured) provider."""
    return bool(api_key(prov))


def require_key(prov: Optional[str] = None) -> str:
    """Return the key or raise a clear, actionable error if it is missing."""
    prov = (prov or provider())
    if prov not in PROVIDER_KEYS:
        raise RuntimeError(
            f"Unknown provider {prov!r}. Set ARITIQ_PROVIDER to one of: "
            f"{', '.join(PROVIDER_KEYS)}."
        )
    key = api_key(prov)
    if not key:
        custom_var_name = os.environ.get("ARITIQ_API_KEY_VAR")
        if custom_var_name:
            raise RuntimeError(
                f"No API key found for provider {prov!r}. Expected to find key in "
                f"environment variable {custom_var_name!r} specified by ARITIQ_API_KEY_VAR."
            )
        var = PROVIDER_KEYS[prov]
        raise RuntimeError(
            f"No API key found for provider {prov!r}. Set ARITIQ_API_KEY or {var} "
            f"in your .env file or environment."
        )
    return key
