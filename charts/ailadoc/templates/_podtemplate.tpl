{{/* Pod template condiviso da Deployment e Rollout (Argo Rollouts) */}}
{{- define "ailadoc.podTemplate" -}}
metadata:
  annotations:
    checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    {{- if not .Values.secrets.existingSecret }}
    checksum/secret-values: {{ list .Values.keycloak .Values.assistant.baseUrl .Values.assistant.apiKey .Values.secrets .Values.metrics.token | toJson | sha256sum }}
    {{- end }}
    {{- if and .Values.metrics.enabled .Values.metrics.scrapeAnnotations }}
    prometheus.io/scrape: "true"
    prometheus.io/port: "8000"
    prometheus.io/path: /metrics
    {{- end }}
    {{- with .Values.podAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  labels:
    {{- include "ailadoc.selectorLabels" . | nindent 4 }}
    {{- with .Values.podLabels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- with .Values.imagePullSecrets }}
  imagePullSecrets:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  serviceAccountName: {{ include "ailadoc.serviceAccountName" . }}
  automountServiceAccountToken: {{ .Values.serviceAccount.automount }}
  securityContext:
    {{- toYaml .Values.podSecurityContext | nindent 4 }}
  containers:
    - name: ailadoc
      image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
      imagePullPolicy: {{ .Values.image.pullPolicy }}
      securityContext:
        {{- toYaml .Values.securityContext | nindent 8 }}
      ports:
        - name: http
          containerPort: 8000
          protocol: TCP
      envFrom:
        - configMapRef:
            name: {{ include "ailadoc.fullname" . }}
        - secretRef:
            name: {{ include "ailadoc.secretName" . }}
        {{- if include "ailadoc.vaultEnabled" . }}
        # credenziali da Vault (ExternalSecret): elencate per ultime, hanno la precedenza
        - secretRef:
            name: {{ include "ailadoc.vaultSecretName" . }}
        {{- end }}
      env:
        - name: DATA_DIR
          value: /data
        - name: HOME
          value: /tmp
        - name: TMPDIR
          value: /tmp
        {{- with .Values.extraEnv }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      startupProbe:
        httpGet:
          path: /healthz
          port: http
        periodSeconds: {{ .Values.probes.startup.periodSeconds }}
        failureThreshold: {{ .Values.probes.startup.failureThreshold }}
      readinessProbe:
        httpGet:
          path: /healthz
          port: http
        periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
      livenessProbe:
        httpGet:
          path: /healthz
          port: http
        periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
        failureThreshold: {{ .Values.probes.liveness.failureThreshold }}
      resources:
        {{- toYaml .Values.resources | nindent 8 }}
      volumeMounts:
        - name: data
          mountPath: /data
        - name: tmp
          mountPath: /tmp
        {{- if .Values.branding.configMapName }}
        - name: branding
          mountPath: /data/branding
          readOnly: true
        {{- end }}
        {{- if include "ailadoc.caMounted" . }}
        - name: keycloak-ca
          mountPath: /etc/ailadoc/ca
          readOnly: true
        {{- end }}
        {{- if include "ailadoc.localUsersJson" . }}
        - name: local-users
          mountPath: /etc/ailadoc/local-users
          readOnly: true
        {{- end }}
        {{- with .Values.extraVolumeMounts }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
  volumes:
    - name: data
      {{- if .Values.persistence.enabled }}
      persistentVolumeClaim:
        claimName: {{ include "ailadoc.claimName" . }}
      {{- else }}
      emptyDir: {}
      {{- end }}
    - name: tmp
      emptyDir:
        sizeLimit: {{ .Values.tmpVolume.sizeLimit }}
    {{- if .Values.branding.configMapName }}
    - name: branding
      configMap:
        name: {{ .Values.branding.configMapName }}
    {{- end }}
    {{- if .Values.keycloak.caBundle.configMapName }}
    - name: keycloak-ca
      configMap:
        name: {{ .Values.keycloak.caBundle.configMapName }}
    {{- else if .Values.keycloak.caBundle.secretName }}
    - name: keycloak-ca
      secret:
        secretName: {{ .Values.keycloak.caBundle.secretName }}
    {{- end }}
    {{- if include "ailadoc.localUsersJson" . }}
    # password degli utenti locali, generate dal Job (un file per utente)
    - name: local-users
      secret:
        secretName: {{ include "ailadoc.localUsersSecretName" . }}
        optional: true
        defaultMode: 0440
    {{- end }}
    {{- with .Values.extraVolumes }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
  {{- with .Values.nodeSelector }}
  nodeSelector:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.affinity }}
  affinity:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  {{- with .Values.tolerations }}
  tolerations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
