"""FastAPI A2A server for the OpenShift Remediation Agent."""

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_card import get_agent_card
from config import settings
from task_handler import TaskHandler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
task_handler = TaskHandler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info(
        "OpenShift Remediation Agent starting on %s:%s (dry_run=%s)",
        settings.AGENT_HOST,
        settings.AGENT_PORT,
        settings.DRY_RUN,
    )
    yield
    logger.info("OpenShift Remediation Agent shutting down.")


app = FastAPI(
    title="OpenShift Remediation Agent",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

JSONRPC_VERSION = "2.0"
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001


def _jsonrpc_error(
    req_id: Any, code: int, message: str, data: Any = None
) -> JSONResponse:
    """Build a JSON-RPC 2.0 error response."""
    body: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        body["error"]["data"] = data
    return JSONResponse(content=body)


def _jsonrpc_success(req_id: Any, result: Any) -> JSONResponse:
    """Build a JSON-RPC 2.0 success response."""
    return JSONResponse(
        content={
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "result": result,
        }
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/.well-known/agent-card.json")
async def agent_card():
    """Serve the A2A Agent Card."""
    return get_agent_card()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": settings.AGENT_NAME}


@app.post("/")
async def a2a_endpoint(request: Request):
    """A2A JSON-RPC 2.0 endpoint."""
    # Parse the request body
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, PARSE_ERROR, "Parse error: invalid JSON.")

    # Validate JSON-RPC envelope
    if not isinstance(body, dict):
        return _jsonrpc_error(None, INVALID_REQUEST, "Request must be a JSON object.")

    jsonrpc = body.get("jsonrpc")
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    if jsonrpc != JSONRPC_VERSION:
        return _jsonrpc_error(
            req_id, INVALID_REQUEST, "Invalid or missing 'jsonrpc' field. Must be '2.0'."
        )

    if not isinstance(method, str) or not method:
        return _jsonrpc_error(req_id, INVALID_REQUEST, "Missing or invalid 'method' field.")

    # Dispatch by method
    if method == "tasks/send":
        return _handle_tasks_send(req_id, params)
    elif method == "tasks/get":
        return _handle_tasks_get(req_id, params)
    elif method == "tasks/cancel":
        return _handle_tasks_cancel(req_id, params)
    else:
        return _jsonrpc_error(req_id, METHOD_NOT_FOUND, f"Method '{method}' not found.")


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------

def _handle_tasks_send(req_id: Any, params: dict[str, Any]) -> JSONResponse:
    """Handle tasks/send -- receive and process a remediation task."""
    if not isinstance(params, dict):
        return _jsonrpc_error(req_id, INVALID_PARAMS, "Params must be a JSON object.")

    message = params.get("message")
    if not message or not isinstance(message, dict):
        return _jsonrpc_error(
            req_id, INVALID_PARAMS, "Missing or invalid 'message' in params."
        )

    try:
        task = task_handler.handle_task(params)
        return _jsonrpc_success(req_id, task)
    except Exception as exc:
        logger.exception("Error processing tasks/send")
        return _jsonrpc_error(req_id, INTERNAL_ERROR, f"Internal error: {exc}")


def _handle_tasks_get(req_id: Any, params: dict[str, Any]) -> JSONResponse:
    """Handle tasks/get -- return current task status."""
    if not isinstance(params, dict):
        return _jsonrpc_error(req_id, INVALID_PARAMS, "Params must be a JSON object.")

    task_id = params.get("id")
    if not task_id:
        return _jsonrpc_error(req_id, INVALID_PARAMS, "Missing 'id' in params.")

    task = task_handler.get_task(task_id)
    if task is None:
        return _jsonrpc_error(req_id, TASK_NOT_FOUND, f"Task '{task_id}' not found.")

    return _jsonrpc_success(req_id, task)


def _handle_tasks_cancel(req_id: Any, params: dict[str, Any]) -> JSONResponse:
    """Handle tasks/cancel -- cancel a running task."""
    if not isinstance(params, dict):
        return _jsonrpc_error(req_id, INVALID_PARAMS, "Params must be a JSON object.")

    task_id = params.get("id")
    if not task_id:
        return _jsonrpc_error(req_id, INVALID_PARAMS, "Missing 'id' in params.")

    task = task_handler.cancel_task(task_id)
    if task is None:
        return _jsonrpc_error(req_id, TASK_NOT_FOUND, f"Task '{task_id}' not found.")

    return _jsonrpc_success(req_id, task)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.AGENT_HOST,
        port=settings.AGENT_PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
