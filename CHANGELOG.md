# Changelog

Le modifiche di AIladoc, release per release. Ogni release è un tag git: il workflow
`.github/workflows/docker-publish.yml` pubblica l'immagine `meticulo/ailadoc:<tag>`.
La versione del chart Helm (`charts/ailadoc/Chart.yaml`) è indicata a parte.

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it-IT/1.1.0/); versioni [SemVer](https://semver.org/lang/it/).

## [Non rilasciato]

Chart `0.3.1`.

### Corretto
- Chart: `appVersion` era rimasta `0.1.0`, un tag mai pubblicato. Senza `image.tag` nei values il pod e il Job delle password andavano in `ErrImagePull` (`meticulo/ailadoc:0.1.0: not found`). Ora è `4.0.0`.
- Il workflow di pubblicazione avvisa quando il tag git non corrisponde all'`appVersion` del chart.

## [4.0.0] - 23-10-2026

Chart `0.3.0`.

### Aggiunto
- **Utenti locali**: accesso con nome utente e password senza passare da Keycloak, per esempio un amministratore d'emergenza quando Keycloak non risponde. Utenti e ruoli da `LOCAL_USERS`, password da `LOCAL_USERS_DIR/<nome>` (una nuova password vale subito, senza riavvio). Stessa pagina di login; con `LOGIN_MODE=redirect` la pagina è `/login/local`. Stesso limite di tentativi degli altri accessi; metrica `ailadoc_logins_total{method="local"}`.
- Chart: `localUsers.users` (di default solo `admin`, amministratore). Un **Job** (hook `pre-install,pre-upgrade`, `PreSync` con Argo CD) genera password casuali nel Secret `<release>-ailadoc-local-users`: password nuove solo per gli utenti nuovi, invariate per quelli esistenti, rimosse per quelli tolti. Il Job usa l'immagine dell'app e un service account che può leggere e scrivere solo quel Secret.
- Chart: **Vault con External Secrets Operator**. Con `vault.address` il chart crea `SecretStore` ed `ExternalSecret` (autenticazione `kubernetes`, `token` o `appRole`, CA, namespace Enterprise, oppure uno store esistente con `vault.existingStore`). Le chiavi in `vault.keys` arrivano da Vault nel Secret `<release>-ailadoc-vault`, che ha la precedenza su quello del chart.
- Chart: senza Vault, le chiavi di `vault.keys` senza valore nei values ricevono il segnaposto **`Changeme`**, così il deploy parte subito. Le note di installazione elencano i segnaposto.
- `SECRET_KEY` facoltativa: se manca, l'app la genera al primo avvio e la salva in `DATA_DIR/.secret_key`. Resta valida tra riavvii e repliche che condividono il volume.

### Modificato
- Chart: il Secret dell'app è sempre creato dai template e dipende solo dai values, quindi con Argo CD (`helm template`) non cambia a ogni sync. Il chart non genera più la `SECRET_KEY`: le installazioni Helm esistenti mantengono quella salvata nel Secret.
- Chart: `keycloak.url` ha come default `https://sso.example.com` (da cambiare), quindi il chart si installa anche con i soli values di default.
- Chart: il ServiceMonitor prende `METRICS_TOKEN` dal Secret di Vault quando la chiave è in `vault.keys`.

### Note di aggiornamento
- Serve una nuova immagine dell'app per gli utenti locali e per la `SECRET_KEY` salvata nel volume.
- Gli utenti locali sono attivi di default (`admin`). Per non averli: `localUsers.enabled: false`.
- Con un client Keycloak pubblico togli `OIDC_CLIENT_SECRET` da `vault.keys` (`vault.keys.OIDC_CLIENT_SECRET: null`), altrimenti riceve il segnaposto.

## [3.0.1] - 2026-10-23

Chart `0.2.0`.

### Aggiunto
- Chart: **Argo Rollouts**. Di default un `Rollout` (canary) sostituisce il `Deployment`; si torna al `Deployment` con `rollout.enabled: false`. Con il volume `ReadWriteOnce` il canary sostituisce il pod (`maxSurge: 0`, `maxUnavailable: 1`) e resta in pausa 2 minuti per un eventuale `abort`. Strategia `blueGreen` (Service `-preview`), traffico diviso con ingress-nginx (Service `-canary`) e analisi (AnalysisTemplate) configurabili.
- Chart: comandi `kubectl argo rollouts` nelle note di installazione.

### Modificato
- Chart: il pod è definito una sola volta (`_podtemplate.tpl`) e condiviso da `Deployment` e `Rollout`.
- Chart: il ServiceMonitor esclude i Service `-canary`/`-preview` per non duplicare le metriche.

## [3.0.0] - 2026-10-23

### Aggiunto
- **Immagini in tre dimensioni** nell'editor: il pulsante immagine chiede *Piccola*, *Media* o *Grande* (classi `.img-piccola`, `.img-media`, `.img-grande`). Le immagini si possono anche trascinare o incollare nel testo.

### Corretto
- Link e immagini con spazi o parentesi nel nome del file: il percorso non viene più codificato due volte (`foto%2520uno.png`) e il file si trova.

## [2.0.1] - 2026-10-22

### Aggiunto
- **Pagina di login dell'app** (`LOGIN_MODE=form`, il default): nome utente e password verificati da Keycloak lato server (*Direct access grants*), senza mostrare la pagina di Keycloak. Opzioni: pulsante «Accedi con Single Sign-On» (`LOGIN_SSO_BUTTON`), codice OTP (`LOGIN_OTP`), link «Password dimenticata?» (`PASSWORD_RESET_URL`), limite di tentativi per utente e IP (`LOGIN_MAX_ATTEMPTS`). Messaggi chiari per account bloccati, disabilitati o da completare su Keycloak.
- **Metriche Prometheus** su `GET /metrics`: richieste HTTP, assistente e LLM, conversioni LibreOffice, accessi e tempi di Keycloak, scansioni in background, configurazione dell'istanza. Protezione facoltativa con `METRICS_TOKEN` (Bearer).
- Chart: `metrics.*`, ServiceMonitor per Prometheus Operator (`metrics.serviceMonitor`), annotazioni `prometheus.io/*` e opzioni `login.*`.

## [2.0.0] - 2026-10-21

### Aggiunto
- **Plugin delle pagine** (`PLUGINS`):
  - **draw.io**: diagrammi `.drawio` visualizzati e modificati nel browser (`DRAWIO_EDITOR_URL`, anche con un'istanza interna);
  - **tabelle dinamiche** da Excel/CSV con colonne calcolate, filtri, raggruppamenti, pivot, totali, formati e grafici;
  - **macro di formattazione**: pannelli, card, pulsanti, hero, colonne, tab, expand, avanzamento, countdown, LaTeX, HTML sanificato, `embed` (siti ammessi in `EMBED_ALLOWED_HOSTS`), `include` di sezioni di altre pagine.
- Mermaid, KaTeX e il visualizzatore draw.io inclusi nell'immagine (`docker/fetch_vendor.py`): nessuna dipendenza da CDN.
- Le citazioni tra documenti rispettano i permessi di chi legge.
- Chart: `plugins.*`.

## [1.0.0] - 2026-10-21

Prima release. Chart `0.1.0`.

### Aggiunto
- Portale di documentazione con accesso **Keycloak** (OIDC, Authorization Code + PKCE) e ruoli da realm, client e gruppi.
- Pagine **Markdown** (compatibili MkDocs Material) in cartelle e sottocartelle, allegati con icona per tipo.
- **Anteprime** nel browser: PDF, Excel/CSV come tabella, PowerPoint e Word convertiti in PDF con LibreOffice.
- **Editor** con anteprima affiancata e creazione rapida di pagine, cartelle e strutture.
- **Permessi** per cartella o documento, ruoli app e gruppi locali, amministrazione dalla UI.
- **Controllo password** nei documenti (anche in PDF, Word ed Excel), con conferma prima di salvare e oscuramento in ricerca e assistente.
- Assistente **AIla**: ricerca tra i documenti visibili all'utente; con un LLM (Anthropic o API compatibili OpenAI) risponde citando le fonti.
- Loghi personalizzabili, Docker Compose e chart Helm (`ailadoc`) con Secret per le credenziali, PVC, Ingress e pod non-root.
- Build dell'immagine da `docker/Dockerfile` e workflow GitHub che a ogni tag pubblica `meticulo/ailadoc:<tag>` su Docker Hub.

[Non rilasciato]: ../../compare/4.0.0...HEAD
[4.0.0]: ../../compare/3.0.1...4.0.0
[3.0.1]: ../../compare/3.0.0...3.0.1
[3.0.0]: ../../compare/2.0.1...3.0.0
[2.0.1]: ../../compare/2.0.0...2.0.1
[2.0.0]: ../../compare/1.0.0...2.0.0
[1.0.0]: ../../releases/tag/1.0.0
