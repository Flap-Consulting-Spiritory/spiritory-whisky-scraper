import requests
import os
from datetime import datetime

STRAPI_BASE_URL = os.environ.get("STRAPI_BASE_URL", "http://localhost:1337/api")
STRAPI_API_KEY = os.environ.get("STRAPI_API_KEY", "")

def get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if STRAPI_API_KEY:
        headers["Authorization"] = f"Bearer {STRAPI_API_KEY}"
    return headers

def fetch_bottles(
    after_id: int | None = None,
    limit: int | None = None,
    published_since: datetime | None = None,
) -> list[dict]:
    """Fetches SKUs from Strapi that have a non-null wbId.

    Args:
        after_id: If set, only fetch SKUs with id > after_id (checkpoint resume).
        limit: If set, stop fetching once this many items are collected.
        published_since: If set, only fetch SKUs published at or after this datetime.
    """
    all_items: list[dict] = []
    page_size = 100
    start = 0

    while True:
        after_filter = f"&filters[id][$gt]={after_id}" if after_id else ""
        date_filter = f"&filters[publishedAt][$gte]={published_since.isoformat()}" if published_since else ""
        url = (
            f"{STRAPI_BASE_URL}/skus"
            f"?filters[wbId][$notNull]=true"
            f"{after_filter}"
            f"{date_filter}"
            f"&pagination[limit]={page_size}"
            f"&pagination[start]={start}"
            f"&sort=id:asc"
        )
        try:
            response = requests.get(url, headers=get_headers())
            response.raise_for_status()
            body = response.json()
        except Exception as e:
            print(f"[Strapi] Error fetching SKUs (start={start}): {e}")
            break

        page = body.get("data", [])
        if not page:
            break

        all_items.extend(page)
        print(f"[Strapi] Fetched {len(all_items)} SKUs so far...")

        if limit and len(all_items) >= limit:
            break

        total = body.get("meta", {}).get("pagination", {}).get("total")
        if total is not None and len(all_items) >= total:
            break

        start += page_size

    print(f"[Strapi] Total SKUs fetched: {len(all_items)}")
    return all_items

def update_bottle(document_id: str, payload: dict) -> bool:
    """Updates a bottle in Strapi via PUT using documentId (Strapi v5)."""
    url = f"{STRAPI_BASE_URL}/skus/{document_id}"

    try:
        response = requests.put(url, json={"data": payload}, headers=get_headers())
        if not response.ok:
            raise RuntimeError(
                f"[Strapi] HTTP {response.status_code} updating {document_id}: {response.text[:500]}"
            )
        return True
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"[Strapi] Request failed for {document_id}: {e}") from e
