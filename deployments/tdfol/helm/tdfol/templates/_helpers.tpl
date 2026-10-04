{{/*
Expand the name of the chart.
*/}}
{{- define "tdfol.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "tdfol.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "tdfol.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "tdfol.labels" -}}
helm.sh/chart: {{ include "tdfol.chart" . }}
{{ include "tdfol.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "tdfol.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tdfol.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "tdfol.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "tdfol.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the proper image name
*/}}
{{- define "tdfol.image" -}}
{{- $registryName := .Values.image.registry -}}
{{- $repositoryName := .Values.image.repository -}}
{{- $tag := .Values.image.tag | toString -}}
{{- if .Values.global }}
    {{- if .Values.global.imageRegistry }}
        {{- $registryName = .Values.global.imageRegistry -}}
    {{- end -}}
{{- end -}}
{{- if $registryName }}
{{- printf "%s/%s:%s" $registryName $repositoryName $tag -}}
{{- else }}
{{- printf "%s:%s" $repositoryName $tag -}}
{{- end }}
{{- end }}

{{/*
Return the proper storage class
*/}}
{{- define "tdfol.storageClass" -}}
{{- if .Values.global }}
    {{- if .Values.global.storageClass }}
        {{- .Values.global.storageClass -}}
    {{- else }}
        {{- .Values.persistence.storageClass -}}
    {{- end -}}
{{- else }}
    {{- .Values.persistence.storageClass -}}
{{- end }}
{{- end }}

{{/*
Redis fullname
*/}}
{{- define "tdfol.redis.fullname" -}}
{{- printf "%s-redis" (include "tdfol.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
