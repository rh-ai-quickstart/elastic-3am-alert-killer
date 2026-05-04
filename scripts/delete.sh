#!/usr/bin/env bash
# =============================================================================
# elastic-autonomous-sre - tear down
# =============================================================================
set -euo pipefail

RELEASE="${RELEASE:-easre}"
NAMESPACE="${NAMESPACE:-$(oc project -q)}"

echo "Uninstalling Helm release '${RELEASE}' from ${NAMESPACE}..."
helm uninstall "${RELEASE}" --namespace "${NAMESPACE}" || true

echo "Cleaning up BuildConfigs and ImageStreams..."
oc delete bc payment-service payment-loadgen remediation-agent \
  -n "${NAMESPACE}" --ignore-not-found
oc delete is payment-service payment-loadgen remediation-agent \
  -n "${NAMESPACE}" --ignore-not-found

echo "Done. The OTEL secret (if you created one manually) is left in place."
