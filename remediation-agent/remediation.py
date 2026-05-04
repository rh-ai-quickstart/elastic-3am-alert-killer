"""Kubernetes remediation actions for the OpenShift Remediation Agent."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class RemediationResult:
    """Result of a remediation action."""

    success: bool
    action: str
    namespace: str
    resource: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class NamespaceNotAllowedError(Exception):
    """Raised when an action targets a namespace not in the allow list."""


class RemediationExecutor:
    """Executes Kubernetes remediation actions against the cluster."""

    def __init__(self) -> None:
        self._core_v1: client.CoreV1Api | None = None
        self._apps_v1: client.AppsV1Api | None = None
        self._k8s_initialized = False

    def _init_k8s(self) -> None:
        """Initialize the Kubernetes client (in-cluster config)."""
        if self._k8s_initialized:
            return
        try:
            k8s_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration.")
        except k8s_config.ConfigException:
            logger.warning(
                "In-cluster config not available, falling back to kubeconfig."
            )
            k8s_config.load_kube_config()
        self._core_v1 = client.CoreV1Api()
        self._apps_v1 = client.AppsV1Api()
        self._k8s_initialized = True

    @property
    def core_v1(self) -> client.CoreV1Api:
        self._init_k8s()
        assert self._core_v1 is not None
        return self._core_v1

    @property
    def apps_v1(self) -> client.AppsV1Api:
        self._init_k8s()
        assert self._apps_v1 is not None
        return self._apps_v1

    def _check_namespace(self, namespace: str) -> None:
        """Validate that the namespace is in the allowed list."""
        allowed = settings.allowed_namespaces_list
        if allowed and namespace not in allowed:
            raise NamespaceNotAllowedError(
                f"Namespace '{namespace}' is not in the allowed list: {allowed}"
            )

    def restart_pod(self, namespace: str, pod_name: str) -> RemediationResult:
        """Restart a pod by deleting it so its controller recreates it."""
        self._check_namespace(namespace)
        logger.info("Restarting pod %s/%s (dry_run=%s)", namespace, pod_name, settings.DRY_RUN)

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="restart_pod",
                namespace=namespace,
                resource=pod_name,
                message=f"[DRY RUN] Would delete pod '{pod_name}' in namespace '{namespace}' to trigger restart.",
            )

        try:
            self.core_v1.delete_namespaced_pod(
                name=pod_name,
                namespace=namespace,
                body=client.V1DeleteOptions(grace_period_seconds=30),
            )
            return RemediationResult(
                success=True,
                action="restart_pod",
                namespace=namespace,
                resource=pod_name,
                message=f"Pod '{pod_name}' in namespace '{namespace}' deleted to trigger restart.",
            )
        except ApiException as exc:
            logger.error("Failed to restart pod %s/%s: %s", namespace, pod_name, exc.reason)
            return RemediationResult(
                success=False,
                action="restart_pod",
                namespace=namespace,
                resource=pod_name,
                message=f"Failed to restart pod '{pod_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )

    def scale_deployment(
        self, namespace: str, deployment_name: str, replicas: int
    ) -> RemediationResult:
        """Scale a deployment to the desired number of replicas."""
        self._check_namespace(namespace)
        logger.info(
            "Scaling deployment %s/%s to %d replicas (dry_run=%s)",
            namespace, deployment_name, replicas, settings.DRY_RUN,
        )

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="scale_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"[DRY RUN] Would scale deployment '{deployment_name}' "
                    f"in namespace '{namespace}' to {replicas} replicas."
                ),
                details={"replicas": replicas},
            )

        try:
            body = {"spec": {"replicas": replicas}}
            self.apps_v1.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=namespace,
                body=body,
            )
            return RemediationResult(
                success=True,
                action="scale_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"Deployment '{deployment_name}' in namespace '{namespace}' "
                    f"scaled to {replicas} replicas."
                ),
                details={"replicas": replicas},
            )
        except ApiException as exc:
            logger.error(
                "Failed to scale deployment %s/%s: %s",
                namespace, deployment_name, exc.reason,
            )
            return RemediationResult(
                success=False,
                action="scale_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=f"Failed to scale deployment '{deployment_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )

    def delete_pod(
        self, namespace: str, pod_name: str, force: bool = False
    ) -> RemediationResult:
        """Delete a pod, optionally with force (zero grace period)."""
        self._check_namespace(namespace)
        grace = 0 if force else 30
        logger.info(
            "Deleting pod %s/%s (force=%s, dry_run=%s)",
            namespace, pod_name, force, settings.DRY_RUN,
        )

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="delete_pod",
                namespace=namespace,
                resource=pod_name,
                message=(
                    f"[DRY RUN] Would delete pod '{pod_name}' in namespace "
                    f"'{namespace}' (force={force})."
                ),
                details={"force": force},
            )

        try:
            self.core_v1.delete_namespaced_pod(
                name=pod_name,
                namespace=namespace,
                body=client.V1DeleteOptions(grace_period_seconds=grace),
            )
            return RemediationResult(
                success=True,
                action="delete_pod",
                namespace=namespace,
                resource=pod_name,
                message=(
                    f"Pod '{pod_name}' in namespace '{namespace}' deleted "
                    f"(force={force})."
                ),
                details={"force": force},
            )
        except ApiException as exc:
            logger.error("Failed to delete pod %s/%s: %s", namespace, pod_name, exc.reason)
            return RemediationResult(
                success=False,
                action="delete_pod",
                namespace=namespace,
                resource=pod_name,
                message=f"Failed to delete pod '{pod_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason, "force": force},
            )

    def rollback_deployment(
        self, namespace: str, deployment_name: str
    ) -> RemediationResult:
        """Rollback a deployment to the previous revision.

        Kubernetes does not have a direct rollback API in apps/v1. The strategy
        used here is to find the previous ReplicaSet revision and patch the
        deployment's pod template to match it.
        """
        self._check_namespace(namespace)
        logger.info(
            "Rolling back deployment %s/%s (dry_run=%s)",
            namespace, deployment_name, settings.DRY_RUN,
        )

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="rollback_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"[DRY RUN] Would rollback deployment '{deployment_name}' "
                    f"in namespace '{namespace}' to the previous revision."
                ),
            )

        try:
            # List ReplicaSets owned by this deployment
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )
            selector = deployment.spec.selector.match_labels
            label_selector = ",".join(f"{k}={v}" for k, v in selector.items())

            rs_list = self.apps_v1.list_namespaced_replica_set(
                namespace=namespace, label_selector=label_selector
            )

            # Sort by revision annotation (descending)
            revision_key = "deployment.kubernetes.io/revision"
            annotated = []
            for rs in rs_list.items:
                annotations = rs.metadata.annotations or {}
                rev = int(annotations.get(revision_key, "0"))
                annotated.append((rev, rs))
            annotated.sort(key=lambda x: x[0], reverse=True)

            if len(annotated) < 2:
                return RemediationResult(
                    success=False,
                    action="rollback_deployment",
                    namespace=namespace,
                    resource=deployment_name,
                    message=(
                        f"Cannot rollback deployment '{deployment_name}': "
                        "no previous revision found."
                    ),
                )

            previous_rs = annotated[1][1]
            previous_template = previous_rs.spec.template

            # Patch the deployment with the previous pod template
            body = {"spec": {"template": previous_template.to_dict()}}
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body,
            )

            return RemediationResult(
                success=True,
                action="rollback_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"Deployment '{deployment_name}' in namespace '{namespace}' "
                    f"rolled back to revision {annotated[1][0]}."
                ),
                details={"rolled_back_to_revision": annotated[1][0]},
            )
        except ApiException as exc:
            logger.error(
                "Failed to rollback deployment %s/%s: %s",
                namespace, deployment_name, exc.reason,
            )
            return RemediationResult(
                success=False,
                action="rollback_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=f"Failed to rollback deployment '{deployment_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )

    def get_pod_status(self, namespace: str, pod_name: str) -> RemediationResult:
        """Retrieve the current status of a pod."""
        self._check_namespace(namespace)
        logger.info("Getting status of pod %s/%s", namespace, pod_name)

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="get_pod_status",
                namespace=namespace,
                resource=pod_name,
                message=f"[DRY RUN] Would retrieve status of pod '{pod_name}'.",
            )

        try:
            pod = self.core_v1.read_namespaced_pod_status(
                name=pod_name, namespace=namespace
            )
            phase = pod.status.phase if pod.status else "Unknown"
            container_statuses = []
            if pod.status and pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    container_statuses.append({
                        "name": cs.name,
                        "ready": cs.ready,
                        "restart_count": cs.restart_count,
                        "state": str(cs.state),
                    })

            return RemediationResult(
                success=True,
                action="get_pod_status",
                namespace=namespace,
                resource=pod_name,
                message=f"Pod '{pod_name}' is in phase '{phase}'.",
                details={
                    "phase": phase,
                    "containers": container_statuses,
                },
            )
        except ApiException as exc:
            logger.error("Failed to get pod status %s/%s: %s", namespace, pod_name, exc.reason)
            return RemediationResult(
                success=False,
                action="get_pod_status",
                namespace=namespace,
                resource=pod_name,
                message=f"Failed to get status of pod '{pod_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )

    def get_deployment_status(
        self, namespace: str, deployment_name: str
    ) -> RemediationResult:
        """Retrieve the current status of a deployment."""
        self._check_namespace(namespace)
        logger.info("Getting status of deployment %s/%s", namespace, deployment_name)

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="get_deployment_status",
                namespace=namespace,
                resource=deployment_name,
                message=f"[DRY RUN] Would retrieve status of deployment '{deployment_name}'.",
            )

        try:
            dep = self.apps_v1.read_namespaced_deployment_status(
                name=deployment_name, namespace=namespace
            )
            status = dep.status
            return RemediationResult(
                success=True,
                action="get_deployment_status",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"Deployment '{deployment_name}': "
                    f"{status.ready_replicas or 0}/{status.replicas or 0} ready."
                ),
                details={
                    "replicas": status.replicas,
                    "ready_replicas": status.ready_replicas,
                    "available_replicas": status.available_replicas,
                    "updated_replicas": status.updated_replicas,
                    "unavailable_replicas": status.unavailable_replicas,
                },
            )
        except ApiException as exc:
            logger.error(
                "Failed to get deployment status %s/%s: %s",
                namespace, deployment_name, exc.reason,
            )
            return RemediationResult(
                success=False,
                action="get_deployment_status",
                namespace=namespace,
                resource=deployment_name,
                message=f"Failed to get status of deployment '{deployment_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )

    def restart_deployment(
        self, namespace: str, deployment_name: str
    ) -> RemediationResult:
        """Rollout restart a deployment via annotation patch (equivalent to kubectl rollout restart)."""
        self._check_namespace(namespace)
        logger.info(
            "Rollout restarting deployment %s/%s (dry_run=%s)",
            namespace, deployment_name, settings.DRY_RUN,
        )

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="restart_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"[DRY RUN] Would rollout restart deployment '{deployment_name}' "
                    f"in namespace '{namespace}'."
                ),
            )

        try:
            body = {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "kubectl.kubernetes.io/restartedAt": datetime.now(
                                    timezone.utc
                                ).isoformat()
                            }
                        }
                    }
                }
            }
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name, namespace=namespace, body=body
            )
            return RemediationResult(
                success=True,
                action="restart_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"Deployment '{deployment_name}' in namespace '{namespace}' "
                    f"rollout restart triggered."
                ),
            )
        except ApiException as exc:
            logger.error(
                "Failed to restart deployment %s/%s: %s",
                namespace, deployment_name, exc.reason,
            )
            return RemediationResult(
                success=False,
                action="restart_deployment",
                namespace=namespace,
                resource=deployment_name,
                message=f"Failed to restart deployment '{deployment_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )

    def verify_deployment_health(
        self, namespace: str, deployment_name: str
    ) -> RemediationResult:
        """Check if a deployment is healthy (all replicas ready, no crash loops)."""
        self._check_namespace(namespace)
        logger.info("Verifying health of deployment %s/%s", namespace, deployment_name)

        if settings.DRY_RUN:
            return RemediationResult(
                success=True,
                action="verify_deployment_health",
                namespace=namespace,
                resource=deployment_name,
                message=f"[DRY RUN] Would verify health of deployment '{deployment_name}'.",
            )

        try:
            dep = self.apps_v1.read_namespaced_deployment_status(
                name=deployment_name, namespace=namespace
            )
            status = dep.status
            replicas = status.replicas or 0
            ready = status.ready_replicas or 0
            unavailable = status.unavailable_replicas or 0

            # Check pod statuses for crash loops
            selector = dep.spec.selector.match_labels
            label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace, label_selector=label_selector
            )

            crash_loop_pods = []
            high_restart_pods = []
            for pod in pods.items:
                if not pod.status or not pod.status.container_statuses:
                    continue
                for cs in pod.status.container_statuses:
                    if cs.restart_count and cs.restart_count >= 5:
                        high_restart_pods.append(
                            {"pod": pod.metadata.name, "container": cs.name, "restarts": cs.restart_count}
                        )
                    if cs.state and cs.state.waiting and cs.state.waiting.reason == "CrashLoopBackOff":
                        crash_loop_pods.append(
                            {"pod": pod.metadata.name, "container": cs.name}
                        )

            healthy = ready == replicas and unavailable == 0 and not crash_loop_pods
            return RemediationResult(
                success=healthy,
                action="verify_deployment_health",
                namespace=namespace,
                resource=deployment_name,
                message=(
                    f"Deployment '{deployment_name}': {ready}/{replicas} ready, "
                    f"{len(crash_loop_pods)} crash-looping, "
                    f"{'HEALTHY' if healthy else 'UNHEALTHY'}."
                ),
                details={
                    "replicas": replicas,
                    "ready_replicas": ready,
                    "unavailable_replicas": unavailable,
                    "crash_loop_pods": crash_loop_pods,
                    "high_restart_pods": high_restart_pods,
                    "healthy": healthy,
                },
            )
        except ApiException as exc:
            logger.error(
                "Failed to verify deployment health %s/%s: %s",
                namespace, deployment_name, exc.reason,
            )
            return RemediationResult(
                success=False,
                action="verify_deployment_health",
                namespace=namespace,
                resource=deployment_name,
                message=f"Failed to verify deployment '{deployment_name}': {exc.reason}",
                details={"status_code": exc.status, "reason": exc.reason},
            )
