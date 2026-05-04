"""
payment-service: Simulated payment processing service with failure injection.

Endpoints:
  GET  /health              - Health check
  POST /pay                 - Process a payment (affected by failure modes)
  POST /admin/fail/oom      - Trigger OOM: allocates memory until killed
  POST /admin/fail/latency  - Trigger high latency: adds delay to /pay
  POST /admin/fail/clear    - Clear all injected failures
  GET  /admin/status        - Show current failure injection state
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("payment-service")

# ---------------------------------------------------------------------------
# Failure injection state
# ---------------------------------------------------------------------------
_failure_state = {
    "latency_ms": 0,       # extra latency added to /pay (ms)
    "oom_triggered": False, # whether OOM leak is active
}
_memory_leak: list[bytes] = []  # holds allocated chunks for OOM simulation


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("payment-service starting up")
    yield
    logger.info("payment-service shutting down")


app = FastAPI(title="payment-service", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PaymentRequest(BaseModel):
    amount: float
    currency: str = "USD"
    customer_id: str
    description: str = ""


class PaymentResponse(BaseModel):
    transaction_id: str
    status: str
    amount: float
    currency: str
    processing_time_ms: float


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "payment-service"}


@app.post("/pay", response_model=PaymentResponse)
async def process_payment(req: PaymentRequest):
    start = time.monotonic()

    # Simulate latency injection
    if _failure_state["latency_ms"] > 0:
        delay = _failure_state["latency_ms"] / 1000.0
        logger.warning(f"Injecting {_failure_state['latency_ms']}ms latency")
        await asyncio.sleep(delay)

    # Simulate normal processing
    await asyncio.sleep(0.05)  # 50ms baseline

    # Validate
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    elapsed_ms = (time.monotonic() - start) * 1000
    txn_id = f"txn_{uuid.uuid4().hex[:12]}"

    logger.info(
        f"Payment processed: {txn_id} amount={req.amount} {req.currency} "
        f"customer={req.customer_id} time={elapsed_ms:.0f}ms"
    )

    return PaymentResponse(
        transaction_id=txn_id,
        status="completed",
        amount=req.amount,
        currency=req.currency,
        processing_time_ms=round(elapsed_ms, 1),
    )


# ---------------------------------------------------------------------------
# Failure injection endpoints
# ---------------------------------------------------------------------------
@app.post("/admin/fail/oom")
async def trigger_oom():
    """Allocate memory in a background task until the container is OOMKilled."""
    _failure_state["oom_triggered"] = True
    logger.error("OOM FAILURE INJECTION: Starting memory leak")

    # Allocate in 50MB chunks to simulate a gradual leak
    chunk_size = 50 * 1024 * 1024  # 50 MB
    async def _leak():
        while _failure_state["oom_triggered"]:
            _memory_leak.append(b"X" * chunk_size)
            allocated = len(_memory_leak) * chunk_size / (1024 * 1024)
            logger.error(f"OOM leak: allocated {allocated:.0f} MB total")
            await asyncio.sleep(1)

    asyncio.create_task(_leak())
    return {
        "status": "oom_triggered",
        "message": "Memory leak started. Container will be OOMKilled shortly.",
    }


@app.post("/admin/fail/latency")
async def trigger_latency(delay_ms: int = 5000):
    """Add artificial latency to /pay endpoint."""
    _failure_state["latency_ms"] = delay_ms
    logger.error(f"LATENCY FAILURE INJECTION: Adding {delay_ms}ms to /pay")
    return {
        "status": "latency_injected",
        "delay_ms": delay_ms,
        "message": f"All /pay requests will now take an extra {delay_ms}ms.",
    }


@app.post("/admin/fail/clear")
async def clear_failures():
    """Clear all injected failures."""
    _failure_state["latency_ms"] = 0
    _failure_state["oom_triggered"] = False
    _memory_leak.clear()
    logger.info("All failure injections cleared")
    return {"status": "cleared", "message": "All failure injections removed."}


@app.get("/admin/status")
async def failure_status():
    return {
        "latency_ms": _failure_state["latency_ms"],
        "oom_triggered": _failure_state["oom_triggered"],
        "oom_allocated_mb": len(_memory_leak) * 50,
    }
