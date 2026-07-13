"""Phase 5: Gemini-based classification. Currently one job - the piece
explicitly deferred in intent_g2.py's docstring (ADR-012): when a G2
review's free text happens to name the reviewer's employer, extract it, so
that rare review can flow into the normal per-company signal pipeline
(eligible for scoring.py's INTENT points and the BOTH-signal bonus) instead
of only ever counting toward the aggregate pain-point corpus.

Deliberately NOT attempted with regex - company names in free text vary too
much (legal suffixes, abbreviations, "my company", no mention at all) for a
brittle pattern match to be reliable. This is exactly the kind of nuanced
extraction an LLM is suited for and regex isn't.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

from gemini import generate_content
from gemini import parse_json_response as _parse_json_response  # noqa: E402

COMPANY_EXTRACTION_PROMPT_TEMPLATE = """You are analyzing a software product review. Most reviewers do NOT name their employer - only extract a company name if it is explicitly and unambiguously stated in the text (e.g. "we use this at Acme Corp", "our team at Acme adopted this"). Do not guess, do not infer from context, do not treat the product being reviewed as the company name.

Review text:
{review_text}

Return ONLY strict JSON, no other text, in exactly this shape:
{{"company_name": "the exact company name as written" or null}}"""


def build_company_extraction_prompt(review_text: str) -> str:
    return COMPANY_EXTRACTION_PROMPT_TEMPLATE.format(review_text=review_text)


def extract_reviewer_company(review_text: str | None) -> str | None:
    """Best-effort: ask Gemini if this review's text names the reviewer's
    employer. Returns the company name, or None (the common case)."""
    if not review_text or not review_text.strip():
        return None

    raw_response = generate_content(build_company_extraction_prompt(review_text))
    parsed = _parse_json_response(raw_response)
    if not parsed:
        return None

    return parsed.get("company_name") or None


def classify_reviews_for_company_attribution(reviews: list[dict]) -> list[dict]:
    """Run extract_reviewer_company() over a batch of normalized G2 reviews
    (python/intent_g2.py's output shape). Returns the same reviews with an
    added `attributed_company` field - None for the large majority."""
    return [{**review, "attributed_company": extract_reviewer_company(review.get("text"))} for review in reviews]
