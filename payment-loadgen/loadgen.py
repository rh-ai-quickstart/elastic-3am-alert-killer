"""
Simple load generator for payment-service.
Sends continuous payment requests to generate APM traces and trigger latency alerts.
"""

import asyncio
import logging
import os
import random
import time

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("loadgen")

PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://payment-service:8080")
RPS = float(os.environ.get("REQUESTS_PER_SECOND", "2"))
CUSTOMERS = [f"cust-{i:04d}" for i in range(1, 51)]
AMOUNTS = [9.99, 19.99, 49.99, 99.99, 149.99, 249.99, 499.99]
DESCRIPTIONS = [
    "Monthly subscription",
    "One-time purchase",
    "Premium upgrade",
    "Checkout order #{}",
    "Refund processing",
    "Wire transfer",
    "Invoice payment",
]


async def send_payment(client: httpx.AsyncClient) -> None:
    payload = {
        "amount": random.choice(AMOUNTS),
        "currency": random.choice(["USD", "EUR", "GBP"]),
        "customer_id": random.choice(CUSTOMERS),
        "description": random.choice(DESCRIPTIONS).format(random.randint(1000, 9999)),
    }
    try:
        start = time.monotonic()
        resp = await client.post(f"{PAYMENT_URL}/pay", json=payload, timeout=30.0)
        elapsed = (time.monotonic() - start) * 1000
        if resp.status_code == 200:
            data = resp.json()
            logger.info(
                "txn=%s amount=%.2f %s latency=%.0fms",
                data["transaction_id"], payload["amount"], payload["currency"], elapsed,
            )
        else:
            logger.warning("HTTP %d: %s (%.0fms)", resp.status_code, resp.text[:100], elapsed)
    except Exception as e:
        logger.error("Request failed: %s", e)


async def main() -> None:
    interval = 1.0 / RPS
    logger.info("Starting load generator: %.1f req/s -> %s", RPS, PAYMENT_URL)

    async with httpx.AsyncClient() as client:
        while True:
            asyncio.create_task(send_payment(client))
            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main())
