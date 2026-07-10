"""Branch C (intent signal): competitor G2 reviews, via the Apify actor
automation-lab/g2-scraper (see docs/DECISIONS.md ADR-012).

Per ADR-009, Claude writes and mock-tests this code but does not run live Apify
calls - the user tests live to manage their own Apify usage.

Design note (ADR-012): G2 reviews are anonymous by design - this actor's reviewer
fields are name, country, region, company-size segment, and industry code, NOT a
company name. Most reviews can't be attached to a specific company the way Branch
A/B signals can. So this module has two jobs, not one:
  1. Normalize raw reviews (company attribution, when a review's free text happens
     to name the reviewer's employer, is a Phase 5 Gemini classification job, not
     attempted here with brittle regex).
  2. Build an aggregated per-competitor pain-point corpus - the primary value -
     which feeds Phase 8's outreach generation with real customer language.
"""
import os
import time

import requests

ACTOR_ID = "automation-lab~g2-scraper"
RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"

# Confirmed 2026-07-09 against real G2 URLs (g2.com/products/{slug}/reviews).
# Craft.io's slug has a duplicated segment ("craft-io-craft-io") - a real G2 URL
# quirk, not a typo, likely from a historical name-collision disambiguation.
DEFAULT_COMPETITORS = {
    "Aha!": "aha",
    "Jira Product Discovery": "jira-product-discovery",
    "ProductPlan": "productplan",
    "Craft.io": "craft-io-craft-io",
}

NEGATIVE_STAR_THRESHOLD = 3
REQUEST_DELAY_SECONDS = 0.5


def build_product_review_url(product_slug: str) -> str:
    """The actor's documented examples pass full G2 URLs via `productUrls`,
    not bare slugs - see docs/ISSUES.md for the field-name research that
    corrected this."""
    return f"https://www.g2.com/products/{product_slug}/reviews"


def run_g2_review_scraper(product_slug: str, max_reviews: int = 100) -> list[dict]:
    """Call the Apify actor for one competitor's reviews. Live network call -
    not exercised in tests; user runs the first real call manually (ADR-009)."""
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN must be set in .env")

    resp = requests.post(
        RUN_SYNC_URL,
        params={"token": token},
        json={
            "mode": "product_reviews",
            "productUrls": [build_product_review_url(product_slug)],
            "maxReviews": max_reviews,
            "sortReviews": "newest",
        },
        timeout=120,
    )
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp.json()


def normalize_g2_reviews(raw_reviews: list[dict], competitor_name: str) -> list[dict]:
    """Normalize raw actor output into a clean per-review shape, tagged with
    which competitor it's about. Does not attempt company attribution - that's
    a Phase 5 Gemini classification job (ADR-012).

    Field names below match the actor's actual documented output (confirmed
    2026-07-09 - see docs/ISSUES.md), not an earlier, less precise research pass."""
    normalized = []
    for review in raw_reviews:
        star_rating = review.get("starRating")
        normalized.append(
            {
                "review_id": review.get("reviewId"),
                "title": review.get("title"),
                "text": review.get("reviewText"),
                "star_rating": star_rating,
                "nps_score": review.get("nps"),
                "posted_date": review.get("publishedAt") or review.get("submittedAt"),
                "love_theme": review.get("loveTheme"),
                "hate_theme": review.get("hateTheme"),
                # switchedFromOtherProduct is a "yes"/"no"/"unknown" flag, NOT a
                # product name (confirmed 2026-07-10 against real data - see
                # docs/ISSUES.md). The actual prior product, when mentioned, is
                # embedded in free text (switch_reason/text) - a Phase 5 Gemini
                # extraction job, not a structured field this actor provides.
                "switched_from_other_product": review.get("switchedFromOtherProduct") == "yes",
                "switch_reason": review.get("switchedReason"),
                "reviewer_country": review.get("country"),
                "reviewer_segment": review.get("companySegment"),
                "reviewer_industry": review.get("industry"),
                "is_negative": star_rating is not None and star_rating <= NEGATIVE_STAR_THRESHOLD,
                "is_switch_signal": review.get("switchedFromOtherProduct") == "yes",
                "competitor": competitor_name,
                "url": review.get("url"),
                "source": "g2",
            }
        )
    return normalized


def build_pain_point_corpus(normalized_reviews: list[dict]) -> dict:
    """Aggregate negative/switch-signal reviews per competitor - the primary
    deliverable of this branch (ADR-012). This becomes reference content for
    Phase 8's outreach generation, not a per-company lead signal."""
    corpus: dict[str, dict] = {}

    for review in normalized_reviews:
        competitor = review["competitor"]
        if competitor not in corpus:
            corpus[competitor] = {
                "competitor": competitor,
                "total_reviews_seen": 0,
                "negative_review_count": 0,
                "switch_signal_count": 0,
                "representative_quotes": [],
            }

        entry = corpus[competitor]
        entry["total_reviews_seen"] += 1
        if review["is_negative"]:
            entry["negative_review_count"] += 1
        if review["is_switch_signal"]:
            entry["switch_signal_count"] += 1
            if review["text"]:
                entry["representative_quotes"].append(
                    {
                        "text": review["text"][:400],
                        "switch_reason": review["switch_reason"],
                        "star_rating": review["star_rating"],
                    }
                )

    return corpus


def get_intent_signals(
    competitors: dict[str, str] | None = None, max_reviews_per_competitor: int = 100
) -> dict:
    """Full Branch C flow: scrape each competitor's reviews, normalize, and build
    the pain-point corpus. Returns {"reviews": [...], "pain_point_corpus": {...}}."""
    competitors = competitors or DEFAULT_COMPETITORS

    all_reviews = []
    for competitor_name, slug in competitors.items():
        raw_reviews = run_g2_review_scraper(slug, max_reviews=max_reviews_per_competitor)
        all_reviews.extend(normalize_g2_reviews(raw_reviews, competitor_name))

    return {
        "reviews": all_reviews,
        "pain_point_corpus": build_pain_point_corpus(all_reviews),
    }
