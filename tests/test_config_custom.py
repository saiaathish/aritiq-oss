import os
import pytest
from aritiq import config

def test_custom_api_key_resolution(monkeypatch):
    monkeypatch.delenv("ARITIQ_API_KEY", raising=False)
    monkeypatch.delenv("ARITIQ_API_KEY_VAR", raising=False)
    for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    # 1. Fallback to standard provider key
    monkeypatch.setenv("ANTHROPIC_API_KEY", "standard-anthropic-key")
    assert config.api_key("anthropic") == "standard-anthropic-key"

    # 2. ARITIQ_API_KEY override
    monkeypatch.setenv("ARITIQ_API_KEY", "custom-generic-key")
    assert config.api_key("anthropic") == "custom-generic-key"

    # 3. ARITIQ_API_KEY_VAR override
    monkeypatch.setenv("ARITIQ_API_KEY_VAR", "MY_SUPER_KEY")
    monkeypatch.setenv("MY_SUPER_KEY", "super-custom-key")
    assert config.api_key("anthropic") == "super-custom-key"

def test_require_key_error_custom_var(monkeypatch):
    monkeypatch.delenv("ARITIQ_API_KEY", raising=False)
    monkeypatch.delenv("ARITIQ_API_KEY_VAR", raising=False)
    for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("ARITIQ_API_KEY_VAR", "MISSING_KEY_VAR")
    with pytest.raises(RuntimeError) as exc_info:
        config.require_key("anthropic")
    assert "Expected to find key in environment variable 'MISSING_KEY_VAR' specified by ARITIQ_API_KEY_VAR" in str(exc_info.value)
