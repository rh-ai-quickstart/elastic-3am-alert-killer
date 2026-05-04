{{/*
Resolve the deployment namespace. Prefers explicit namespaceOverride, falls
back to the Helm release namespace.
*/}}
{{- define "easre.namespace" -}}
{{- default .Release.Namespace .Values.namespaceOverride -}}
{{- end -}}

{{/*
ECK stack name (used as Elasticsearch + Kibana + APM Server CR name).
*/}}
{{- define "easre.stackName" -}}
{{- default "elastic-stack" .Values.eck.naming.stackName -}}
{{- end -}}

{{/*
ECK Elastic Agent CR name.
*/}}
{{- define "easre.agentName" -}}
{{- default "elastic-agent" .Values.eck.naming.agentName -}}
{{- end -}}

{{/*
APM Server in-cluster URL. Defaults to plaintext HTTP since httpTLS is off
in the chart defaults; flips to HTTPS when the user re-enables TLS.
*/}}
{{- define "easre.apmEndpoint" -}}
{{- $scheme := "http" -}}
{{- if .Values.eck.apm.httpTLS -}}{{- $scheme = "https" -}}{{- end -}}
{{ $scheme }}://{{ include "easre.stackName" . }}-apm-http:8200
{{- end -}}

{{/*
Build an internal-registry image reference for an app component when the
user hasn't supplied an explicit repository.
Usage: include "easre.image" (dict "image" .Values.paymentService.image "ns" $ns "name" "payment-service")
*/}}
{{- define "easre.image" -}}
{{- $img := .image -}}
{{- if $img.repository -}}
{{ $img.repository }}:{{ $img.tag | default "latest" }}
{{- else -}}
image-registry.openshift-image-registry.svc:5000/{{ .ns }}/{{ .name }}:{{ $img.tag | default "latest" }}
{{- end -}}
{{- end -}}

{{/*
Standard labels shared across all resources.
*/}}
{{- define "easre.labels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
app.kubernetes.io/part-of: elastic-autonomous-sre
app: {{ .name }}
{{- end -}}
