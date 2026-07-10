"""Branch B orchestrator: Adzuna (Layer 1, broad discovery) + Greenhouse/Lever
(Layer 2, per-company deepening). See docs/DECISIONS.md ADR-010.

This is the module the rest of the pipeline calls - python/hiring_adzuna.py and
python/hiring_ats_lookup.py are the two layers underneath it.
"""
from hiring_adzuna import get_adzuna_hiring_signals
from hiring_ats_lookup import enrich_company_with_ats_data


def get_hiring_signals(keywords: list[str] | None = None, lookback_days: int = 60) -> list[dict]:
    """Full Branch B flow: Adzuna discovery, then Greenhouse/Lever deepening per company.

    When Layer 2 resolves a company's own ATS board, its richer/more current data
    wins. When it doesn't (ADR-010's documented limitation - the slug guess didn't
    match), falls back to Adzuna's own aggregated count for that company.
    """
    adzuna_candidates = get_adzuna_hiring_signals(keywords=keywords, lookback_days=lookback_days)

    signals = []
    for candidate in adzuna_candidates:
        company_name = candidate["company_name"]
        ats_result = enrich_company_with_ats_data(company_name)

        if ats_result["source"]:
            pm_postings = ats_result["pm_postings"]
            signals.append(
                {
                    "company_name": company_name,
                    "domain": None,  # resolved later by Clay, ADR-008/ADR-010
                    "employee_count": None,
                    "pm_job_post_count": len(pm_postings),
                    "job_titles": [p["title"] for p in pm_postings],
                    "most_recent_posting_date": max(
                        (p["posted_date"] for p in pm_postings if p["posted_date"]),
                        default=candidate["most_recent_posting_date"],
                    ),
                    "source": ats_result["source"],
                    "ats_matched_slug": ats_result["matched_slug"],
                }
            )
        else:
            signals.append(
                {
                    "company_name": company_name,
                    "domain": None,
                    "employee_count": None,
                    "pm_job_post_count": candidate["pm_job_post_count"],
                    "job_titles": candidate["job_titles"],
                    "most_recent_posting_date": candidate["most_recent_posting_date"],
                    "source": "adzuna",
                    "ats_matched_slug": None,
                }
            )

    return signals
