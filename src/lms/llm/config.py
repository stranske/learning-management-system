"""Per-mode model routing and budget configuration for the LLM client wrapper.

Per project-plan ``LLM client wrapper interface (v1)`` and Segment 10, mode
routing is config-driven (env vars) so a model decision is a one-line change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from lms.llm.models import LLM_MODES

DEFAULT_MODE_MODELS: Mapping[str, str] = {
    "study-coach": "claude-haiku-4-5",
    "practice": "claude-haiku-4-5",
    "transfer": "claude-sonnet-4-6",
    "authoring-assist": "claude-sonnet-4-6",
}


@dataclass
class LLMConfig:
    """Resolved per-mode routing and budget settings for the wrapper."""

    mode_models: Mapping[str, str]
    global_daily_cap_micro_usd: int = 200_000  # 0.20 USD/day default kill-switch
    per_mode_daily_cap_micro_usd: Mapping[str, int] = field(default_factory=dict)
    default_provider: str = "fake"
    default_timeout_seconds: float = 30.0

    def model_for(self, mode: str) -> str:
        if mode not in LLM_MODES:
            raise ValueError(f"unknown mode '{mode}'; valid modes: {LLM_MODES}")
        if mode in self.mode_models:
            return self.mode_models[mode]
        raise KeyError(f"no model configured for mode '{mode}'")

    def provider_and_model_for(self, mode: str) -> tuple[str | None, str]:
        """Return ``(provider_name_or_None, model_name)`` for the given mode.

        When the model string uses ``provider:model`` notation (e.g.
        ``anthropic:claude-sonnet-4-5``), the provider prefix is split out and
        returned as the first element. A bare model string (e.g.
        ``claude-haiku-4-5``) returns ``None`` as the provider so the caller
        falls back to ``config.default_provider``.
        """
        raw = self.model_for(mode)
        if ":" in raw:
            provider, _, model = raw.partition(":")
            return provider, model
        return None, raw


def _env_var_for(mode: str) -> str:
    return f"LLM_MODEL_{mode.upper().replace('-', '_')}"


def load_llm_config_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    defaults: Mapping[str, str] = DEFAULT_MODE_MODELS,
) -> LLMConfig:
    """Build an :class:`LLMConfig` from environment variables.

    Resolves per-mode model overrides via ``LLM_MODEL_STUDY_COACH`` and friends,
    falling back to ``defaults`` per Segment 10. Substantive per-mode model
    choices are deferred until empirical evaluation data exists; the defaults
    are intentionally sensible-but-revisable.
    """
    env = dict(environ) if environ is not None else dict(os.environ)
    mode_models = {mode: env.get(_env_var_for(mode), defaults[mode]) for mode in LLM_MODES}
    cap_str = env.get("LLM_DAILY_CAP_MICRO_USD")
    cap = int(cap_str) if cap_str else 200_000
    provider = env.get("LLM_DEFAULT_PROVIDER", "fake")
    return LLMConfig(
        mode_models=mode_models,
        global_daily_cap_micro_usd=cap,
        default_provider=provider,
    )
