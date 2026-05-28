"""
HTTP pagination helpers para extracción de fuentes ETL.
Reutilizado por los endpoints de sincronización manual (/sync/run/*).
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

_PER_PAGE = 100
_MAX_WORKERS = 5


def fetch_collecta_page(url: str, headers: dict, page: int) -> tuple[list[dict], int]:
    resp = requests.get(url, headers=headers,
                        params={"page": page, "per_page": _PER_PAGE}, timeout=30)
    resp.raise_for_status()
    block = resp.json().get("result", {})
    return block.get("data", []), block.get("last_page", 1)


def fetch_datasefil_page(url: str, headers: dict, page: int) -> tuple[list[dict], int]:
    resp = requests.get(url, headers=headers,
                        params={"page": page, "per_page": _PER_PAGE}, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    return body.get("data", []), body.get("last_page", 1)


def fetch_all_pages(fetch_fn, url: str, headers: dict, label: str) -> list[dict]:
    """Descarga todas las páginas en paralelo. Retorna lista vacía si falla la primera."""
    try:
        first_records, last_page = fetch_fn(url, headers, 1)
    except Exception as exc:
        logger.error("[%s] Cannot fetch page 1: %s", label, exc)
        return []

    logger.info("[%s] %d page(s) to download (per_page=%d)", label, last_page, _PER_PAGE)
    all_records = list(first_records)

    if last_page > 1:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            futures = {
                executor.submit(fetch_fn, url, headers, p): p
                for p in range(2, last_page + 1)
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    records, _ = future.result()
                    all_records.extend(records)
                except Exception as exc:
                    logger.warning("[%s] Error on page %d: %s", label, page_num, exc)

    logger.info("[%s] %d total records downloaded.", label, len(all_records))
    return all_records
