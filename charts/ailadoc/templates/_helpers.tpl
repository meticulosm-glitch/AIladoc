{{- define "ailadoc.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ailadoc.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "ailadoc.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "ailadoc.labels" -}}
helm.sh/chart: {{ include "ailadoc.chart" . }}
{{ include "ailadoc.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "ailadoc.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ailadoc.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "ailadoc.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "ailadoc.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "ailadoc.secretName" -}}
{{- default (include "ailadoc.fullname" .) .Values.secrets.existingSecret }}
{{- end }}

{{- define "ailadoc.claimName" -}}
{{- default (printf "%s-data" (include "ailadoc.fullname" .)) .Values.persistence.existingClaim }}
{{- end }}

{{/* URL pubblico: app.baseUrl oppure il primo host dell'ingress */}}
{{- define "ailadoc.baseUrl" -}}
{{- if .Values.app.baseUrl }}
{{- .Values.app.baseUrl | trimSuffix "/" }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- $host := (first .Values.ingress.hosts).host }}
{{- $scheme := ternary "https" "http" (gt (len .Values.ingress.tls) 0) }}
{{- printf "%s://%s" $scheme $host }}
{{- else }}
{{- fail "Imposta app.baseUrl (URL pubblico dell'app) oppure abilita ingress con almeno un host." }}
{{- end }}
{{- end }}

{{- define "ailadoc.caMounted" -}}
{{- if or .Values.keycloak.caBundle.configMapName .Values.keycloak.caBundle.secretName }}true{{ end }}
{{- end }}

{{/* "true" se il volume dati è ReadWriteOnce: due pod non possono usarlo insieme */}}
{{- define "ailadoc.rwo" -}}
{{- if and .Values.persistence.enabled (has "ReadWriteOnce" .Values.persistence.accessModes) }}true{{ end }}
{{- end }}

{{- define "ailadoc.validateReplicas" -}}
{{- if and (gt (int .Values.replicaCount) 1) (include "ailadoc.rwo" .) }}
{{- fail "replicaCount > 1 richiede un volume ReadWriteMany (persistence.accessModes) e databaseUrl verso Postgres: con SQLite su ReadWriteOnce usa 1 replica." }}
{{- end }}
{{- end }}

{{/* "true" se le credenziali arrivano da Vault (External Secrets Operator) */}}
{{- define "ailadoc.vaultEnabled" -}}
{{- if or .Values.vault.address .Values.vault.existingStore.name }}true{{ end }}
{{- end }}

{{- define "ailadoc.vaultSecretName" -}}
{{- printf "%s-vault" (include "ailadoc.fullname" .) }}
{{- end }}

{{/* Secret con METRICS_TOKEN (per il ServiceMonitor), vuoto se non c'è un token */}}
{{- define "ailadoc.metricsTokenSecret" -}}
{{- $inVault := hasKey .Values.vault.keys "METRICS_TOKEN" -}}
{{- if and (include "ailadoc.vaultEnabled" .) $inVault }}
{{- include "ailadoc.vaultSecretName" . }}
{{- else if .Values.secrets.existingSecret }}
{{- if .Values.metrics.existingSecretHasToken }}{{ .Values.secrets.existingSecret }}{{ end }}
{{- else if or .Values.metrics.token $inVault }}
{{- include "ailadoc.fullname" . }}
{{- end }}
{{- end }}

{{/* Utenti locali come JSON nome -> ruoli; vuoto se disattivati */}}
{{- define "ailadoc.localUsersJson" -}}
{{- if .Values.localUsers.enabled }}
{{- $out := dict -}}
{{- range .Values.localUsers.users }}
{{- $name := "" -}}
{{- $roles := $.Values.localUsers.defaultRoles -}}
{{- if kindIs "string" . }}
{{- $name = . -}}
{{- else }}
{{- $name = required "localUsers.users[].name è obbligatorio" .name -}}
{{- if hasKey . "roles" }}{{ $roles = .roles }}{{ end -}}
{{- end }}
{{- if not (regexMatch "^[a-z0-9][a-z0-9._-]{0,63}$" (toString $name)) }}
{{- fail (printf "localUsers: nome utente %q non valido (lettere minuscole, cifre, '.', '_' o '-', max 64)" $name) }}
{{- end }}
{{- $_ := set $out (toString $name) $roles -}}
{{- end }}
{{- if $out }}{{ toJson $out }}{{ end }}
{{- end }}
{{- end }}

{{- define "ailadoc.localUsersSecretName" -}}
{{- printf "%s-local-users" (include "ailadoc.fullname" .) }}
{{- end }}
