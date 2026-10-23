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
