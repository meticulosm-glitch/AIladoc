"""Configurazione da variabili d'ambiente."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "AIladoc")
    company_name: str = os.getenv("COMPANY_NAME", "")
    base_url: str = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

    data_dir: Path = Path(os.getenv("DATA_DIR", "/data"))

    # --- Keycloak / OIDC -------------------------------------------------
    # URL usato dal BROWSER (redirect di login/logout)
    keycloak_public_url: str = os.getenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8080").rstrip("/")
    # URL usato dal CONTAINER per token/JWKS/userinfo (es. http://keycloak:8080)
    keycloak_internal_url: str = os.getenv("KEYCLOAK_INTERNAL_URL", "").rstrip("/")
    keycloak_realm: str = os.getenv("KEYCLOAK_REALM", "ailadoc")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "ailadoc")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")
    oidc_scopes: str = os.getenv("OIDC_SCOPES", "openid profile email")
    # Claim aggiuntivi da cui leggere i ruoli (path puntato, es. "roles" o "groups")
    roles_extra_claims: list[str] = field(default_factory=lambda: _list("ROLES_EXTRA_CLAIMS", "roles,groups"))
    verify_tls: bool = _bool("OIDC_VERIFY_TLS", True)
    # Bundle PEM di una CA interna con cui verificare il certificato di Keycloak
    ca_file: str = os.getenv("OIDC_CA_FILE", "")

    # --- Ruoli Keycloak "di bootstrap" ------------------------------------
    # ADMIN_ROLES è sempre valido (anti lock-out). EDITOR/VIEWER servono a creare
    # i ruoli app iniziali al primo avvio; poi si gestiscono dalla UI.
    admin_roles: list[str] = field(default_factory=lambda: _list("ADMIN_ROLES", "ailadoc-admin"))
    editor_roles: list[str] = field(default_factory=lambda: _list("EDITOR_ROLES", "ailadoc-editor"))
    viewer_roles: list[str] = field(default_factory=lambda: _list("VIEWER_ROLES", "ailadoc-viewer"))

    # --- Sessione ---------------------------------------------------------
    secret_key: str = os.getenv("SECRET_KEY", "") or secrets.token_urlsafe(48)
    session_max_age: int = int(os.getenv("SESSION_MAX_AGE", str(8 * 3600)))
    cookie_secure: bool = _bool("COOKIE_SECURE", False)

    # Login di sviluppo senza Keycloak (MAI in produzione)
    dev_auth: bool = _bool("AUTH_DEV_MODE", False)
    # Al primo avvio, se /data/docs è vuota, copia i documenti di esempio
    seed_sample_docs: bool = _bool("SEED_SAMPLE_DOCS", False)

    # --- Upload / anteprime ----------------------------------------------
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "100"))
    office_preview: bool = _bool("OFFICE_PREVIEW", True)
    office_timeout: int = int(os.getenv("OFFICE_PREVIEW_TIMEOUT", "120"))

    # --- Controllo password nei documenti ---------------------------------
    secrets_scan: bool = _bool("SECRETS_SCAN", True)
    # warn: salva/carica ma avvisa (in modifica chiede conferma); block: rifiuta
    secrets_policy: str = os.getenv("SECRETS_POLICY", "warn").strip().lower()
    secrets_rescan_seconds: float = float(os.getenv("SECRETS_RESCAN_SECONDS", "30"))

    # --- Assistente (bot di ricerca documenti) ----------------------------
    assistant_enabled: bool = _bool("ASSISTANT_ENABLED", True)
    assistant_name: str = os.getenv("ASSISTANT_NAME", "AIla")
    # domande d'esempio mostrate nel pannello, separate da "|" (vuoto = suggerimenti generici)
    assistant_suggestions: list[str] = field(default_factory=lambda: [
        x.strip() for x in os.getenv("ASSISTANT_SUGGESTIONS", "").split("|") if x.strip()])
    # none | anthropic | openai (qualsiasi API compatibile OpenAI: OpenAI, Azure, Ollama, vLLM, LM Studio...)
    # Vuoto = "anthropic" se c'è ANTHROPIC_API_KEY, altrimenti modalità ricerca senza LLM
    assistant_llm: str = (os.getenv("ASSISTANT_LLM", "").strip().lower()
                          or ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "none"))
    assistant_api_key: str = os.getenv("ASSISTANT_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
    assistant_model: str = os.getenv("ASSISTANT_MODEL", "")
    assistant_base_url: str = os.getenv("ASSISTANT_BASE_URL", "")
    assistant_timeout: int = int(os.getenv("ASSISTANT_TIMEOUT", "60"))
    assistant_max_tokens: int = int(os.getenv("ASSISTANT_MAX_TOKENS", "900"))
    assistant_max_sources: int = int(os.getenv("ASSISTANT_MAX_SOURCES", "5"))
    assistant_max_question: int = int(os.getenv("ASSISTANT_MAX_QUESTION", "1000"))
    assistant_rate_per_minute: int = int(os.getenv("ASSISTANT_RATE_PER_MINUTE", "20"))
    # ogni quanti secondi, al massimo, si ricontrolla se i file sono cambiati
    assistant_rescan_seconds: float = float(os.getenv("ASSISTANT_RESCAN_SECONDS", "5"))

    def __post_init__(self) -> None:
        if self.assistant_llm == "anthropic":
            self.assistant_model = self.assistant_model or "claude-haiku-5-5"
            self.assistant_base_url = self.assistant_base_url or "https://api.anthropic.com"
        elif self.assistant_llm == "openai":
            self.assistant_base_url = self.assistant_base_url or "https://api.openai.com/v1"

    @property
    def assistant_api_key_ok(self) -> bool:
        """Anthropic richiede la chiave; un endpoint OpenAI-compatibile locale può non averla, ma serve il modello."""
        if self.assistant_llm == "anthropic":
            return bool(self.assistant_api_key)
        if self.assistant_llm == "openai":
            return bool(self.assistant_model) and (bool(self.assistant_api_key) or "api.openai.com" not in self.assistant_base_url)
        return False

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    @property
    def branding_dir(self) -> Path:
        return self.data_dir / "branding"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def db_url(self) -> str:
        return os.getenv("DATABASE_URL", f"sqlite:///{self.data_dir / 'ailadoc.db'}")

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.keycloak_realm}"

    @property
    def internal_issuer_base(self) -> str:
        base = self.keycloak_internal_url or self.keycloak_public_url
        return f"{base}/realms/{self.keycloak_realm}"


settings = Settings()
