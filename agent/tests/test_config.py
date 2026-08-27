"""Unit tests: AI provider seam (AI Studio key vs Vertex AI ADC)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from incident_director.config import Settings, apply_ai_env, load_settings

AI_KEYS = ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY")
VERTEX_VARS = ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")


@pytest.fixture(autouse=True)
def _preserve_environ(monkeypatch):
    """apply_ai_env mutates os.environ — snapshot/restore around every test."""
    saved = {k: os.environ.get(k) for k in (*AI_KEYS, *VERTEX_VARS, "GOOGLE_APPLICATION_CREDENTIALS")}
    for k in saved:
        monkeypatch.delenv(k, raising=False)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


BASE = {
    "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_test",
}


class TestProviderSelection:
    def test_default_is_ai_studio_key(self):
        s = load_settings(env={**BASE})
        assert s.ai_provider == "gemini"
        assert not s.is_vertex
        assert s.gemini_model == "gemini-3.6-flash"

    def test_vertex_via_provider_alias(self):
        s = load_settings(env={**BASE, "PROVIDER": "vertex", "GOOGLE_CLOUD_PROJECT": "p"})
        assert s.is_vertex

    def test_vertex_model_default_is_vertex_ga(self):
        # gemini-3.6-flash is AI-Studio-only (404 on Vertex us-central1)
        s = load_settings(env={**BASE, "AI_PROVIDER": "vertex"})
        assert s.gemini_model == "gemini-2.5-flash"

    def test_explicit_model_wins_on_vertex(self):
        s = load_settings(env={**BASE, "AI_PROVIDER": "vertex", "GEMINI_MODEL": "gemini-2.5-pro"})
        assert s.gemini_model == "gemini-2.5-pro"


class TestApplyAiEnv:
    def test_vertex_sets_vertex_vars_and_strips_keys(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "stale-key")
        s = load_settings(
            env={
                **BASE,
                "AI_PROVIDER": "vertex",
                "GOOGLE_CLOUD_PROJECT": "proj-1",
                "GOOGLE_CLOUD_LOCATION": "us-central1",
                "GOOGLE_APPLICATION_CREDENTIALS": "C:/keys/sa.json",
            }
        )
        apply_ai_env(s)
        assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "1"
        assert os.environ["GOOGLE_CLOUD_PROJECT"] == "proj-1"
        assert os.environ["GOOGLE_CLOUD_LOCATION"] == "us-central1"
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "C:/keys/sa.json"
        # google-genai errors on key+vertex conflict — keys must be gone
        for k in AI_KEYS:
            assert k not in os.environ

    def test_gemini_sets_key_and_clears_vertex(self):
        s = load_settings(env={**BASE, "GEMINI_API_KEY": "k-1"})
        apply_ai_env(s)
        assert os.environ["GOOGLE_API_KEY"] == "k-1"
        for k in VERTEX_VARS:
            assert k not in os.environ


class TestValidateRuntime:
    def test_gemini_without_key_fails(self):
        s = load_settings(env={**BASE})
        problems = s.validate_runtime()
        assert any("GEMINI_API_KEY" in p for p in problems)

    def test_vertex_without_project_fails(self, tmp_path: Path):
        key = tmp_path / "sa.json"
        key.write_text("{}", encoding="utf-8")
        s = load_settings(
            env={
                **BASE,
                "AI_PROVIDER": "vertex",
                "GOOGLE_APPLICATION_CREDENTIALS": str(key),
            }
        )
        problems = s.validate_runtime()
        assert any("GOOGLE_CLOUD_PROJECT" in p for p in problems)

    def test_vertex_with_missing_key_file_fails(self):
        s = load_settings(
            env={
                **BASE,
                "AI_PROVIDER": "vertex",
                "GOOGLE_CLOUD_PROJECT": "proj-1",
                "GOOGLE_APPLICATION_CREDENTIALS": "C:/nope/does-not-exist.json",
            }
        )
        problems = s.validate_runtime()
        assert any("not a file" in p for p in problems)

    def test_vertex_full_config_passes(self, tmp_path: Path):
        key = tmp_path / "sa.json"
        key.write_text("{}", encoding="utf-8")
        s = load_settings(
            env={
                **BASE,
                "AI_PROVIDER": "vertex",
                "GOOGLE_CLOUD_PROJECT": "proj-1",
                "GOOGLE_APPLICATION_CREDENTIALS": str(key),
            }
        )
        assert s.validate_runtime() == []

    def test_unknown_provider_fails(self):
        s = load_settings(env={**BASE, "AI_PROVIDER": "openai", "GEMINI_API_KEY": "k"})
        assert any("AI_PROVIDER" in p for p in s.validate_runtime())


def test_settings_frozen():
    s = Settings()
    with pytest.raises(Exception):
        s.ai_provider = "vertex"  # type: ignore[misc]
