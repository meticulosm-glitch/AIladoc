# Chart Helm `ailadoc`

Deploy di AIladoc su Kubernetes con Keycloak **esterno**.

## 1. Immagine

Il chart non costruisce l'immagine. Il workflow `.github/workflows/docker-publish.yml` la pubblica su Docker Hub come `meticulo/ailadoc:<tag>` a ogni tag git; a mano, dalla radice del progetto:

```bash
docker build -f docker/Dockerfile -t meticulo/ailadoc:0.1.0 .
docker push meticulo/ailadoc:0.1.0
# cluster su un'architettura diversa (es. Mac ARM -> nodi amd64):
docker buildx build -f docker/Dockerfile --platform linux/amd64 -t meticulo/ailadoc:0.1.0 --push .
```

## 2. Client Keycloak

Nel realm crea un client OpenID Connect:

- *Client authentication* attiva (confidenziale), *Standard flow* attivo, PKCE `S256`.
- **Direct access grants** attivo, per la pagina di login dell'app (`login.mode: form`, il default). Nel realm attiva anche la *Brute force detection*.
- **Valid redirect URIs**: `https://docs.example.com/auth/callback`
- **Valid post logout redirect URIs**: `https://docs.example.com/*`
- Ruoli realm (o del client) per amministratori, editor e lettori, per esempio `ailadoc-admin`, `ailadoc-editor`, `ailadoc-viewer`.
- Facoltativo: un mapper *Group Membership* con claim `groups`, per usare i gruppi Keycloak.

## 3. Valori

`my-values.yaml` minimo:

```yaml
image:
  repository: meticulo/ailadoc
  tag: "0.1.0"

app:
  companyName: Meticulo

keycloak:
  url: https://sso.example.com
  realm: ailadoc
  clientId: ailadoc
  clientSecret: "..."            # finisce nel Secret; oppure secrets.existingSecret, vedi sotto

ingress:
  className: nginx
  hosts:
    - host: docs.example.com
      paths: [{ path: /, pathType: Prefix }]
  tls:
    - secretName: docs-example-com-tls
      hosts: [docs.example.com]
```

```bash
helm upgrade --install docs ./charts/ailadoc -n docs --create-namespace -f my-values.yaml
helm test docs -n docs
```

`BASE_URL` viene ricavato dal primo host dell'ingress: con TLS è `https://` e i cookie vengono marcati `Secure`. Se l'app è esposta diversamente, imposta `app.baseUrl`.

### Secret: stringhe di connessione e credenziali

Le stringhe di connessione e le credenziali **non** finiscono nella ConfigMap ma in un Secret, letto dal pod con `envFrom`:

| Chiave | Da quale valore | |
|--------|-----------------|---|
| `SECRET_KEY` | `secrets.secretKey` | generata al primo install se vuota, poi **mantenuta** negli upgrade |
| `KEYCLOAK_PUBLIC_URL` | `keycloak.url` | obbligatoria |
| `KEYCLOAK_INTERNAL_URL` | `keycloak.internalUrl` | facoltativa |
| `KEYCLOAK_REALM` | `keycloak.realm` | obbligatoria |
| `OIDC_CLIENT_ID` | `keycloak.clientId` | obbligatoria |
| `OIDC_CLIENT_SECRET` | `keycloak.clientSecret` | se il client è confidenziale |
| `DATABASE_URL` | `secrets.databaseUrl` | facoltativa (Postgres) |
| `ASSISTANT_BASE_URL` | `assistant.baseUrl` | facoltativa |
| `ASSISTANT_API_KEY` | `assistant.apiKey` | facoltativa |
| `METRICS_TOKEN` | `metrics.token` | facoltativa: token Bearer per `/metrics` |

Il Secret creato dal chart ha `helm.sh/resource-policy: keep`, così `helm uninstall` non perde la chiave di sessione.

Per non mettere credenziali nei values, crea tu il Secret (a mano, Sealed Secrets, External Secrets, Vault…) con le stesse chiavi e indicalo al chart:

```bash
kubectl -n docs create secret generic ailadoc-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -base64 48)" \
  --from-literal=KEYCLOAK_PUBLIC_URL=https://sso.example.com \
  --from-literal=KEYCLOAK_REALM=ailadoc \
  --from-literal=OIDC_CLIENT_ID=ailadoc \
  --from-literal=OIDC_CLIENT_SECRET='...'
```
```yaml
secrets:
  existingSecret: ailadoc-secrets
```

Con `secrets.existingSecret` il chart non crea il proprio Secret e ignora `keycloak.url/internalUrl/realm/clientId/clientSecret`, `assistant.baseUrl/apiKey`, `secrets.secretKey/databaseUrl`, `metrics.token`.

### Keycloak con CA interna

```bash
kubectl -n docs create configmap corp-ca --from-file=ca.crt=./corp-root-ca.pem
```
```yaml
keycloak:
  caBundle:
    configMapName: corp-ca     # oppure secretName
    key: ca.crt
```

### Keycloak raggiungibile dal pod a un indirizzo diverso

Se il pod raggiunge Keycloak su un servizio interno (`http://keycloak.keycloak.svc:8080`) mentre il browser usa `https://sso.example.com`:

```yaml
keycloak:
  url: https://sso.example.com
  internalUrl: http://keycloak.keycloak.svc:8080
```

In Keycloak serve allora `KC_HOSTNAME=https://sso.example.com` e `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`, così l'issuer dei token resta quello pubblico.

## Loghi

Due possibilità:

1. **Dalla UI** (Amministrazione → Loghi): i file finiscono nel volume, in `/data/branding`.
2. **Da una ConfigMap**, gestita insieme al deploy:
   ```bash
   kubectl -n docs create configmap ailadoc-logos \
     --from-file=app-logo.svg --from-file=company-logo.svg
   ```
   ```yaml
   branding:
     configMapName: ailadoc-logos
   ```
   In questo caso la cartella è in sola lettura e la UI mostra un avviso se provi a cambiarli. Una ConfigMap ha un limite di 1 MiB: per i PNG usa `--from-file` e verrà salvato come `binaryData`.

Formati: `app-logo` quadrato (SVG o PNG 512×512), `company-logo` orizzontale (SVG o PNG circa 600×160), sfondo trasparente.

## Documenti

Stanno nel volume (`/data/docs`). Si gestiscono dalla UI oppure si copiano:

```bash
POD=$(kubectl -n docs get pod -l app.kubernetes.io/instance=docs -o jsonpath='{.items[0].metadata.name}')
kubectl -n docs cp ./mia-documentazione/. $POD:/data/docs/
```

## Persistenza e repliche

- Un solo PVC (`10Gi`, `ReadWriteOnce`) contiene documenti, loghi, cache delle anteprime e il database SQLite di ruoli, gruppi e permessi.
- La PVC ha `helm.sh/resource-policy: keep`: `helm uninstall` **non** cancella i documenti.
- Con `ReadWriteOnce` il chart forza **1 replica** e la strategia `Recreate`. Per più repliche servono un volume `ReadWriteMany` e `databaseUrl` verso Postgres (con `psycopg[binary]` aggiunto a `requirements.txt`); le sessioni sono cookie firmati, quindi non serve la sticky session.
- Backup: snapshot della PVC, oppure `kubectl cp $POD:/data ./backup`.

## Sicurezza del pod

Utente non-root `1000`, root filesystem in sola lettura (scrivibili solo `/data` e un `emptyDir` su `/tmp`), nessuna capability, `seccomp: RuntimeDefault`, token del service account non montato.

## Assistente AIla

```yaml
assistant:
  enabled: true
  llm: anthropic            # none (predefinito: solo ricerca, nessun dato esce) | anthropic | openai
  apiKey: sk-ant-...        # va nel Secret
  # model: claude-haiku-5-5
  # baseUrl: http://ollama.ai.svc:11434/v1   # con llm: openai (va nel Secret)
  suggestions: ["Come chiedo le ferie?", "Dove trovo il listino?"]
```

Con un LLM esterno il pod deve poter uscire verso il provider (controlla eventuali NetworkPolicy o proxy).

## Plugin

```yaml
plugins:
  enabled: [all]                                   # oppure [drawio, tables, macros]
  drawioEditorUrl: https://drawio.example.com      # istanza jgraph/drawio interna; "" = solo visualizzazione
  embedAllowedHosts: [www.figma.com, miro.com, "*.sharepoint.com"]
```

Il visualizzatore draw.io, KaTeX e mermaid sono già nell'immagine. Con `drawioEditorUrl` esterno (predefinito `https://embed.diagrams.net`) il browser degli utenti deve poter raggiungere quel sito; il diagramma passa dal browser all'iframe e torna ad AIladoc, non viene caricato su draw.io.

## Metriche Prometheus

Il pod espone `GET /metrics` sulla porta `http` (elenco delle metriche e query d'esempio nel [README principale](../../README.md#monitoraggio-prometheus)).

```yaml
metrics:
  enabled: true
  token: "un-token-lungo-e-casuale"     # va nel Secret come METRICS_TOKEN
  serviceMonitor:
    enabled: true                       # richiede le CRD di Prometheus Operator
    labels:
      release: kube-prometheus-stack    # quelle del serviceMonitorSelector del vostro Prometheus
```

L'ingress pubblica tutta l'app, `/metrics` compreso: con un ingress raggiungibile da Internet imposta `metrics.token`. Il ServiceMonitor lo legge dal Secret dell'app e lo invia come `Authorization: Bearer`. Con `secrets.existingSecret` aggiungi la chiave `METRICS_TOKEN` a quel Secret e imposta `metrics.existingSecretHasToken: true`.

Senza Prometheus Operator: `metrics.scrapeAnnotations: true` aggiunge al pod le annotazioni `prometheus.io/scrape|port|path` (non portano il token: usale con `metrics.token` vuoto e `/metrics` non esposto all'esterno).

## Valori principali

| Valore | Default | Descrizione |
|--------|---------|-------------|
| `image.repository` / `image.tag` | `meticulo/ailadoc` / appVersion | immagine (il tag deve esistere: è il tag git pubblicato dal workflow) |
| `keycloak.url` | **obbligatorio** (o `secrets.existingSecret`) | URL pubblico di Keycloak → Secret |
| `keycloak.internalUrl` | `""` | URL usato dal pod, se diverso → Secret |
| `keycloak.realm` / `clientId` / `clientSecret` | `ailadoc` / `ailadoc` / `""` | client OIDC → Secret |
| `keycloak.scopes` / `rolesExtraClaims` / `verifyTls` | | ConfigMap |
| `keycloak.caBundle.*` | vuoto | CA interna per Keycloak |
| `secrets.existingSecret` | `""` | Secret esistente con tutte le chiavi di connessione |
| `secrets.secretKey` / `secrets.databaseUrl` | generata / `""` | → Secret |
| `login.mode` / `ssoButton` / `otp` | `form` / `false` / `false` | pagina di login dell'app o di Keycloak (ConfigMap) |
| `login.passwordResetUrl` / `maxAttempts` | `""` / `10` | link «Password dimenticata?» e limite tentativi (ConfigMap) |
| `secretsScan.enabled` / `policy` / `rescanSeconds` | `true` / `warn` / `30` | controllo password nei documenti (ConfigMap) |
| `assistant.enabled` / `name` / `suggestions` | `true` / `AIla` / `[]` | ConfigMap |
| `assistant.llm` / `model` | `none` / `""` | ConfigMap |
| `assistant.baseUrl` / `apiKey` | `""` | → Secret |
| `plugins.enabled` / `drawioEditorUrl` / `embedAllowedHosts` | `[all]` / `https://embed.diagrams.net` / `[]` | plugin delle pagine (ConfigMap) |
| `metrics.enabled` / `token` | `true` / `""` | `/metrics` (ConfigMap) e token Bearer (→ Secret) |
| `metrics.serviceMonitor.enabled` / `interval` / `labels` | `false` / `30s` / `{}` | ServiceMonitor per Prometheus Operator |
| `metrics.scrapeAnnotations` | `false` | annotazioni `prometheus.io/*` sul pod |
| `app.adminRoles` / `editorRoles` / `viewerRoles` | `ailadoc-admin` / `-editor` / `-viewer` | ruoli Keycloak |
| `app.baseUrl` | dall'ingress | URL pubblico dell'app |
| `app.maxUploadMb` | `100` | allinealo all'annotazione `proxy-body-size` dell'ingress |
| `app.officePreview` | `true` | anteprima PowerPoint/Word (LibreOffice) |
| `app.seedSampleDocs` | `false` | copia la guida d'esempio se il volume è vuoto |
| `persistence.size` / `storageClass` / `existingClaim` | `10Gi` / default / `""` | volume dati |
| `branding.configMapName` | `""` | loghi da ConfigMap |
| `ingress.*` | nginx, `docs.example.com` | esposizione |
| `resources` | 100m / 256Mi, limite 1Gi | LibreOffice può chiedere memoria su file grandi |
| `extraEnv`, `extraVolumes`, `extraVolumeMounts` | `[]` | estensioni |
