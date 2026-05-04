"""A2A task lifecycle management for the OpenShift Remediation Agent."""

import json
import logging
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from remediation import NamespaceNotAllowedError, RemediationExecutor, RemediationResult

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    """A2A task states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskHandler:
    """Manages A2A task lifecycle and dispatches remediation actions."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._executor = RemediationExecutor()

    def _create_task(self, task_id: str | None = None) -> dict[str, Any]:
        """Create a new task record."""
        tid = task_id or str(uuid.uuid4())
        task: dict[str, Any] = {
            "id": tid,
            "status": {
                "state": TaskState.SUBMITTED,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": None,
            },
            "history": [],
            "artifacts": [],
        }
        self._tasks[tid] = task
        return task

    def _update_state(
        self, task: dict[str, Any], state: TaskState, message: str | None = None
    ) -> None:
        """Transition a task to a new state and record history."""
        previous = task["status"].copy()
        task["history"].append(previous)
        task["status"] = {
            "state": state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
        }

    def _parse_action(self, text: str) -> dict[str, Any]:
        """Parse an incoming message to extract the remediation action and parameters.

        Supports two formats:
        1. JSON body with explicit fields:
           {"action": "restart_pod", "namespace": "myns", "pod_name": "mypod"}
        2. Natural-language style (best-effort extraction):
           "Restart pod my-pod-abc in namespace production"
        """
        # Try JSON first
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "action" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass

        # Natural language parsing
        normalized = text.lower().strip()
        params: dict[str, Any] = {}

        # Extract namespace
        ns_match = re.search(r"(?:namespace|ns)[:\s]+([a-z0-9][-a-z0-9]*)", normalized)
        if ns_match:
            params["namespace"] = ns_match.group(1)

        # Detect action and resource
        if re.search(r"\brestart\b.*\bpod\b", normalized):
            params["action"] = "restart_pod"
            pod_match = re.search(r"pod[:\s]+([a-z0-9][-a-z0-9.]*)", normalized)
            if pod_match:
                params["pod_name"] = pod_match.group(1)
        elif re.search(r"\bdelete\b.*\bpod\b", normalized):
            params["action"] = "delete_pod"
            pod_match = re.search(r"pod[:\s]+([a-z0-9][-a-z0-9.]*)", normalized)
            if pod_match:
                params["pod_name"] = pod_match.group(1)
            if "force" in normalized:
                params["force"] = True
        elif re.search(r"\bscale\b.*\bdeployment\b", normalized):
            params["action"] = "scale_deployment"
            dep_match = re.search(r"deployment[:\s]+([a-z0-9][-a-z0-9.]*)", normalized)
            if dep_match:
                params["deployment_name"] = dep_match.group(1)
            rep_match = re.search(r"(?:to|replicas)[:\s]*(\d+)", normalized)
            if rep_match:
                params["replicas"] = int(rep_match.group(1))
        elif re.search(r"\brollback\b.*\bdeployment\b", normalized):
            params["action"] = "rollback_deployment"
            dep_match = re.search(r"deployment[:\s]+([a-z0-9][-a-z0-9.]*)", normalized)
            if dep_match:
                params["deployment_name"] = dep_match.group(1)
        elif re.search(r"\brestart\b.*\bdeployment\b", normalized):
            params["action"] = "restart_deployment"
            dep_match = re.search(r"deployment[:\s]+([a-z0-9][-a-z0-9.]*)", normalized)
            if dep_match:
                params["deployment_name"] = dep_match.group(1)
        elif re.search(r"\bverify\b.*\bdeployment\b", normalized):
            params["action"] = "verify_deployment_health"
            dep_match = re.search(r"deployment[:\s]+([a-z0-9][-a-z0-9.]*)", normalized)
            if dep_match:
                params["deployment_name"] = dep_match.group(1)

        return params

    def _execute_action(self, params: dict[str, Any]) -> RemediationResult:
        """Dispatch to the appropriate remediation action."""
        action = params.get("action")
        namespace = params.get("namespace", "")
        if not action:
            raise ValueError("No remediation action could be determined from the message.")
        if not namespace:
            raise ValueError("No namespace specified for the remediation action.")

        if action == "restart_pod":
            pod_name = params.get("pod_name")
            if not pod_name:
                raise ValueError("No pod_name specified for restart_pod action.")
            return self._executor.restart_pod(namespace, pod_name)

        if action == "scale_deployment":
            deployment_name = params.get("deployment_name")
            replicas = params.get("replicas")
            if not deployment_name:
                raise ValueError("No deployment_name specified for scale_deployment action.")
            if replicas is None:
                raise ValueError("No replicas count specified for scale_deployment action.")
            return self._executor.scale_deployment(namespace, deployment_name, int(replicas))

        if action == "delete_pod":
            pod_name = params.get("pod_name")
            if not pod_name:
                raise ValueError("No pod_name specified for delete_pod action.")
            force = params.get("force", False)
            return self._executor.delete_pod(namespace, pod_name, force=bool(force))

        if action == "rollback_deployment":
            deployment_name = params.get("deployment_name")
            if not deployment_name:
                raise ValueError("No deployment_name specified for rollback_deployment action.")
            return self._executor.rollback_deployment(namespace, deployment_name)

        if action == "restart_deployment":
            deployment_name = params.get("deployment_name")
            if not deployment_name:
                raise ValueError("No deployment_name specified for restart_deployment action.")
            return self._executor.restart_deployment(namespace, deployment_name)

        if action == "verify_deployment_health":
            deployment_name = params.get("deployment_name")
            if not deployment_name:
                raise ValueError("No deployment_name specified for verify_deployment_health action.")
            return self._executor.verify_deployment_health(namespace, deployment_name)

        raise ValueError(f"Unknown action: {action}")

    def handle_task(self, task_params: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming A2A task/send request.

        Args:
            task_params: The ``params`` field from the JSON-RPC request, containing
                         at minimum an ``id`` and a ``message`` with ``parts``.

        Returns:
            The full task object with updated status and artifacts.
        """
        task_id = task_params.get("id", str(uuid.uuid4()))
        task = self._create_task(task_id)

        # Extract the text content from the message parts
        message = task_params.get("message", {})
        parts = message.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        full_text = "\n".join(text_parts).strip()

        if not full_text:
            self._update_state(task, TaskState.FAILED, "No text content in the task message.")
            return task

        # Move to working
        self._update_state(task, TaskState.WORKING, "Parsing remediation request.")

        try:
            params = self._parse_action(full_text)
            result = self._execute_action(params)
        except NamespaceNotAllowedError as exc:
            logger.warning("Namespace not allowed: %s", exc)
            self._update_state(task, TaskState.FAILED, str(exc))
            return task
        except ValueError as exc:
            logger.warning("Invalid remediation request: %s", exc)
            self._update_state(task, TaskState.FAILED, str(exc))
            return task
        except Exception as exc:
            logger.exception("Unexpected error executing remediation.")
            self._update_state(task, TaskState.FAILED, f"Internal error: {exc}")
            return task

        # Build artifact from result
        result_dict = asdict(result)
        artifact = {
            "parts": [
                {"type": "text", "text": result.message},
                {"type": "data", "data": result_dict},
            ],
        }
        task["artifacts"].append(artifact)

        if result.success:
            self._update_state(task, TaskState.COMPLETED, result.message)
        else:
            self._update_state(task, TaskState.FAILED, result.message)

        return task

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Return a task by its ID, or None if not found."""
        return self._tasks.get(task_id)

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        """Cancel a task if it is still in a cancelable state."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        current_state = task["status"]["state"]
        if current_state in (TaskState.SUBMITTED, TaskState.WORKING):
            self._update_state(task, TaskState.CANCELED, "Task canceled by client.")
        return task
