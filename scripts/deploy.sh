#!/usr/bin/env bash
# =============================================================================
# elastic-autonomous-sre - end-to-end deploy
#
# 1. Verifies the ECK operator is installed (offers to install if missing).
# 2. Builds the three application images via OpenShift binary builds.
# 3. helm installs the chart (Elastic Stack + demo workloads).
# 4. Waits for Elasticsearch to reach green health and apps to roll out.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}/.."
RELEASE="${RELEASE:-easre}"
NAMESPACE="${NAMESPACE:-$(oc project -q)}"
STACK_NAME="${STACK_NAME:-elastic-stack}"

echo "=============================================="
echo "  elastic-autonomous-sre - Deploy"
echo "=============================================="
echo "  Release:   ${RELEASE}"
echo "  Namespace: ${NAMESPACE}"
echo "  Stack:     ${STACK_NAME}"
echo ""

# --- Prereq: ECK CRDs ---
if ! oc get crd elasticsearches.elasticsearch.k8s.elastic.co >/dev/null 2>&1; then
  echo "ECK CRDs not found. Installing the ECK operator..."
  echo "  (requires cluster-admin)"
  oc apply -f "${ROOT_DIR}/manifests/eck-operator.yaml"
  printf "Waiting for Elasticsearch CRD"
  until oc get crd elasticsearches.elasticsearch.k8s.elastic.co >/dev/null 2>&1; do
    printf '.'
    sleep 5
  done
  echo " ready."
fi

# --- Build images ---
build_and_push() {
  local app="$1"
  echo "=== Building ${app} ==="
  if ! oc get bc/"${app}" -n "${NAMESPACE}" >/dev/null 2>&1; then
    oc new-build --name="${app}" --binary --strategy=docker \
      --namespace="${NAMESPACE}" -l app="${app}"
  fi
  oc start-build "${app}" --from-dir="${ROOT_DIR}/${app}" \
    --namespace="${NAMESPACE}" --follow
}

for app in payment-service payment-loadgen remediation-agent; do
  build_and_push "${app}"
done

# --- helm install ---
echo ""
echo "=== helm install ==="
helm upgrade --install "${RELEASE}" "${ROOT_DIR}/chart" --namespace "${NAMESPACE}"

# --- Wait for Elasticsearch ---
echo ""
echo "=== Waiting for Elasticsearch to reach green health (3-5 min) ==="
oc wait --for=jsonpath='{.status.health}'=green \
  elasticsearch/"${STACK_NAME}" -n "${NAMESPACE}" --timeout=600s || \
  echo "WARNING: Elasticsearch did not reach green within timeout — continuing."

# --- Wait for app rollouts ---
echo ""
echo "=== App rollouts ==="
for d in payment-service payment-loadgen remediation-agent; do
  oc rollout status deployment/"${d}" -n "${NAMESPACE}" --timeout=120s || true
done

# --- Print Kibana access ---
echo ""
KIBANA_HOST=$(oc get route kibana -n "${NAMESPACE}" -o jsonpath='{.spec.host}' 2>/dev/null || true)
KIBANA_PASS=$(oc get secret "${STACK_NAME}-es-elastic-user" -n "${NAMESPACE}" \
  -o jsonpath='{.data.elastic}' 2>/dev/null | base64 -d || true)
if [[ -n "${KIBANA_HOST}" ]]; then
  echo "=============================================="
  echo "  Kibana ready"
  echo "=============================================="
  echo "  URL:  https://${KIBANA_HOST}"
  echo "  user: elastic"
  echo "  pass: ${KIBANA_PASS}"
  echo ""
fi

echo "Done. See README step 5+ to configure the AI connector and workflow."
