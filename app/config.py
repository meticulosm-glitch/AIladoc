"""Configurazione da variabili d'ambiente."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


def _list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


LOCAL_USER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _local_users(raw: str) -> dict[str, list[str]]:
    """LOCAL_USERS: JSON {"admin": ["ailadoc-admin"], "mario": ["ailadoc-editor"]}
    oppure nomi separati da virgola (utenti senza ruoli Keycloak)."""
    raw = raw.strip()
    if not raw:
        return {}
    try:
        items = json.loads(raw) if raw.startswith("{") else {x: [] for x in raw.split(",")}
    except ValueError:
        logging.getLogger("ailadoc.config").error("LOCAL_USERS non è un JSON valido: utenti locali disattivati")
        return {}
    out: dict[str, list[str]] = {}
    for name, roles in items.items():
        name = str(name).strip().lower()
        if not name:
            continue
        if not LOCAL_USER_RE.match(name):
            logging.getLogger("ailadoc.config").error(
                "Utente locale %r ignorato: usa lettere minuscole, cifre, '.', '_' o '-' (max 64)", name)
            continue
        if isinstance(roles, str):
            roles = [roles]
        out[name] = sorted({str(r).strip() for r in roles or [] if str(r).strip()})
    return out


def _secret_key() -> str:
    """SECRET_KEY dall'ambiente; se manca viene generata una sola volta e salvata in
    DATA_DIR/.secret_key, così resta la stessa tra riavvii e repliche che condividono il volume."""
    key = os.getenv("SECRET_KEY", "").strip()
    if key:
        return key
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    path = data_dir / ".secret_key"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # creata da un avvio precedente o da un'altra replica: attende che sia scritta
        for _ in range(50):
            key = path.read_text().strip()
            if key:
                return key
            time.sleep(0.1)
        raise RuntimeError(f"{path} è vuoto: cancellalo oppure imposta SECRET_KEY")
    except OSError:
        # volume non scrivibile: chiave valida solo per questo processo
        return secrets.token_urlsafe(48)
    key = secrets.token_urlsafe(48)
    with os.fdopen(fd, "w") as f:
        f.write(key)
    return key


DEFAULT_EMBED_HOSTS = (
    "www.figma.com,figma.com,miro.com,docs.google.com,drive.google.com,calendar.google.com,"
    "*.sharepoint.com,onedrive.live.com,forms.office.com,app.powerbi.com,www.youtube.com,"
    "www.youtube-nocookie.com,youtube.com,player.vimeo.com,www.loom.com,viewer.diagrams.net,"
    "app.diagrams.net,embed.diagrams.net,lucid.app,*.atlassian.net")


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

    # --- Pagina di login ---------------------------------------------------
    # form:     pagina di login dell'app; nome utente e password li verifica Keycloak lato server
    #           (il client deve avere "Direct access grants"). L'utente non vede la pagina di Keycloak.
    # redirect: si va alla pagina di login di Keycloak (Authorization Code + PKCE).
    login_mode: str = os.getenv("LOGIN_MODE", "form").strip().lower()
    # Mostra anche "Accedi con Single Sign-On" (redirect a Keycloak: provider esterni, passkey, ...)
    login_sso_button: bool = _bool("LOGIN_SSO_BUTTON", False)
    # Campo "Codice di verifica" per chi ha l'OTP attivo in Keycloak
    login_otp: bool = _bool("LOGIN_OTP", False)
    # Link "Password dimenticata?": vuoto = nascosto, "keycloak" = reset del realm, oppure un URL
    password_reset_url: str = os.getenv("PASSWORD_RESET_URL", "").strip()
    # Tentativi falliti ammessi in 10 minuti per utente e indirizzo IP (per singolo IP: 5 volte tanto).
    # La protezione vera è la "Brute force detection" del realm Keycloak.
    login_max_attempts: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))

    # --- Ruoli Keycloak "di bootstrap" ------------------------------------
    # ADMIN_ROLES è sempre valido (anti lock-out). EDITOR/VIEWER servono a creare
    # i ruoli app iniziali al primo avvio; poi si gestiscono dalla UI.
    admin_roles: list[str] = field(default_factory=lambda: _list("ADMIN_ROLES", "ailadoc-admin"))
    editor_roles: list[str] = field(default_factory=lambda: _list("EDITOR_ROLES", "ailadoc-editor"))
    viewer_roles: list[str] = field(default_factory=lambda: _list("VIEWER_ROLES", "ailadoc-viewer"))

    # --- Sessione ---------------------------------------------------------
    # vuota = generata al primo avvio e salvata in DATA_DIR/.secret_key
    secret_key: str = field(default_factory=_secret_key)
    session_max_age: int = int(os.getenv("SESSION_MAX_AGE", str(8 * 3600)))
    cookie_secure: bool = _bool("COOKIE_SECURE", False)

    # --- Utenti locali (accesso senza Keycloak, es. amministratore d'emergenza) ---
    # nome -> ruoli; le password stanno in LOCAL_USERS_DIR, un file per utente
    local_users: dict[str, list[str]] = field(default_factory=lambda: _local_users(os.getenv("LOCAL_USERS", "")))
    local_users_dir: Path = Path(os.getenv("LOCAL_USERS_DIR", "/etc/ailadoc/local-users"))

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

    # --- Plugin (macro nelle pagine) --------------------------------------
    # "all" oppure elenco tra: macros, tables, drawio
    plugins: list[str] = field(default_factory=lambda: [x.lower() for x in _list("PLUGINS", "all")] or ["all"])
    # Editor draw.io incorporato (gira nel browser: il diagramma non passa dal server di draw.io).
    # Self-hosting: docker run jgraph/drawio e indica qui il suo URL. Vuoto = modifica disattivata.
    drawio_editor_url: str = os.getenv("DRAWIO_EDITOR_URL", "https://embed.diagrams.net").rstrip("/")
    # Siti ammessi nella macro "embed" (iframe). "*.dominio" = anche i sottodomini. Vuoto = predefiniti.
    embed_allowed_hosts: list[str] = field(default_factory=lambda: [
        x.lower() for x in (_list("EMBED_ALLOWED_HOSTS") or DEFAULT_EMBED_HOSTS.split(","))])

    # --- Metriche Prometheus (GET /metrics) -------------------------------
    metrics_enabled: bool = _bool("METRICS_ENABLED", True)
    # Se impostato, /metrics richiede "Authorization: Bearer <token>". Consigliato se /metrics è raggiungibile
    # da Internet (l'ingress pubblica tutta l'app); vuoto = endpoint aperto (rete interna / NetworkPolicy).
    metrics_token: str = os.getenv("METRICS_TOKEN", "")

    def __post_init__(self) -> None:
        if self.login_mode not in ("form", "redirect"):
            self.login_mode = "form"
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
    def password_reset_link(self) -> str:
        if self.password_reset_url.lower() == "keycloak":
            return f"{self.issuer}/login-actions/reset-credentials?client_id={quote(self.oidc_client_id)}"
        return self.password_reset_url

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
