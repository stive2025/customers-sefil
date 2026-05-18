"""
HTTP client for the Worker → Hostinger API communication.

Splits a list of CustomerUpsertItem into chunks of CHUNK_SIZE and POSTs each
chunk to POST /sync/bulk-upsert. Logs detailed per-chunk stats on HTTP 200.
Never raises — all errors are captured in SendStats.errors.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import List

import requests

from app.schemas.sync import BulkUpsertResponse, CustomerUpsertItem

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 500      # records per HTTP request
_TIMEOUT    = 120      # seconds to wait for each POST response


# ---------------------------------------------------------------------------
# Stats container
# ---------------------------------------------------------------------------

@dataclass
class SendStats:
    chunks_sent: int = 0
    created:     int = 0
    updated:     int = 0
    skipped:     int = 0
    errors: list[str] = field(default_factory=list)

    def absorb(self, resp: BulkUpsertResponse) -> None:
        self.chunks_sent += 1
        self.created  += resp.created
        self.updated  += resp.updated
        self.skipped  += resp.skipped
        self.errors.extend(resp.errors)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_config() -> tuple[str, str]:
    url = os.getenv("HOSTINGER_API_URL", "").rstrip("/")
    key = os.getenv("HOSTINGER_API_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "HOSTINGER_API_URL and HOSTINGER_API_KEY must be set in the environment."
        )
    return url, key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_customers(customers: List[CustomerUpsertItem], source_name: str) -> SendStats:
    """
    POST all customers to /sync/bulk-upsert in chunks of CHUNK_SIZE.

    Args:
        customers:   Pre-cleaned list of CustomerUpsertItem built by an ETL.
        source_name: Label used only for log messages (e.g. "Collecta-clients").

    Returns:
        SendStats with cumulative counters and any transport/API-level errors.
    """
    api_url, api_key = _get_config()
    endpoint = f"{api_url}/sync/bulk-upsert"
    stats    = SendStats()

    if not customers:
        logger.info("[%s] No records to send — skipping.", source_name)
        return stats

    total  = len(customers)
    chunks = [customers[i : i + _CHUNK_SIZE] for i in range(0, total, _CHUNK_SIZE)]

    logger.info(
        "[%s] Sending %d records in %d chunk(s) → %s",
        source_name, total, len(chunks), endpoint,
    )

    for idx, chunk in enumerate(chunks, start=1):
        payload = {"customers": [c.model_dump(mode="json") for c in chunk]}
        t0 = time.monotonic()

        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers={
                    "X-API-Key":     api_key,
                    "Content-Type":  "application/json",
                    "Accept":        "application/json",
                },
                timeout=_TIMEOUT,
            )
            elapsed = time.monotonic() - t0
            resp.raise_for_status()

            chunk_resp = BulkUpsertResponse(**resp.json())
            stats.absorb(chunk_resp)

            logger.info(
                "[%s] Chunk %d/%d — HTTP 200 OK (%.1fs) | "
                "created: +%d | updated: +%d | skipped: %d | errors: %d",
                source_name, idx, len(chunks), elapsed,
                chunk_resp.created, chunk_resp.updated,
                chunk_resp.skipped, len(chunk_resp.errors),
            )
            # Log first 5 API-level errors if any
            for err in chunk_resp.errors[:5]:
                logger.warning("[%s] Chunk %d — API error: %s", source_name, idx, err)

        except requests.exceptions.Timeout:
            elapsed = time.monotonic() - t0
            msg = f"chunk {idx}/{len(chunks)} timed out after {elapsed:.0f}s"
            logger.error("[%s] %s", source_name, msg)
            stats.errors.append(msg)

        except requests.exceptions.HTTPError as exc:
            body = exc.response.text[:300] if exc.response is not None else ""
            msg = f"chunk {idx}/{len(chunks)} HTTP {exc.response.status_code}: {body}"
            logger.error("[%s] %s", source_name, msg)
            stats.errors.append(msg)

        except Exception as exc:
            msg = f"chunk {idx}/{len(chunks)} unexpected error: {exc}"
            logger.error("[%s] %s", source_name, msg, exc_info=True)
            stats.errors.append(msg)

    logger.info(
        "[%s] TOTAL — chunks: %d | created: %d | updated: %d | skipped: %d | errors: %d",
        source_name, stats.chunks_sent,
        stats.created, stats.updated, stats.skipped, len(stats.errors),
    )
    return stats
