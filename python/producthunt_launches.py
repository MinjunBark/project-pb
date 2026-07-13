"""Redesign v2, Tier 1 (see redesign/03-creative-signal-approaches.md): a new
TIMING signal source - a target company launching a new product on Product
Hunt is a real, freely-scrapable version of the Trigger-Bot analysis's
"new product launch" trigger, which had no data source before this.

Product Hunt's GraphQL API v2 is free (verified live 2026-07-12): a free
developer token via producthunt.com/v2/oauth/applications, no paid tier gate
on read-only queries, rate limit 900 req/15min. Their default terms restrict
use to non-commercial purposes without contacting them directly - accepted
as fine for this portfolio/interview-prep project, flagged here rather than
glossed over (same honesty standard applied to every other data source's ToS
in this project - see docs/DECISIONS.md).

Real, honest uncertainty (not yet measured): Product Hunt's `name` field is a
product/brand name, not necessarily the registered legal company name in our
companies table (e.g. a product called "Acme AI" vs. a company legally named
"Acme Technologies, Inc."). This is structurally more likely to miss/duplicate
matches than Branch A/B (both of which use formal registered names) - do not
assume a match rate here, the same honest treatment already given to Branch
B's measured ~7% ATS-slug-guess hit rate (docs/ISSUES.md).
"""
import os

import requests

GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

LAUNCHES_QUERY = """
query RecentLaunches($postedAfter: DateTime!, $first: Int!) {
  posts(postedAfter: $postedAfter, first: $first, order: NEWEST) {
    edges {
      node {
        id
        name
        tagline
        url
        createdAt
      }
    }
  }
}
"""


def _headers() -> dict:
    token = os.environ.get("PRODUCT_HUNT_API_TOKEN")
    if not token:
        raise RuntimeError(
            "PRODUCT_HUNT_API_TOKEN must be set in .env - get a free developer "
            "token at https://www.producthunt.com/v2/oauth/applications"
        )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _posted_after_iso(lookback_days: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def search_recent_launches(lookback_days: int = 30, first: int = 50) -> list[dict]:
    """POST a GraphQL query for posts within the lookback window. Returns
    normalized dicts: {product_name, tagline, launched_at, url}."""
    variables = {"postedAfter": _posted_after_iso(lookback_days), "first": first}
    resp = requests.post(
        GRAPHQL_URL, headers=_headers(), json={"query": LAUNCHES_QUERY, "variables": variables}, timeout=15
    )
    resp.raise_for_status()
    data = resp.json()

    edges = ((data.get("data") or {}).get("posts") or {}).get("edges") or []
    return [
        {
            "product_name": edge["node"]["name"],
            "tagline": edge["node"].get("tagline"),
            "launched_at": edge["node"].get("createdAt"),
            "url": edge["node"].get("url"),
        }
        for edge in edges
        if edge.get("node") and edge["node"].get("name")
    ]


def get_launch_signals(lookback_days: int = 30) -> list[dict]:
    """Full Branch D flow: query, normalize, shape for the signals pipeline.

    company_name uses the product name (see module docstring's honest
    match-rate caveat) - the same field merge_signals.merge_launch_signals()
    passes to db.upsert_company() for name-based dedup/matching."""
    launches = search_recent_launches(lookback_days=lookback_days)
    return [
        {
            "company_name": launch["product_name"],
            "product_name": launch["product_name"],
            "tagline": launch["tagline"],
            "launched_at": launch["launched_at"],
            "url": launch["url"],
            "source": "producthunt",
        }
        for launch in launches
    ]
