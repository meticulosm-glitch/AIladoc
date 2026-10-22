"""Metriche Prometheus (endpoint /metrics).

- richieste HTTP: conteggio, durata e richieste in corso, per metodo e *modello* di route
  (es. "/d/{rel:path}", mai il percorso reale: niente nomi di documenti nelle etichette)
- tempi delle operazioni lente: risposte dell'assistente, chiamate all'LLM, conversioni LibreOffice,
  chiamate a Keycloak, scansioni in background (indice dell'assistente, controllo password)
- stato: documenti indicizzati, password trovate nei documenti, info sulla configurazione
- processo: CPU, memoria, file aperti, GC (collector standard di prometheus_client)

Il registro è per processo: l'app gira con un solo worker uvicorn; con più repliche
Prometheus interroga ogni pod separatamente.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, Info,
                               disable_created_metrics, generate_latest)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector
from starlette.routing import Match

disable_created_metrics()  # niente serie *_created: raddoppiano le serie senza servire a Grafana
REGISTRY = CollectorRegistry(auto_describe=True)
ProcessCollector(registry=REGISTRY)
PlatformCollector(registry=REGISTRY)
GCCollector(registry=REGISTRY)

# Pagine e API rispondono in millisecondi; LLM, LibreOffice e download grandi in secondi.
HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)
SLOW_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 60, 120, 300)

# ------------------------------------------------------------------- HTTP
HTTP_REQUESTS = Counter(
    "ailadoc_http_requests_total", "Richieste HTTP completate.", ["method", "route", "status"], registry=REGISTRY)
HTTP_DURATION = Histogram(
    "ailadoc_http_request_duration_seconds", "Durata delle richieste HTTP (fino all'ultimo byte della risposta).",
    ["method", "route"], buckets=HTTP_BUCKETS, registry=REGISTRY)
HTTP_IN_PROGRESS = Gauge(
    "ailadoc_http_requests_in_progress", "Richieste HTTP in corso.", ["method"], registry=REGISTRY)

# ------------------------------------------------------------- assistente
ASSISTANT_DURATION = Histogram(
    "ailadoc_assistant_answer_duration_seconds",
    "Tempo per rispondere a una domanda all'assistente (ricerca + eventuale LLM).",
    ["mode"], buckets=SLOW_BUCKETS, registry=REGISTRY)
ASSISTANT_NO_RESULTS = Counter(
    "ailadoc_assistant_no_results_total", "Domande per cui non è stato trovato nessun documento.", registry=REGISTRY)
ASSISTANT_RATE_LIMITED = Counter(
    "ailadoc_assistant_rate_limited_total", "Domande rifiutate per il limite al minuto.", registry=REGISTRY)
LLM_DURATION = Histogram(
    "ailadoc_llm_request_duration_seconds", "Durata delle chiamate al modello linguistico.",
    ["provider", "outcome"], buckets=SLOW_BUCKETS, registry=REGISTRY)

# --------------------------------------------------------------- anteprime
OFFICE_CONVERSION = Histogram(
    "ailadoc_office_conversion_duration_seconds", "Durata delle conversioni Office -> PDF con LibreOffice.",
    ["outcome"], buckets=SLOW_BUCKETS, registry=REGISTRY)
OFFICE_CACHE = Counter(
    "ailadoc_office_preview_cache_total", "Anteprime PDF servite dalla cache (hit) o da convertire (miss).",
    ["result"], registry=REGISTRY)

# -------------------------------------------------------------------- login
LOGINS = Counter(
    "ailadoc_logins_total", "Tentativi di accesso per metodo ed esito.", ["method", "result"], registry=REGISTRY)
KEYCLOAK_DURATION = Histogram(
    "ailadoc_keycloak_request_duration_seconds", "Durata delle chiamate a Keycloak durante il login.",
    ["operation", "outcome"], buckets=HTTP_BUCKETS, registry=REGISTRY)

# -------------------------------------------------------------- background
BACKGROUND_DURATION = Histogram(
    "ailadoc_background_task_duration_seconds",
    "Durata delle scansioni dei documenti (indice dell'assistente, controllo password).",
    ["task"], buckets=SLOW_BUCKETS, registry=REGISTRY)
BACKGROUND_LAST_RUN = Gauge(
    "ailadoc_background_task_last_run_timestamp_seconds", "Fine dell'ultima scansione completata (Unix time).",
    ["task"], registry=REGISTRY)

APP_INFO = Info("ailadoc_app", "Configurazione dell'istanza.", registry=REGISTRY)


@contextmanager
def timed(histogram: Histogram, **labels: str) -> Iterator[dict]:
    """Misura un blocco. Se tra le etichette c'è "outcome" (es. outcome="ok") si può cambiare nel dict
    restituito; se il blocco solleva un'eccezione diventa "error"."""
    state = dict(labels)
    start = time.perf_counter()
    try:
        yield state
    except BaseException:
        if "outcome" in state and state["outcome"] == "ok":
            state["outcome"] = "error"
        raise
    finally:
        histogram.labels(**state).observe(time.perf_counter() - start)


@contextmanager
def background_task(task: str) -> Iterator[None]:
    start = time.perf_counter()
    yield
    BACKGROUND_DURATION.labels(task=task).observe(time.perf_counter() - start)
    BACKGROUND_LAST_RUN.labels(task=task).set(time.time())


# ------------------------------------------------------- stato dell'app
class _StateCollector:
    """Valori letti al momento dello scrape, senza avviare scansioni del disco."""

    def collect(self):
        from . import assistant, secretscan
        from .config import settings

        docs = GaugeMetricFamily("ailadoc_assistant_index_documents", "Documenti nell'indice dell'assistente.")
        passages = GaugeMetricFamily("ailadoc_assistant_index_passages", "Brani nell'indice dell'assistente.")
        try:
            entries = list(assistant.INDEX.docs.values())
            docs.add_metric([], len(entries))
            passages.add_metric([], sum(len(d.passages) for d in entries))
        except RuntimeError:  # indice modificato durante la lettura: salta questo giro
            pass
        yield docs
        yield passages

        if settings.secrets_scan:
            findings = GaugeMetricFamily(
                "ailadoc_secret_findings", "Password e credenziali trovate nei documenti (escluse quelle ignorate).")
            files = GaugeMetricFamily("ailadoc_secret_files", "Documenti con almeno una password trovata.")
            try:
                found = secretscan.SCANNER.all()
                findings.add_metric([], sum(len(v) for v in found.values()))
                files.add_metric([], len(found))
            except RuntimeError:
                pass
            yield findings
            yield files

    def describe(self):
        return []


REGISTRY.register(_StateCollector())


def set_app_info(**values: str) -> None:
    APP_INFO.info({k: str(v) for k, v in values.items()})


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# ----------------------------------------------------------- middleware
def _route_of(scope, original) -> str:
    """Modello della route (bassa cardinalità). Percorsi sconosciuti -> "<unmatched>".
    `original` è lo scope prima del router (che lo modifica, es. root_path per i Mount)."""
    route = scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    app = scope.get("app")
    partial = None
    for r in getattr(app, "routes", ()):
        match, _ = r.matches(original)
        if match == Match.FULL:
            return r.path
        if match == Match.PARTIAL and partial is None:  # metodo non ammesso
            partial = r.path
    return partial or "<unmatched>"


class PrometheusMiddleware:
    """Middleware ASGI puro (non bufferizza: funziona anche con FileResponse e risposte in streaming)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        original = dict(scope)
        status = 500
        start = time.perf_counter()

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        in_progress = HTTP_IN_PROGRESS.labels(method=method)
        in_progress.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            in_progress.dec()
            route = _route_of(scope, original)
            HTTP_DURATION.labels(method=method, route=route).observe(time.perf_counter() - start)
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
