"""A2A Agent Card definition for the OpenShift Remediation Agent."""

from config import settings


def get_agent_card() -> dict:
    """Return the A2A Agent Card describing this agent's capabilities."""
    base_url = settings.AGENT_EXTERNAL_URL.rstrip("/")

    return {
        "name": "OpenShift Remediation Agent",
        "description": "Automated remediation agent for OpenShift clusters. "
        "Executes corrective actions such as restarting pods, scaling deployments, "
        "deleting stuck pods, and rolling back deployments.",
        "url": base_url,
        "version": "1.0.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "restart_pod",
                "name": "Restart Pod",
                "description": (
                    "Restart a pod by deleting it and allowing the controller "
                    "to recreate it. Useful for pods stuck in error states."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace of the pod.",
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Name of the pod to restart.",
                        },
                    },
                    "required": ["namespace", "pod_name"],
                },
            },
            {
                "id": "scale_deployment",
                "name": "Scale Deployment",
                "description": (
                    "Scale a deployment to a specified number of replicas. "
                    "Can be used to scale up for load or scale down to zero."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace of the deployment.",
                        },
                        "deployment_name": {
                            "type": "string",
                            "description": "Name of the deployment to scale.",
                        },
                        "replicas": {
                            "type": "integer",
                            "description": "Desired number of replicas.",
                            "minimum": 0,
                        },
                    },
                    "required": ["namespace", "deployment_name", "replicas"],
                },
            },
            {
                "id": "delete_pod",
                "name": "Delete Pod",
                "description": (
                    "Delete a specific pod, optionally with force. "
                    "Useful for removing pods stuck in Terminating state."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace of the pod.",
                        },
                        "pod_name": {
                            "type": "string",
                            "description": "Name of the pod to delete.",
                        },
                        "force": {
                            "type": "boolean",
                            "description": "Force delete with zero grace period.",
                            "default": False,
                        },
                    },
                    "required": ["namespace", "pod_name"],
                },
            },
            {
                "id": "rollback_deployment",
                "name": "Rollback Deployment",
                "description": (
                    "Rollback a deployment to the previous revision. "
                    "Useful when a new version introduces errors."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace of the deployment.",
                        },
                        "deployment_name": {
                            "type": "string",
                            "description": "Name of the deployment to rollback.",
                        },
                    },
                    "required": ["namespace", "deployment_name"],
                },
            },
            {
                "id": "restart_deployment",
                "name": "Restart Deployment",
                "description": (
                    "Rollout restart a deployment by patching the pod template annotation. "
                    "Equivalent to kubectl rollout restart. Useful for crash loops and pod failures."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace of the deployment.",
                        },
                        "deployment_name": {
                            "type": "string",
                            "description": "Name of the deployment to restart.",
                        },
                    },
                    "required": ["namespace", "deployment_name"],
                },
            },
            {
                "id": "verify_deployment_health",
                "name": "Verify Deployment Health",
                "description": (
                    "Check if a deployment is healthy: all replicas ready, "
                    "no crash-looping containers, no high restart counts."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {
                            "type": "string",
                            "description": "Kubernetes namespace of the deployment.",
                        },
                        "deployment_name": {
                            "type": "string",
                            "description": "Name of the deployment to verify.",
                        },
                    },
                    "required": ["namespace", "deployment_name"],
                },
            },
        ],
    }
