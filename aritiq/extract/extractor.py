"""
The extraction engine: (source, summary) -> structured Claims.

This is the only module in Aritiq that talks to an LLM, and it is deliberately
thin.  All the *judgment* lives in the prompt; all the *safety* lives in
schema.parse_claims (hard Pydantic validation).  This file just moves bytes:
build the prompt, call a model, hand the text to the validator.

Firewall: this module imports the Day 1 schema (to produce Claim objects) and
the prompt/validator.  It does NOT import aritiq.core.verify or score, and
nothing in the verification path imports this.  `grep -r verify` here returns
nothing.

Testability: every model call goes through a `CompletionFn` — a plain
`(system_prompt, user_prompt) -> str` callable.  Tests inject a fake one, so the
whole pipeline runs with no network and no API key.  The real Anthropic/OpenAI
clients are just default implementations of that callable, imported lazily so
the package works even when neither SDK is installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..core.schema import Claim
from .prompt import build_system_prompt, build_user_prompt
from .schema import ExtractionIssue, parse_claims

# (system_prompt, user_prompt) -> raw model text
CompletionFn = Callable[[str, str], str]

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
DEFAULT_GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MAX_TOKENS = 8192


@dataclass
class ExtractionOutput:
    """Everything the extraction stage produced, for the pipeline and for audit."""
    claims: List[Claim]
    issues: List[ExtractionIssue] = field(default_factory=list)
    raw_response: str = ""
    provider: str = ""
    model: str = ""

    @property
    def n_claims(self) -> int:
        return len(self.claims)

    @property
    def n_issues(self) -> int:
        return len(self.issues)


# ---------------------------------------------------------------------------
# Default model clients (lazy imports; only needed when no complete_fn is given)
# ---------------------------------------------------------------------------

def _anthropic_client(model: str, max_tokens: int) -> CompletionFn:
    """
    Build a CompletionFn backed by the Anthropic Messages API.

    Uses an assistant-turn prefill of "[" to force the model to begin a JSON
    array immediately — Anthropic's reliable equivalent of a JSON mode.  The
    leading "[" is stitched back on so the validator sees a complete array.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on env
        raise RuntimeError(
            "The 'anthropic' package is not installed. Install it (pip install "
            "anthropic) or pass your own complete_fn to extract_claims()."
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it, or pass complete_fn to "
            "extract_claims() to run with a different backend."
        )

    client = anthropic.Anthropic(api_key=api_key)

    def complete(system_prompt: str, user_prompt: str) -> str:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": "["},  # prefill -> JSON array
            ],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
        return "[" + text  # restore the prefilled bracket

    return complete


def _openai_client(model: str, max_tokens: int) -> CompletionFn:
    """Build a CompletionFn backed by the OpenAI Chat Completions API."""
    try:
        import openai
    except ImportError as exc:  # pragma: no cover - depends on env
        raise RuntimeError(
            "The 'openai' package is not installed. Install it (pip install "
            "openai) or pass your own complete_fn to extract_claims()."
        ) from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it, or pass complete_fn to "
            "extract_claims() to run with a different backend."
        )

    client = openai.OpenAI(api_key=api_key)

    def complete(system_prompt: str, user_prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    return complete


def _groq_client(model: str, max_tokens: int) -> CompletionFn:
    """Build a CompletionFn backed by Groq (OpenAI-compatible endpoint)."""
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "The 'openai' package is not installed. "
            "Install it (pip install openai) or pass complete_fn."
        ) from exc

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Export it, or pass complete_fn to "
            "extract_claims() to run with a different backend."
        )

    client = openai.OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)

    def complete(system_prompt: str, user_prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content or ""

    return complete


def _gemini_client(model: str, max_tokens: int) -> CompletionFn:
    """Build a CompletionFn backed by the Google Gemini API (google-genai SDK)."""
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "The 'google-genai' package is not installed. "
            "Install it (pip install google-genai) or pass complete_fn."
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Export it, or pass complete_fn to "
            "extract_claims() to run with a different backend."
        )

    client = genai.Client(api_key=api_key)

    def complete(system_prompt: str, user_prompt: str) -> str:
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            ),
        )
        return response.text or ""

    return complete


def _default_complete_fn(provider: str, model: Optional[str], max_tokens: int) -> tuple[CompletionFn, str, str]:
    """Resolve provider/model and return (complete_fn, provider, model)."""
    provider = (provider or os.environ.get("ARITIQ_PROVIDER") or "gemini").lower()
    model = model or os.environ.get("ARITIQ_EXTRACT_MODEL")

    if provider == "anthropic":
        model = model or DEFAULT_ANTHROPIC_MODEL
        return _anthropic_client(model, max_tokens), provider, model
    if provider == "openai":
        model = model or DEFAULT_OPENAI_MODEL
        return _openai_client(model, max_tokens), provider, model
    if provider == "gemini":
        model = model or DEFAULT_GEMINI_MODEL
        return _gemini_client(model, max_tokens), provider, model
    if provider == "groq":
        model = model or DEFAULT_GROQ_MODEL
        return _groq_client(model, max_tokens), provider, model
    raise ValueError(f"Unknown provider {provider!r}; use 'anthropic', 'openai', 'gemini', 'groq', or pass complete_fn.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_claims(
    source: str,
    summary: str,
    *,
    complete_fn: Optional[CompletionFn] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    include_example: bool = True,
) -> ExtractionOutput:
    """
    Extract structured Claims from a source document and an AI-generated summary.

    Parameters
    ----------
    source, summary : str
        The source document (ground truth) and the summary being audited.
    complete_fn : optional
        A `(system_prompt, user_prompt) -> str` callable.  If given, it is used
        directly and no SDK/API key is required (this is how tests and offline
        runs work).  If omitted, a default Anthropic/OpenAI client is built from
        environment variables.
    provider, model :
        Select the default backend ('anthropic' or 'openai') and model string.
        Ignored when complete_fn is provided.

    Returns
    -------
    ExtractionOutput with validated Claims and any structural issues.  This
    function does not raise on a bad model response: malformed claims become
    ExtractionIssues; only well-formed claims appear in `.claims`.
    """
    system_prompt = build_system_prompt(include_example=include_example)
    user_prompt = build_user_prompt(source, summary)

    used_provider, used_model = "injected", "injected"
    if complete_fn is None:
        complete_fn, used_provider, used_model = _default_complete_fn(provider, model, max_tokens)

    raw = complete_fn(system_prompt, user_prompt)
    claims, issues = parse_claims(raw)

    return ExtractionOutput(
        claims=claims,
        issues=issues,
        raw_response=raw,
        provider=used_provider,
        model=used_model,
    )
