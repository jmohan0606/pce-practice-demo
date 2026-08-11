"""Per-role LLM configuration + auto-fallback.

Four PCE agent roles — RULE_EXTRACTOR, RULE_CONFLICT_AUDITOR, INSIGHTS_MINER and
INSIGHTS_REPORTER — may each need a different model in the client environment.
Azure/cdao route by DEPLOYMENT NAME, the model id is passed in the request, and
some models need their own api_version; the three can all differ. Each role
therefore gets an optional (mode, model, deployment, api_version) tuple in .env
(<ROLE>_MODE / <ROLE>_MODEL / <ROLE>_DEPLOYMENT / <ROLE>_API_VERSION), plus a
<ROLE>_TEMPERATURE.

This module is the ONE place role → effective-config resolution lives:

    resolve_role_config("rule_extractor" | ... ) -> RoleLLMConfig

Resolution rules (identical for every role):
- every field empty  → the active LLM_MODE and that mode's own default model.
- any field set      → the role runs on its own values, falling back PER FIELD
  to the active mode's value for anything left empty.
- deployment vs model: Azure/cdao route by deployment; if only one of the two
  is set it is used for both, best-effort, and a log line says which.

Auto-fallback lives here too: build_role_llm() wraps a configured role's client
so a construction or first-call failure (bad deployment, missing api_version,
404/400) logs a WARNING naming the role and retries ONCE with the active
default agent LLM. The served path is recorded per role: role_config /
fallback_agent_llm / unavailable. Total failure surfaces the role-appropriate
honest state at the caller — never a fabricated answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import get_settings
from app.shared.logging import get_logger

_log = get_logger("app.llm.roles")

ROLES = ("rule_extractor", "rule_conflict_auditor", "insights_miner", "insights_reporter")

_FIELDS = ("mode", "model", "deployment", "api_version")

# role -> Settings attribute per field: <role>_mode / _model / _deployment / _api_version.
_ROLE_SETTING_ATTRS = {
    role: {f: f"{role}_{f}" for f in _FIELDS} for role in ROLES
}

# The .env alias for each (role, field) — used in Env Health / operator messages.
ROLE_ENV_KEYS = {
    role: {f: f"{role}_{f}".upper() for f in _FIELDS} for role in ROLES
}


def _normalize_mode(mode: str) -> str:
    """"cdao" is an alias of "cdao_openai" everywhere modes are compared."""
    mode = (mode or "").lower()
    return "cdao_openai" if mode == "cdao" else mode


@dataclass(frozen=True)
class RoleLLMConfig:
    """A role's EFFECTIVE LLM config after per-field resolution.

    `model` / `deployment` / `api_version` are None when the role left the
    field empty (= the active mode's own default applies at construction);
    `configured_fields` lists which fields the operator explicitly set.
    """

    role: str
    mode: str
    model: str | None
    deployment: str | None
    api_version: str | None
    configured_fields: tuple[str, ...] = field(default=())
    # The role's *_TEMPERATURE (default 1: GPT-5 rejects < 1). Always present,
    # so it never counts toward `configured_fields` — setting a temperature
    # alone must not flip a role onto its own client path.
    temperature: float = 1.0

    @property
    def configured(self) -> bool:
        """True when the operator set ANY of this role's keys — only then does
        the role get its own client (+ auto-fallback); all-empty keeps the
        plain shared-client construction path."""
        return bool(self.configured_fields)

    def default_model_label(self) -> str:
        """What this role runs on when its model/deployment fields are empty —
        display label for Env Health / fallback messages (no secrets)."""
        return default_model_for(self.role, self.mode)


def _raw(settings, role: str, fieldname: str) -> str:
    return (getattr(settings, _ROLE_SETTING_ATTRS[role][fieldname], "") or "").strip()


def resolve_role_config(role: str, settings=None) -> RoleLLMConfig:
    """role → effective {mode, model, deployment, api_version, temperature}.

    The single shared resolution helper for all four roles. Empty fields
    resolve per-field to the active mode's own defaults (returned as None —
    the adapter constructors apply their existing defaults).
    """
    if role not in ROLES:
        raise ValueError(f"unknown LLM role {role!r} (expected one of {ROLES})")
    settings = settings or get_settings()
    raw = {f: _raw(settings, role, f) for f in _FIELDS}

    # Any explicitly set field makes the role configured (no legacy keys here).
    configured_fields = tuple(f for f, v in raw.items() if v)

    mode = _normalize_mode(raw["mode"] or settings.llm_client_mode or "mock")
    model, deployment = raw["model"] or None, raw["deployment"] or None
    if mode in ("cdao_openai", "real", "azure") and (bool(model) != bool(deployment)) and (model or deployment):
        # Azure/cdao route by deployment; only one of the pair set → best-effort
        # use it for both, and say which.
        which = "model" if model else "deployment"
        _log.info("role %s: only %s_%s set — using %r for both the deployment "
                  "route and the request model id (best-effort)",
                  role, role.upper(), which.upper(), model or deployment)
    return RoleLLMConfig(
        role=role, mode=mode, model=model, deployment=deployment,
        api_version=raw["api_version"] or None,
        configured_fields=configured_fields,
        temperature=float(getattr(settings, f"{role}_temperature", 1.0)),
    )


def default_model_for(role: str, mode: str, settings=None) -> str:
    """The model a role runs on in `mode` with no explicit override — a display
    label (Env Health, fallback messages), not a constructor argument."""
    settings = settings or get_settings()
    mode = _normalize_mode(mode)
    return {
        "mock": "deterministic-template",
        "claude": settings.anthropic_model,
        "real": settings.azure_openai_deployment,
        "cdao_openai": settings.cdao_model,
        "azure": f"SmartSDK:{settings.azure_deployment_name} (fixed at construction)",
    }.get(mode, f"unknown mode '{mode}'")


def default_api_version_for(mode: str, settings=None) -> str | None:
    """The api_version the mode's adapter uses when a role sets none."""
    settings = settings or get_settings()
    return {
        "real": settings.azure_openai_api_version,
        "cdao_openai": settings.cdao_api_version,
        "azure": settings.azure_api_version,
    }.get(_normalize_mode(mode))


# --- Role client construction with single-retry auto-fallback ----------------

SERVED_ROLE_CONFIG = "role_config"
SERVED_FALLBACK = "fallback_agent_llm"
SERVED_UNAVAILABLE = "unavailable"


def build_configured_role_client(cfg: RoleLLMConfig):
    """Construct a role's OWN client from its resolved config, through the
    shared multi-mode builder. Raises on failure — callers wrap with RoleLLM
    for the auto-fallback."""
    from app.llm.client import build_llm_client

    return build_llm_client(
        cfg.mode,
        model_override=cfg.model,
        deployment_override=cfg.deployment,
        api_version_override=cfg.api_version,
        temperature_override=cfg.temperature,
    )


class RoleLLM:
    """LLMClient wrapper adding the auto-fallback for a CONFIGURED role.

    generate() tries the role's own client; on the first failure (construction
    already failed, or the first call 404s/400s) it logs a WARNING naming the
    role and reason and retries ONCE with the active default agent LLM
    (build_llm_client(LLM_MODE) — the role's keys treated as empty).
    `served_path` records which path answered: role_config /
    fallback_agent_llm / unavailable. If both fail, generate() raises so the
    caller's honest failure state engages — nothing is fabricated.
    """

    def __init__(self, cfg: RoleLLMConfig) -> None:
        self.cfg = cfg
        self.served_path = SERVED_ROLE_CONFIG
        self._active = None
        self._fallback_tried = False
        try:
            self._active = build_configured_role_client(cfg)
        except Exception as exc:  # noqa: BLE001 — fall back once, loudly
            self._fall_back(f"construction failed: {exc}")

    def _default_client(self):
        from app.llm.client import build_llm_client

        return build_llm_client(get_settings().llm_client_mode)

    def _fall_back(self, reason: str) -> None:
        """One retry with the active default agent LLM — logged, never silent."""
        self._fallback_tried = True
        settings = get_settings()
        _log.warning(
            "role %s: configured LLM (%s model=%s deployment=%s api_version=%s) "
            "unusable — %s; falling back ONCE to the default agent LLM "
            "(LLM_MODE=%s)",
            self.cfg.role, self.cfg.mode, self.cfg.model, self.cfg.deployment,
            self.cfg.api_version, reason, settings.llm_client_mode)
        try:
            self._active = self._default_client()
            self.served_path = SERVED_FALLBACK
        except Exception as exc:  # noqa: BLE001 — honest unavailable state
            _log.warning("role %s: default agent LLM also unavailable: %s",
                         self.cfg.role, exc)
            self._active = None
            self.served_path = SERVED_UNAVAILABLE

    @property
    def available(self) -> bool:
        return self._active is not None

    def generate(self, prompt: str, context: dict | None = None) -> str:
        if self._active is None:
            raise RuntimeError(
                f"role {self.cfg.role}: no LLM available (configured client and "
                f"default agent LLM both failed)")
        try:
            return self._active.generate(prompt, context)
        except Exception as exc:  # noqa: BLE001 — first-call failure → one retry
            if self._fallback_tried:
                raise  # already on the default agent LLM — honest failure
            self._fall_back(f"first call failed: {exc}")
            if self._active is None:
                raise
            return self._active.generate(prompt, context)

    def describe(self) -> dict:
        inner = self._active.describe() if self._active is not None else {}
        return {**inner, "role": self.cfg.role, "served_path": self.served_path}


def build_role_llm(role: str, settings=None):
    """The role's client, or None when the role has no per-role config (callers
    keep the plain shared-client construction path)."""
    cfg = resolve_role_config(role, settings)
    if not cfg.configured:
        return None
    return RoleLLM(cfg)
