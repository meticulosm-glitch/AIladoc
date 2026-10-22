# AIladoc

Portale di documentazione aziendale, containerizzato. Si accede con l'account **Keycloak** e ognuno vede solo quello che i suoi ruoli gli permettono: chi ha il ruolo di lettore consulta, chi ha il ruolo di editor scrive, gli amministratori decidono chi vede cosa. Chi non ha nessun ruolo abilitato vede solo una pagina di accesso negato.

- Pagine **Markdown** (compatibili MkDocs Material) organizzate in **cartelle e sottocartelle**, più allegati con un'icona per tipo: PDF, PowerPoint, Excel/CSV, Word, immagini, video, archivi.
- **Anteprime nel browser**: PDF nativo, Excel e CSV come tabella, PowerPoint e Word convertiti in PDF da LibreOffice.
- **Editor** con anteprima affiancata e **creazione rapida** di pagine, cartelle e intere strutture.
- **Permessi** per cartella o per documento, basati su ruoli Keycloak e gruppi locali.
- **Controllo password**: segnala password, PIN, token e chiavi scritti in chiaro nei documenti (anche dentro PDF, Word ed Excel), chiede conferma prima di salvarli e li oscura in ricerca e assistente.
- Assistente **AIla**: trova i documenti partendo da una domanda scritta a parole proprie; con un LLM configurato risponde citando le fonti.
- **Plugin** nelle pagine: diagrammi **draw.io** (visualizzazione e modifica nel browser), **tabelle dinamiche** da Excel/CSV con calcoli, filtri, pivot e grafici, **macro di formattazione** (pannelli, card, pulsanti, hero, tab, colonne, stato, countdown, LaTeX, HTML, contenuti incorporati, citazione di altre pagine).

---

## Come funziona

```
  Browser ──────────────► AIladoc (container, porta 8000) ──────► Keycloak (esterno, OIDC)
     │   login/logout                │        ▲   token, chiavi pubbliche
     └──────────────────────────────►│        │
     pagina di login dell'app        ▼
                              /data  (volume)
                              ├── docs/        documenti e cartelle
                              ├── branding/    loghi
                              ├── cache/       anteprime PDF, indice dell'assistente
                              └── ailadoc.db   ruoli app, gruppi locali, permessi (SQLite)
```

### Accesso

1. L'utente apre l'app e trova la **pagina di accesso dell'app** (logo, nome utente, password). Le credenziali le verifica Keycloak lato server (grant *password*, «Direct access grants»): l'utente non vede la pagina di Keycloak e la password non viene salvata. Con `LOGIN_MODE=redirect` si usa invece la pagina di Keycloak (Authorization Code + PKCE).
2. L'app verifica i token con le chiavi pubbliche del realm e legge i **ruoli** da `realm_access`, `resource_access` e dai claim in `ROLES_EXTRA_CLAIMS` (di default `roles` e `groups`).
3. I ruoli Keycloak vengono tradotti in **ruoli app** (vedi sotto). Il ruolo app con il livello più alto decide l'accesso: *nessuno* → pagina di accesso negato, *lettura*, *modifica*, *amministratore*.
4. La sessione è un cookie firmato con `SECRET_KEY`. I ruoli si aggiornano a ogni login. «Esci» chiude anche la sessione su Keycloak.

### Contenuti

Tutto quello che c'è in `data/docs/` è la documentazione: ogni cartella è una sezione del menu, un `index.md` dentro una cartella è la sua pagina, un prefisso numerico (`01-`, `02-`) decide l'ordine e non viene mostrato. I file si gestiscono dall'app oppure copiandoli direttamente nel volume (rsync, git, `kubectl cp`): l'app li legge dal disco a ogni richiesta.

Per creare contenuti gli editor usano il pannello **Nuovo** (pulsante in cima al menu, **+** accanto a ogni cartella, oppure il tasto <kbd>N</kbd>):

| Scrivi | Risultato |
|--------|-----------|
| `Controllo accessi` | pagina `controllo-accessi.md` con titolo «Controllo accessi», aperta nell'editor |
| `Procedure/Qualità/Controllo accessi` | crea anche le cartelle mancanti *Procedure* e *Qualità* |
| `01 Introduzione` | `01-introduzione.md`, titolo «Introduzione», prima nel menu |
| `Manuali/` (o modalità *Cartella*) | solo cartella, con pagina `index.md` facoltativa |

La modalità **Struttura** crea una sezione intera in un colpo solo: una riga per elemento, il rientro indica l'annidamento, le righe che finiscono con `/` (o che hanno righe rientrate sotto) diventano cartelle. <kbd>⇧</kbd>+<kbd>↵</kbd> crea e lascia il pannello aperto per l'elemento successivo.

```text
Procedure/
  Qualità/
    Controllo accessi
    Non conformità
  Gestione resi
Glossario
```

### Ruoli e permessi

```
Ruoli Keycloak ─┐
                ├─► Ruoli app ─► livello globale (nessuno / lettura / modifica / admin)
Gruppi locali  ─┘                       │
                                        ▼
                     Restrizioni su cartelle e documenti (ACL)
```

1. **Ruoli app** (*Amministrazione → Ruoli app*): un ruolo app vale per chi ha *almeno uno* dei ruoli Keycloak indicati, oppure è in uno dei gruppi locali collegati. Al primo avvio ne vengono creati tre (Amministratori, Editor, Lettori) da `ADMIN_ROLES`, `EDITOR_ROLES`, `VIEWER_ROLES`.
2. **Gruppi locali** (*Amministrazione → Gruppi locali*): elenchi di username o email, per quando in Keycloak manca il ruolo giusto.
3. **Restrizioni** (*Amministrazione → Permessi documenti*, oppure «⋯ → Permessi»): senza restrizioni un contenuto è visibile a chiunque abbia accesso all'app. Con **Restringi accesso** su una cartella o un file, solo le voci elencate (ruolo app, gruppo locale, ruolo Keycloak, singolo utente) possono accedere, in *Lettura* o *Modifica*. Vale per tutto il contenuto della cartella, salvo sottocartelle o file con una restrizione propria.
4. Il ruolo Keycloak è il **tetto massimo**: un'ACL in *Modifica* non rende editor chi ha solo il livello Lettura.
5. I contenuti non accessibili spariscono da menu, ricerca e assistente; aprendo un link diretto compare la pagina di accesso negato. Gli amministratori vedono tutto, e chi ha un ruolo in `ADMIN_ROLES` resta amministratore anche se i ruoli app vengono cancellati.

### Password nei documenti

Ogni documento viene controllato alla ricerca di **password e credenziali scritte in chiaro**, con due livelli:

1. **[detect-secrets](https://github.com/Yelp/detect-secrets)** (Yelp) per i formati riconoscibili: chiavi AWS e Azure, token GitHub/GitLab/Slack/Stripe/OpenAI/npm/PyPI, JWT, chiavi private, credenziali dentro un URL (`postgres://utente:password@host`).
2. **Regole proprie** (`app/secretscan.py`) per la documentazione scritta da persone, in italiano e in inglese: «Password: Estate2026!», «la password del wifi è …», «PIN: 4821», «Credenziali: admin / …», «chiave WPA: …», «API key: …», le colonne *Password*/*PIN*/*Token* nelle tabelle Markdown e Word e nei fogli Excel/CSV. Segnaposto (`****`, `<password>`, `${DB_PASSWORD}`), link e frasi normali («la password è obbligatoria», «chiedila all'IT») vengono ignorati.

Cosa succede quando ne trova una:

| Dove | Cosa vede l'utente |
|------|--------------------|
| Editor | Un riquadro elenca le righe sospette mentre scrivi; al salvataggio chiede conferma (con `SECRETS_POLICY=block` non salva) |
| Caricamento file | Avviso dopo l'upload (con `block` il file viene rifiutato) |
| Pagina del documento | Avviso con le posizioni, solo per chi può modificarlo |
| Amministrazione → Password nei documenti | Tutti i documenti con possibili password, il punto esatto (riga, pagina, slide, foglio), «Non è una password» per i falsi positivi, «Ricontrolla tutto» |
| Menu | Una chiave accanto ai documenti interessati (solo amministratori) |
| Ricerca e assistente AIla | I valori sono sostituiti da `••••••`: non compaiono negli estratti e non vengono mai inviati all'LLM |

I valori trovati **non vengono mai salvati**: l'app conserva una versione mascherata (`E•••••••••!`) e un'impronta HMAC per riconoscere i falsi positivi. Il controllo riparte da solo quando un file cambia, anche se viene copiato a mano in `data/docs/`.

### Assistente AIla

Il pulsante **Chiedi a AIla** (o <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>J</kbd>) apre una chat. AIla cerca solo tra i documenti che l'utente può aprire, anche dentro PDF, Word, PowerPoint ed Excel, e ogni fonte porta al punto giusto (sezione, pagina del PDF, slide, foglio). L'indice si costruisce all'avvio e si aggiorna quando i file cambiano; il testo estratto resta in `data/cache/assistant/`.

| | Senza LLM (predefinita) | Con LLM |
|---|---|---|
| Risposta | Il documento più pertinente e le alternative | 2–6 frasi con fonti citate `[1]` `[2]` |
| Dati in uscita | Nessuno | Solo gli estratti dei documenti visibili all'utente, verso il provider scelto |

Se l'LLM non risponde, AIla mostra comunque i documenti trovati.

### Plugin: diagrammi, tabelle e macro

Le macro si scrivono nel Markdown con la sintassi a blocchi di MkDocs Material (`pymdownx.blocks`): `/// nome | argomento`, le opzioni subito sotto rientrate di 4 spazi (YAML), il contenuto, poi `///`. Per annidare, il blocco esterno usa una barra in più (`////`). Nell'editor sono tutte nel menu **Inserisci**; la pagina **Macro e plugin** (`/plugins`, dal menu utente) mostra ogni esempio con il sorgente accanto al risultato.

```text
/// table | Spesa per reparto                ← dati da un Excel/CSV della documentazione
    source: ../Amministrazione/spese.xlsx
    filter: Stato <> "Respinto"
    group: Reparto
    aggregate: ["sum(Importo) as Totale"]
    format: {Totale: euro}
    chart: bar
///

/// drawio | schema-rete.drawio              ← diagramma draw.io
    page: 2
///

/// include | ../Procedure/resi.md#tempi    ← cita una sezione di un'altra pagina
///
```

| Plugin | Cosa aggiunge |
|--------|---------------|
| **draw.io** (`drawio`) | I file `.drawio` si caricano come gli altri allegati o si creano dall'editor (*Inserisci → Nuovo diagramma*). Si vedono con il visualizzatore draw.io (pagine, livelli, zoom, schermo intero); chi può modificarli usa **Modifica diagramma**, che apre l'editor draw.io incorporato: il diagramma passa tra il browser e l'iframe e viene salvato da AIladoc, senza caricarlo sui server di draw.io. Nelle pagine: `/// drawio \| file.drawio` oppure `![didascalia](file.drawio)`. Il testo delle forme è indicizzato da AIla e controllato dal controllo password. |
| **Tabelle** (`tables`) | `/// table` legge un `.xlsx`/`.csv` (o i dati scritti nel blocco) e applica, in quest'ordine, `compute` (colonne calcolate), `filter`, `group`+`aggregate` o `pivot`, `sort`, `columns`, `limit`, `totals`; poi `format` (euro, percentuali, date), `highlight`, `colors` (stati colorati) e `chart` (barre, linee, aree, torta, ciambella). Le espressioni sono valutate da un interprete ristretto (niente `eval`). Nel browser la tabella si ordina cliccando le intestazioni, si filtra e si scarica in CSV. Nell'editor: editor visuale delle tabelle Markdown (▦), incolla da Excel → tabella, *Tabella da Excel/CSV…*. |
| **Macro** (`macros`) | `panel`, `cards`/`card`, `button`, `hero`, `title`, `divider`, `background`, `columns`/`column`, `tabs` (anche verticali) con `tab`, `expand`, `progress`, `countdown`, `latex` (e `$…$`), `html` (sanificato: niente script), `embed` (iframe solo dai siti in `EMBED_ALLOWED_HOSTS`, con conversione automatica dei link di YouTube, Figma, Miro, Google, Loom), `include` (cita un'altra pagina o una sua sezione), `pages` (panoramica dinamica di una cartella); in linea `{{status: Testo \| colore}}` e `{{icon: nome}}`; `numbered_headings: true` nel front matter numera i titoli. |

Le citazioni rispettano i permessi di chi legge: `include`, `table` con `source`, `drawio` e `pages` mostrano solo documenti che l'utente può aprire (altrimenti un riquadro «non esiste o non hai i permessi», senza rivelare se il file c'è). Mermaid, KaTeX e il visualizzatore draw.io sono serviti dall'app (`/static/vendor`), non da CDN.

---

## Variabili d'ambiente

Il file `.env.example` le contiene tutte, con commenti. Con Helm non si scrivono a mano: le genera il chart dai valori (vedi [Kubernetes](#kubernetes-helm)).

### Obbligatorie in produzione

| Variabile | Esempio | Descrizione |
|-----------|---------|-------------|
| `BASE_URL` | `https://docs.azienda.it` | URL pubblico dell'app, usato per i redirect di login e logout |
| `SECRET_KEY` | 48+ caratteri casuali | Firma dei cookie di sessione. Se manca ne viene generata una a ogni avvio e tutti vengono disconnessi. Genera con `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `KEYCLOAK_PUBLIC_URL` | `https://sso.azienda.it` | Keycloak come lo raggiunge il browser, senza `/realms/...` |
| `KEYCLOAK_REALM` | `ailadoc` | Realm |
| `OIDC_CLIENT_ID` | `ailadoc` | Client OIDC |
| `OIDC_CLIENT_SECRET` | | Secret del client confidenziale (vuoto se il client è pubblico) |
| `COOKIE_SECURE` | `true` | `true` quando l'app è in HTTPS |

### Keycloak e ruoli

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `KEYCLOAK_INTERNAL_URL` | vuoto | Keycloak come lo raggiunge il container, se diverso dal pubblico (es. `http://keycloak:8080`). Keycloak deve avere `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` |
| `OIDC_SCOPES` | `openid profile email` | |
| `ROLES_EXTRA_CLAIMS` | `roles,groups` | Claim aggiuntivi da cui leggere ruoli/gruppi (percorsi puntati ammessi) |
| `OIDC_CA_FILE` | vuoto | File PEM della CA interna se Keycloak ha un certificato aziendale |
| `OIDC_VERIFY_TLS` | `true` | Solo per test: `false` disattiva la verifica del certificato |
| `ADMIN_ROLES` | `ailadoc-admin` | Ruoli Keycloak sempre amministratori (separati da virgola) |
| `EDITOR_ROLES` | `ailadoc-editor` | Ruoli del ruolo app «Editor» creato al primo avvio |
| `VIEWER_ROLES` | `ailadoc-viewer` | Ruoli del ruolo app «Lettori» creato al primo avvio |
| `SESSION_MAX_AGE` | `28800` | Durata della sessione in secondi |

### Pagina di login

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `LOGIN_MODE` | `form` | `form`: pagina di login dell'app, credenziali verificate da Keycloak lato server (il client deve avere *Direct access grants*). `redirect`: pagina di login di Keycloak |
| `LOGIN_SSO_BUTTON` | `false` | Aggiunge «Accedi con Single Sign-On», che passa dalla pagina di Keycloak (provider esterni, passkey) |
| `LOGIN_OTP` | `false` | Campo «Codice di verifica» per chi ha l'OTP attivo in Keycloak |
| `PASSWORD_RESET_URL` | vuoto | Link «Password dimenticata?»: `keycloak` = reset del realm (serve *Forgot password* attivo nel realm), oppure un URL. Vuoto = nascosto |
| `LOGIN_MAX_ATTEMPTS` | `10` | Tentativi falliti in 10 minuti per utente e IP prima di una pausa (per IP: 5 volte tanto). La difesa principale resta la *Brute force detection* di Keycloak |

### Applicazione e contenuti

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `APP_NAME` | `AIladoc` | Nome mostrato in alto e nel titolo delle pagine |
| `COMPANY_NAME` | vuoto | Mostrato in fondo al menu se non c'è il logo aziendale |
| `DATA_DIR` | `/data` | Cartella dei dati (documenti, loghi, cache, database) |
| `DATABASE_URL` | SQLite in `DATA_DIR/ailadoc.db` | Anche `postgresql+psycopg://user:pass@host/db` (aggiungi `psycopg[binary]` a `requirements.txt`) |
| `MAX_UPLOAD_MB` | `100` | Dimensione massima per file caricato |
| `OFFICE_PREVIEW` | `true` | Anteprima di PowerPoint e Word con LibreOffice |
| `OFFICE_PREVIEW_TIMEOUT` | `120` | Secondi massimi per una conversione |
| `SEED_SAMPLE_DOCS` | `false` | Al primo avvio, se `docs/` è vuota, copia la guida d'esempio |
| `AUTH_DEV_MODE` | `false` | Login simulato senza Keycloak. **Solo sviluppo** |

### Controllo password

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `SECRETS_SCAN` | `true` | Attiva il controllo delle password nei documenti |
| `SECRETS_POLICY` | `warn` | `warn`: salva ma avvisa e in modifica chiede conferma; `block`: rifiuta salvataggi e caricamenti che contengono password (i falsi positivi li sblocca un amministratore) |
| `SECRETS_RESCAN_SECONDS` | `30` | Ogni quanto, al massimo, si ricontrollano i file cambiati |

### Assistente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `ASSISTANT_ENABLED` | `true` | `false` nasconde pulsante e pannello |
| `ASSISTANT_NAME` | `AIla` | Nome mostrato nell'interfaccia |
| `ASSISTANT_SUGGESTIONS` | vuoto | Domande d'esempio separate da `\|` |
| `ASSISTANT_LLM` | `anthropic` se c'è `ANTHROPIC_API_KEY`, altrimenti `none` | `none`, `anthropic`, `openai` (qualsiasi API compatibile: OpenAI, Azure, Ollama, vLLM, LM Studio) |
| `ANTHROPIC_API_KEY` / `ASSISTANT_API_KEY` | vuoto | Chiave del provider |
| `ASSISTANT_MODEL` | `claude-haiku-5-5` con Anthropic | Obbligatorio con `openai` |
| `ASSISTANT_BASE_URL` | endpoint del provider | Es. `http://ollama:11434/v1` |
| `ASSISTANT_MAX_SOURCES` | `5` | Documenti proposti per risposta |
| `ASSISTANT_RATE_PER_MINUTE` | `20` | Domande al minuto per utente |
| `ASSISTANT_TIMEOUT` | `60` | Secondi di attesa per l'LLM |
| `ASSISTANT_MAX_TOKENS` | `900` | Lunghezza massima della risposta |
| `ASSISTANT_MAX_QUESTION` | `1000` | Caratteri massimi di una domanda |
| `ASSISTANT_RESCAN_SECONDS` | `5` | Ogni quanto, al massimo, si controlla se i file sono cambiati |

### Plugin

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `PLUGINS` | `all` | `all` oppure elenco tra `drawio`, `tables`, `macros` |
| `DRAWIO_EDITOR_URL` | `https://embed.diagrams.net` | Editor draw.io incorporato (il browser degli utenti deve raggiungerlo). Per non dipendere da Internet: `docker run -p 8080:8080 jgraph/drawio` e il suo URL. Vuoto = diagrammi in sola visualizzazione |
| `EMBED_ALLOWED_HOSTS` | Figma, Miro, Google Docs/Drive, SharePoint/OneDrive, Power BI, YouTube, Vimeo, Loom, diagrams.net, Lucid, Atlassian | Siti ammessi nella macro `embed`; `*.dominio` include i sottodomini |

### Metriche

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `METRICS_ENABLED` | `true` | Espone `GET /metrics` in formato Prometheus |
| `METRICS_TOKEN` | vuoto | Se impostato, `/metrics` richiede `Authorization: Bearer <token>`. Consigliato quando l'app è raggiungibile da Internet |

---

## Configurare Keycloak

Nel realm crea un client OpenID Connect:

- *Client authentication* attiva (client confidenziale) e *Standard flow* attivo; PKCE `S256` consigliato.
- **Direct access grants** attivo: serve alla pagina di login dell'app (`LOGIN_MODE=form`, il default). Senza, la pagina lo segnala e propone l'accesso dalla pagina di Keycloak.
- Nel realm: *Realm settings → Security defenses → Brute force detection* attiva. Con la pagina di login dell'app è Keycloak a bloccare i tentativi ripetuti sulle password.
- **Valid redirect URIs**: `https://docs.azienda.it/auth/callback`
- **Valid post logout redirect URIs**: `https://docs.azienda.it/*`
- I ruoli: ruoli realm (es. `ailadoc-admin`, `ailadoc-editor`, `ailadoc-viewer`) oppure ruoli del client (il ruolo `editor` del client `ailadoc` viene letto sia come `editor` sia come `ailadoc:editor`).
- Facoltativo: un mapper *Group Membership* con claim `groups`, per usare i gruppi Keycloak come ruoli.

Alcuni casi passano comunque dalla pagina di Keycloak, perché richiedono un'interazione che solo Keycloak gestisce: utenti con un'*azione richiesta* (password temporanea da cambiare, email da verificare, OTP da configurare), il reset della password e i provider esterni. L'app li riconosce e propone «Continua» con il nome utente già compilato. Per renderli coerenti con l'app conviene un tema di login Keycloak con gli stessi colori e lo stesso logo.

---

## Avvio

### Prova veloce, senza Keycloak

```bash
python3 -m venv .venv && source .venv/bin/activate      # Python 3.10+
pip install -r requirements.txt
python docker/fetch_vendor.py                           # mermaid, KaTeX, visualizzatore draw.io in app/static/vendor
AUTH_DEV_MODE=true SEED_SAMPLE_DOCS=true DATA_DIR=./data uvicorn app.main:app --reload
```

Su http://localhost:8000 compare un login simulato con utenti amministratore, editor, lettore e senza ruoli.

### Docker Compose

```bash
cp .env.example .env      # compila almeno le variabili obbligatorie
docker compose up -d --build
```

I dati finiscono in `./data`. Su un server Linux il container gira come utente `1000`: rendi la cartella scrivibile con `sudo chown -R 1000:1000 data` (con Docker Desktop non serve). Dietro un reverse proxy basta inoltrare a `:8000`; gli header `X-Forwarded-*` sono già accettati.

### Kubernetes (Helm)

Il chart è in [`charts/ailadoc`](charts/ailadoc/README.md). Le **stringhe di connessione e le credenziali** (Keycloak, database, endpoint e chiave del modello, `SECRET_KEY`) finiscono in un **Secret**; il resto in una ConfigMap.

```bash
docker build -f docker/Dockerfile -t meticulo/ailadoc:0.1.0 . && docker push meticulo/ailadoc:0.1.0
helm upgrade --install docs ./charts/ailadoc -n docs --create-namespace -f my-values.yaml
```

Valori minimi: `image.repository`, `keycloak.url`, `keycloak.clientSecret` e l'host dell'ingress. In alternativa a `keycloak.*` puoi fornire un Secret già esistente con `secrets.existingSecret` (chiavi elencate nel README del chart).

L'immagine si costruisce da **`docker/Dockerfile`** con la **radice del progetto come contesto** (copia `app/`, `sample-docs/` e `requirements.txt`); le esclusioni dal contesto sono in `docker/Dockerfile.dockerignore`. Serve BuildKit, attivo di default da Docker 23. Il workflow `.github/workflows/docker-publish.yml` fa lo stesso a ogni tag e pubblica `meticulo/ailadoc:<tag>` su Docker Hub.

Immagine più leggera, senza LibreOffice (circa 400 MB in meno, niente anteprima di PowerPoint e Word):

```bash
docker build -f docker/Dockerfile --build-arg OFFICE_PREVIEW=false -t meticulo/ailadoc:light .
```

---

## Monitoraggio (Prometheus)

`GET /metrics` espone le metriche in formato Prometheus. Non richiede il login: si protegge con `METRICS_TOKEN` (Bearer) oppure lasciandolo raggiungibile solo dalla rete interna.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: ailadoc
    metrics_path: /metrics
    authorization:
      credentials: "<METRICS_TOKEN>"      # ometti se il token è vuoto
    static_configs:
      - targets: ["ailadoc:8000"]
```

Con Kubernetes il chart può creare un `ServiceMonitor` (vedi il [README del chart](charts/ailadoc/README.md#metriche-prometheus)).

| Metrica | Tipo | Etichette | Cosa misura |
|---------|------|-----------|-------------|
| `ailadoc_http_requests_total` | counter | `method`, `route`, `status` | Richieste completate |
| `ailadoc_http_request_duration_seconds` | histogram | `method`, `route` | Tempo di risposta, fino all'ultimo byte (i download grandi includono il trasferimento) |
| `ailadoc_http_requests_in_progress` | gauge | `method` | Richieste in corso |
| `ailadoc_assistant_answer_duration_seconds` | histogram | `mode` (`ai`, `search`) | Tempo per rispondere a una domanda ad AIla |
| `ailadoc_assistant_no_results_total` | counter | | Domande senza nessun documento trovato (lacune della documentazione) |
| `ailadoc_assistant_rate_limited_total` | counter | | Domande rifiutate per il limite al minuto |
| `ailadoc_llm_request_duration_seconds` | histogram | `provider`, `outcome` (`ok`, `error`) | Durata delle chiamate all'LLM |
| `ailadoc_office_conversion_duration_seconds` | histogram | `outcome` (`ok`, `error`, `timeout`) | Conversioni PowerPoint/Word → PDF con LibreOffice |
| `ailadoc_office_preview_cache_total` | counter | `result` (`hit`, `miss`) | Anteprime servite dalla cache o da convertire |
| `ailadoc_logins_total` | counter | `method` (`form`, `sso`, `dev`), `result` | Accessi riusciti e falliti (`success`, `credentials`, `locked`, `rate`, `unavailable`, …) |
| `ailadoc_keycloak_request_duration_seconds` | histogram | `operation` (`password_login`, `code_exchange`), `outcome` | Tempo di risposta di Keycloak; `error` = Keycloak non raggiungibile o client mal configurato (una password errata è `ok`) |
| `ailadoc_background_task_duration_seconds` | histogram | `task` (`assistant_index`, `secret_scan`) | Durata delle scansioni dei documenti |
| `ailadoc_background_task_last_run_timestamp_seconds` | gauge | `task` | Fine dell'ultima scansione |
| `ailadoc_assistant_index_documents` / `_passages` | gauge | | Documenti e brani nell'indice di AIla |
| `ailadoc_secret_findings` / `ailadoc_secret_files` | gauge | | Password trovate nei documenti e file coinvolti (escluse quelle ignorate) |
| `ailadoc_app_info` | info | `llm_provider`, `login_mode`, `office_preview`, `secrets_scan` | Configurazione dell'istanza |
| `process_*`, `python_*` | | | CPU, memoria, file aperti, garbage collector |

`route` è il modello della route (`/d/{rel:path}`, `/api/assistant`…), mai il percorso reale: i nomi dei documenti non finiscono nelle metriche e il numero di serie resta basso. I percorsi inesistenti sono raggruppati in `<unmatched>`, i file statici in `/static`.

Query utili:

```promql
# richieste al secondo per route (media su 5 minuti)
sum by (route) (rate(ailadoc_http_requests_total[5m]))
# tempo di risposta al 95° percentile per route
histogram_quantile(0.95, sum by (le, route) (rate(ailadoc_http_request_duration_seconds_bucket[5m])))
# percentuale di errori 5xx
sum(rate(ailadoc_http_requests_total{status=~"5.."}[5m])) / sum(rate(ailadoc_http_requests_total[5m]))
# latenza mediana dell'LLM e quota di chiamate fallite
histogram_quantile(0.5, sum by (le) (rate(ailadoc_llm_request_duration_seconds_bucket[15m])))
sum(rate(ailadoc_llm_request_duration_seconds_count{outcome="error"}[15m])) / sum(rate(ailadoc_llm_request_duration_seconds_count[15m]))
# domande ad AIla all'ora e quante senza risultati
sum(increase(ailadoc_assistant_answer_duration_seconds_count[1h]))
increase(ailadoc_assistant_no_results_total[1h])
# accessi falliti per esito nell'ultima ora
sum by (result) (increase(ailadoc_logins_total{result!="success"}[1h]))
```

Le metriche sono per processo: l'immagine avvia un solo worker uvicorn; con più repliche Prometheus interroga ogni pod.

---

## Loghi

Due file in **`data/branding/`**, oppure caricali da *Amministrazione → Loghi* (con Helm anche da una ConfigMap):

| File | Dove compare | Formato consigliato |
|------|--------------|---------------------|
| `app-logo.svg` (o `.png`) | pagina di accesso (72 px), in alto a sinistra (alto 32 px), icona del browser | **SVG** quadrato; in alternativa PNG trasparente **512×512** |
| `company-logo.svg` (o `.png`) | sotto il riquadro di accesso, in fondo al menu, nella pagina di accesso negato | **SVG** orizzontale; in alternativa PNG trasparente circa **600×160** |

Sono accettati anche `.webp` e `.jpg`; se ci sono più formati vince l'SVG. Usa uno sfondo trasparente: il menu cambia colore tra tema chiaro e scuro.

---

## Backup

Basta salvare `data/` (o fare uno snapshot del volume): documenti, loghi e database dei permessi. La cache si ricostruisce da sola.

## Sviluppo

```bash
pip install -r requirements.txt pytest
python -m pytest tests
```

I test usano documenti di prova propri (`tests/fixtures/docs`), indipendenti dalla guida d'esempio. Per provare con un Keycloak vero in locale, la cartella `keycloak/` (esclusa da git) contiene un compose di prova: vedi `keycloak/README.md`.

```
app/
├── main.py         route: documenti, editor, creazione, upload, admin, assistente
├── auth.py         OIDC (Authorization Code + PKCE), verifica JWT, estrazione ruoli
├── permissions.py  calcolo dei permessi
├── creator.py      creazione rapida di pagine, cartelle e strutture
├── secretscan.py   controllo password e credenziali nei documenti
├── db.py           modelli: ruoli app, gruppi, restrizioni, ACL
├── storage.py      filesystem, albero, tipi di file
├── render.py       Markdown → HTML sanificato
├── preview.py      LibreOffice → PDF, Excel/CSV → tabella
├── assistant.py    assistente AIla: estrazione testo, indice, LLM opzionale
├── plugins/        macro delle pagine: drawio.py, tables.py (+ tabledata.py, charts.py), macros.py
├── icons.py        icone SVG per tipo
├── templates/      pagine Jinja2
└── static/         CSS, JS, logo predefinito
charts/ailadoc/     chart Helm
docker/             Dockerfile e relative esclusioni (contesto di build = radice)
sample-docs/        guida d'esempio (copiata con SEED_SAMPLE_DOCS=true)
tests/              test e documenti di prova
```
