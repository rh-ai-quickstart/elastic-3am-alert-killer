# =============================================================================
# elastic-autonomous-sre - demo Makefile
# =============================================================================
# Convenience targets for the full lifecycle of the quickstart. All targets
# operate on the current `oc project` unless NAMESPACE is overridden.
#
# Required tools: oc, helm. Optional: jq, mmdc (for diagram rendering).
# =============================================================================

SHELL          := /usr/bin/env bash
.SHELLFLAGS    := -eu -o pipefail -c
.DEFAULT_GOAL  := help

RELEASE        ?= easre
NAMESPACE      ?= $(shell oc project -q 2>/dev/null)
STACK_NAME     ?= elastic-stack
ELASTIC_API_KEY ?=

# Resolved at-call so `make help` works without a cluster
PAYMENT_ROUTE   = $(shell oc get route payment-service -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null)
AGENT_ROUTE     = $(shell oc get route remediation-agent -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null)
KIBANA_HOST     = $(shell oc get route kibana -n $(NAMESPACE) -o jsonpath='{.spec.host}' 2>/dev/null)
KIBANA_URL      = $(if $(KIBANA_HOST),https://$(KIBANA_HOST))
KIBANA_PASS     = $(shell oc get secret $(STACK_NAME)-es-elastic-user -n $(NAMESPACE) -o jsonpath='{.data.elastic}' 2>/dev/null | base64 -d)

# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo
	@echo "Vars: NAMESPACE=$(NAMESPACE)  RELEASE=$(RELEASE)  STACK_NAME=$(STACK_NAME)"

##@ Cluster prerequisites

.PHONY: eck-operator
eck-operator: ## Install the ECK operator via OLM (cluster-admin, one-time)
	oc apply -f manifests/eck-operator.yaml
	@echo "Waiting for Elasticsearch CRD..."
	@until oc get crd elasticsearches.elasticsearch.k8s.elastic.co >/dev/null 2>&1; do \
		printf '.'; sleep 5; \
	done
	@echo " ready."

.PHONY: eck-uninstall
eck-uninstall: ## Remove the ECK operator (cluster-admin)
	oc delete -f manifests/eck-operator.yaml --ignore-not-found

##@ Build & deploy

.PHONY: build
build: ## Build the three application images via OpenShift binary builds
	@for app in payment-service payment-loadgen remediation-agent; do \
		echo "=== Building $$app ==="; \
		oc get bc/$$app -n $(NAMESPACE) >/dev/null 2>&1 || \
			oc new-build --name=$$app --binary --strategy=docker -n $(NAMESPACE) -l app=$$app; \
		oc start-build $$app --from-dir=./$$app -n $(NAMESPACE) --follow; \
	done

.PHONY: install
install: ## helm install/upgrade the chart into NAMESPACE
	helm upgrade --install $(RELEASE) ./chart --namespace $(NAMESPACE)

.PHONY: deploy
deploy: build install ## Build images and install the chart (full deploy)
	@echo
	@echo "Waiting for Elasticsearch to reach green health (this can take 3-5 min)..."
	@oc wait --for=jsonpath='{.status.health}'=green elasticsearch/$(STACK_NAME) \
		-n $(NAMESPACE) --timeout=600s || true
	@echo
	@echo "Waiting for app rollouts..."
	@for d in payment-service payment-loadgen remediation-agent; do \
		oc rollout status deployment/$$d -n $(NAMESPACE) --timeout=120s || true; \
	done
	@echo
	@$(MAKE) status

.PHONY: status
status: ## Show ECK CRs, pods, routes, and Kibana access info
	@echo "=== Elastic Stack ==="
	@oc get elasticsearch,kibana,apmserver,agent -n $(NAMESPACE) 2>/dev/null
	@echo
	@echo "=== Pods ==="
	@oc get pods -n $(NAMESPACE) -l app.kubernetes.io/part-of=elastic-autonomous-sre
	@echo
	@echo "=== Routes ==="
	@oc get route -n $(NAMESPACE) -o custom-columns=NAME:.metadata.name,HOST:.spec.host 2>/dev/null
	@echo
	@if [ -n "$(KIBANA_HOST)" ]; then \
		echo "=== Kibana access ==="; \
		echo "  URL:  $(KIBANA_URL)"; \
		echo "  user: elastic"; \
		echo "  pass: $(KIBANA_PASS)"; \
	fi

.PHONY: kibana-creds
kibana-creds: ## Print Kibana URL + elastic user password
	@echo "URL:  $(KIBANA_URL)"
	@echo "user: elastic"
	@echo "pass: $(KIBANA_PASS)"

##@ Demo

.PHONY: inject-latency
inject-latency: ## Inject 5s latency into payment-service (DELAY_MS overrides)
	@: $${DELAY_MS:=5000}; \
	echo "Injecting $$DELAY_MS ms latency..."; \
	curl -sk -X POST "https://$(PAYMENT_ROUTE)/admin/fail/latency?delay_ms=$$DELAY_MS"; \
	echo

.PHONY: inject-oom
inject-oom: ## Trigger an OOM crash in payment-service
	@echo "Triggering OOM..."
	@curl -sk -X POST "https://$(PAYMENT_ROUTE)/admin/fail/oom" || true
	@echo

.PHONY: reset
reset: ## Clear all injected failures
	@curl -sk -X POST "https://$(PAYMENT_ROUTE)/admin/fail/clear"
	@echo

.PHONY: traffic
traffic: ## Send a single test request to payment-service
	@curl -sk "https://$(PAYMENT_ROUTE)/health" && echo
	@curl -sk -X POST "https://$(PAYMENT_ROUTE)/charge" \
		-H "Content-Type: application/json" \
		-d '{"amount": 42.00, "currency": "USD"}' && echo

.PHONY: logs-agent
logs-agent: ## Tail remediation-agent logs
	oc logs -f -n $(NAMESPACE) -l app=remediation-agent --tail=50

.PHONY: logs-payment
logs-payment: ## Tail payment-service logs
	oc logs -f -n $(NAMESPACE) -l app=payment-service --tail=50

##@ Elastic workflow

.PHONY: workflow-deploy
workflow-deploy: ## Push workflows/3am-alert-killer.yaml to Kibana (requires KIBANA_URL + ELASTIC_API_KEY)
	@if [ -z "$(KIBANA_URL)" ] || [ -z "$(ELASTIC_API_KEY)" ]; then \
		echo "ERROR: set KIBANA_URL and ELASTIC_API_KEY env vars"; exit 1; \
	fi
	@command -v jq >/dev/null || { echo "ERROR: jq required"; exit 1; }
	jq -Rs --arg yaml "$$(cat workflows/3am-alert-killer.yaml)" '{workflows: [{yaml: $$yaml}]}' <<< '' \
		| curl -s -X POST "$(KIBANA_URL)/api/workflows?overwrite=true" \
			-H "Authorization: ApiKey $(ELASTIC_API_KEY)" \
			-H "kbn-xsrf: true" \
			-H "Content-Type: application/json" \
			--data-binary @-
	@echo

##@ Diagrams

.PHONY: diagram
diagram: ## Render docs/images/architecture.mmd to architecture.png (needs mmdc)
	@command -v mmdc >/dev/null || { \
		echo "ERROR: mmdc not found. Install with: npm install -g @mermaid-js/mermaid-cli"; \
		exit 1; \
	}
	mmdc -i docs/images/architecture.mmd \
		 -o docs/images/architecture.png \
		 -w 1600 -H 900 \
		 -b transparent

##@ Quality

.PHONY: lint
lint: ## helm lint + ruff
	helm lint chart
	@command -v ruff >/dev/null && ruff check payment-service payment-loadgen remediation-agent || \
		echo "ruff not installed, skipping python lint"

.PHONY: template
template: ## Render the chart for inspection
	helm template $(RELEASE) ./chart --namespace $(NAMESPACE) --set otel.existingSecret=$(OTEL_SECRET)

##@ Teardown

.PHONY: clean
clean: ## helm uninstall + remove BuildConfigs/ImageStreams (preserves Elasticsearch PVCs)
	-helm uninstall $(RELEASE) --namespace $(NAMESPACE)
	-oc delete bc payment-service payment-loadgen remediation-agent -n $(NAMESPACE) --ignore-not-found
	-oc delete is payment-service payment-loadgen remediation-agent -n $(NAMESPACE) --ignore-not-found

.PHONY: clean-all
clean-all: clean ## clean + delete Elasticsearch PVCs (DESTROYS DATA)
	-oc delete pvc -n $(NAMESPACE) -l elasticsearch.k8s.elastic.co/cluster-name=$(STACK_NAME)
