"""Phase 4 (scoring) + Phase 9 (n8n-facing pipeline endpoints).

Run locally with: uvicorn api.main:app --reload

n8n's workflow (built by the user in the UI, ADR-007) calls these endpoints
in sequence rather than reimplementing any of the underlying logic itself -
every endpoint here is a thin wrapper around already-tested Python
(funding_edgar, hiring_signals, intent_g2, merge_signals, pipeline), so
every real bug fix made across this session's development stays in force.
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

# Every other script in this session called load_dotenv() explicitly before
# touching any credential-reading function - this was the one place that
# didn't, and a real live test running uvicorn standalone caught it
# immediately (EDGAR_USER_AGENT missing -> RuntimeError). Must run before
# any of the sys.path-imported modules below actually get CALLED (not
# necessarily before they're imported, since they read os.environ lazily
# inside functions, but placing it first is the safest convention).
load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

import db  # noqa: E402
import discord_bot  # noqa: E402
import discord_webhooks as discord  # noqa: E402
import full_pipeline_run  # noqa: E402
import funding_edgar  # noqa: E402
import hiring_signals  # noqa: E402
import intent_g2  # noqa: E402
import leadership_monitor  # noqa: E402
import merge_signals  # noqa: E402
import pipeline  # noqa: E402
import producthunt_launches  # noqa: E402
import raw_landing  # noqa: E402
from scoring import score_company  # noqa: E402

app = FastAPI(title="GTM Signal Engine API")

# Redesign v2, Tier 5: how often the background poller checks
# data/clay/incoming_*/ for a manually dropped-back enriched CSV. 60s is
# more than fast enough for a human-paced manual workflow (the user is not
# going to drop the file and expect sub-second pickup) and cheap enough
# (a couple of os.listdir calls + a no-op DB query when nothing's there) to
# run indefinitely alongside the app.
CLAY_POLL_INTERVAL_SECONDS = 60


@app.on_event("startup")
async def _start_clay_enrichment_poller() -> None:
    """Redesign v2, Tier 5: launches the automatic-resume background loop
    inside this already-required uvicorn process - no separate bot/process.
    Runs full_pipeline_run.resume_after_enrichment() (a blocking, synchronous
    function using requests/psycopg2) via asyncio.to_thread() so it never
    blocks the event loop. A single bad iteration (e.g. a transient DB or
    Discord hiccup) is posted to ops-progress and the loop keeps going -
    unlike _run_phase's fail-loud policy for a foreground run the user is
    actively watching, an unattended poller must not die permanently from
    one failure."""

    async def _poll_loop() -> None:
        while True:
            await asyncio.sleep(CLAY_POLL_INTERVAL_SECONDS)
            try:
                await asyncio.to_thread(full_pipeline_run.resume_after_enrichment)
            except Exception as exc:
                try:
                    discord.send_progress_update(f"❌ Clay enrichment auto-resume poll failed: {exc}")
                except Exception:
                    pass

    asyncio.create_task(_poll_loop())

    # Redesign v2, Tier 6: the faster, more natural counterpart to the
    # poller above - a real Discord bot watching #clay-enrichment for the
    # user's uploaded CSV directly, instead of requiring a local file drop.
    # Returns None (does nothing) if DISCORD_BOT_TOKEN/DISCORD_CLAY_CHANNEL_ID
    # aren't configured yet - the poller above still works fully
    # independently either way.
    discord_bot.create_bot_task()


class CompanyIn(BaseModel):
    funding_stage: str | None = None
    funding_date: str | None = None
    employee_count: int | None = None
    is_saas: bool | None = None
    is_existing_customer: bool = False
    current_tool_mentioned: str | None = None


class SignalIn(BaseModel):
    signal_category: str
    raw_text: str | None = None
    posted_at: str | None = None
    created_at: str | None = None


class CompetitorIntelIn(BaseModel):
    switch_signal_count: int
    total_reviews_seen: int


class ScoreRequest(BaseModel):
    company: CompanyIn
    signals: list[SignalIn] = []
    competitor_intel: dict[str, CompetitorIntelIn] = {}


class ScoreResponse(BaseModel):
    icp_score: int
    qualified: bool
    signal_type: str
    score_breakdown: dict


class BranchARequest(BaseModel):
    keywords: list[str] | None = None
    lookback_days: int = 90


class BranchBRequest(BaseModel):
    keywords: list[str] | None = None
    lookback_days: int = 60


class BranchCRequest(BaseModel):
    competitors: dict[str, str] | None = None
    max_reviews_per_competitor: int = 100


class BranchDRequest(BaseModel):
    lookback_days: int = 30


class BranchRunResponse(BaseModel):
    count: int
    landed_path: str


class MergeResponse(BaseModel):
    companies_from_funding: int
    companies_from_hiring: int
    competitors_updated: int
    companies_from_launches: int
    distinct_company_ids: int


class RunAllRequest(BaseModel):
    dedup_window_days: int = pipeline.DEFAULT_DEDUP_WINDOW_DAYS


class RunFullCycleRequest(BaseModel):
    include_branch_c: bool = False
    branch_c_competitors: dict[str, str] | None = None
    dedup_window_days: int = pipeline.DEFAULT_DEDUP_WINDOW_DAYS
    include_enrichment_request: bool = True


class RunFullCycleResponse(BaseModel):
    companies_evaluated: int
    qualified_count: int
    branch_a_count: int
    branch_b_count: int
    branch_d_count: int
    branch_c_count: int | None = None
    merge_result: dict
    leadership_companies_checked: int
    leadership_new_hires_found: int
    run_log_path: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/score", response_model=ScoreResponse)
def score(request: ScoreRequest) -> dict:
    company = request.company.model_dump()
    signals = [s.model_dump() for s in request.signals]
    competitor_intel = {name: intel.model_dump() for name, intel in request.competitor_intel.items()}

    return score_company(company, signals, competitor_intel)


@app.post("/branch-a/run", response_model=BranchRunResponse)
def branch_a_run(request: BranchARequest) -> dict:
    """Free, safe for a daily schedule. SEC EDGAR has no API key/cost limit."""
    signals = funding_edgar.get_funding_signals(keywords=request.keywords, lookback_days=request.lookback_days)
    path = raw_landing.save_raw_signals("branch_a", signals)
    return {"count": len(signals), "landed_path": path}


@app.post("/branch-b/run", response_model=BranchRunResponse)
def branch_b_run(request: BranchBRequest) -> dict:
    """Free, safe for a daily schedule. Adzuna + Greenhouse/Lever, no paid API."""
    signals = hiring_signals.get_hiring_signals(keywords=request.keywords, lookback_days=request.lookback_days)
    path = raw_landing.save_raw_signals("branch_b", signals)
    return {"count": len(signals), "landed_path": path}


@app.post("/branch-c/run", response_model=BranchRunResponse)
def branch_c_run(request: BranchCRequest) -> dict:
    """COSTS REAL APIFY MONEY per call (ADR-009). Wire this to a separate,
    less-frequent n8n trigger than the free daily A/B schedule - the
    accumulate-don't-replace redesign (ADR-021) makes it safe to run
    periodically without losing prior data, but each call still has a real
    cost, so it should not fire on the same schedule as the free branches."""
    result = intent_g2.get_intent_signals(
        competitors=request.competitors, max_reviews_per_competitor=request.max_reviews_per_competitor
    )
    path = raw_landing.save_raw_signals("branch_c", result)
    return {"count": len(result["reviews"]), "landed_path": path}


@app.post("/branch-d/run", response_model=BranchRunResponse)
def branch_d_run(request: BranchDRequest) -> dict:
    """Redesign v2, Tier 1. Free (Product Hunt developer token, verified live
    2026-07-12 - see python/producthunt_launches.py). Non-commercial-use ToS
    caveat noted and accepted for this portfolio project."""
    signals = producthunt_launches.get_launch_signals(lookback_days=request.lookback_days)
    path = raw_landing.save_raw_signals("branch_d", signals)
    return {"count": len(signals), "landed_path": path}


@app.post("/merge/run", response_model=MergeResponse)
def merge_run() -> dict:
    """Merges the most recently landed raw file from each branch into
    Postgres. Reloads from python/raw_landing.py's local landing zone."""
    conn = db.get_connection()
    try:
        return merge_signals.run_full_merge(conn)
    finally:
        conn.close()


@app.post("/leadership/run")
def leadership_run() -> dict:
    """Redesign v2, Tier 1 - EXPLICIT EXCEPTION to every other branch
    endpoint's convention (they only land raw JSON, never touch Postgres
    directly). This one writes directly to the database because it needs
    durable snapshot state (company_leadership_snapshots) to diff against on
    the NEXT run - a one-shot land-then-merge flow doesn't support that.
    Only processes companies with a known domain (see leadership_monitor.py's
    module docstring on that real, load-bearing limitation)."""
    conn = db.get_connection()
    try:
        companies = [c for c in db.get_all_companies(conn) if c.get("domain")]
        results = [
            leadership_monitor.check_for_new_leadership(conn, c["id"], c["domain"]) for c in companies
        ]
        return {"companies_checked": len(companies), "new_hires_found": sum(1 for r in results if r)}
    finally:
        conn.close()


@app.post("/pipeline/run-all")
def pipeline_run_all(request: RunAllRequest) -> dict:
    """Scores every company currently in Postgres and batch-processes
    whoever qualifies (respecting the dedup window, ADR from 2026-07-12) -
    the n8n workflow's final step after branch runs + merge."""
    conn = db.get_connection()
    try:
        competitor_intel = db.get_all_competitor_intel(conn)
        companies = db.get_all_companies(conn)

        status_counts: dict[str, int] = {}
        for company in companies:
            signals = db.get_signals_for_company(conn, company["id"])
            result = pipeline.process_qualified_lead(
                conn, company, signals, competitor_intel, dedup_window_days=request.dedup_window_days
            )
            status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1

        return {"companies_evaluated": len(companies), "status_counts": status_counts}
    finally:
        conn.close()


@app.post("/pipeline/run-full-cycle", response_model=RunFullCycleResponse)
def pipeline_run_full_cycle(request: RunFullCycleRequest) -> dict:
    """Redesign v2, Tier 2: the single 'run everything live with Discord
    visibility' entry point - calls python/full_pipeline_run.py's
    run_full_cycle() in-process (not by re-calling this API's own other
    endpoints over HTTP - see full_pipeline_run.py's module docstring for
    why). Branch C is opt-in only (ADR-009). Posts progress to the
    ops-progress Discord channel throughout, and a final digest to the
    sdr-digest channel."""
    return full_pipeline_run.run_full_cycle(
        include_branch_c=request.include_branch_c,
        branch_c_competitors=request.branch_c_competitors,
        dedup_window_days=request.dedup_window_days,
        include_enrichment_request=request.include_enrichment_request,
    )


class ResumeAfterEnrichmentRequest(BaseModel):
    dedup_window_days: int = pipeline.DEFAULT_DEDUP_WINDOW_DAYS


@app.post("/pipeline/resume-after-enrichment")
def pipeline_resume_after_enrichment(request: ResumeAfterEnrichmentRequest) -> dict:
    """Redesign v2, Tier 5: manual/on-demand version of the same
    auto-resume check the background poller runs every 60s (see
    _start_clay_enrichment_poller above) - lets the user trigger an
    immediate check instead of waiting for the next poll tick. Returns
    {"resumed": false} when nothing new was found in data/clay/incoming_*/,
    or the real run summary when a resume actually happened."""
    result = full_pipeline_run.resume_after_enrichment(dedup_window_days=request.dedup_window_days)
    if result is None:
        return {"resumed": False}
    return {"resumed": True, **result}
