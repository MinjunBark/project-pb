"""Tests for python/full_pipeline_run.py - redesign v2, Tier 2's live-run
orchestrator. Every external call (branches, merge, leadership, scoring,
Discord) is mocked; this file only checks that the orchestrator sequences
and wires them together correctly, mirroring test_pipeline.py's own
"sequencing, not individual logic" scope."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import full_pipeline_run  # noqa: E402

COMPANY_NO_DOMAIN = {"id": 1, "name": "Acme Corp", "domain": None}
COMPANY_WITH_DOMAIN = {"id": 2, "name": "Beta Inc", "domain": "beta.com"}

NOT_QUALIFIED_RESULT = {
    "status": "not_qualified",
    "icp_score": 20,
    "company_name": "Acme Corp",
    "domain": None,
    "signal_type": "TIMING",
    "score_breakdown": {"timing": {"funding_recency": 25}},
}
PROCESSED_RESULT = {
    "status": "processed",
    "lead_id": 1,
    "hubspot_company_id": "hs-1",
    "icp_score": 90,
    "signal_type": "BOTH",
    "company_name": "Beta Inc",
    "domain": "beta.com",
    "priority_summary": "Act now.",
}

MERGE_RESULT = {
    "companies_from_funding": 1,
    "companies_from_hiring": 1,
    "competitors_updated": 0,
    "companies_from_launches": 1,
    "distinct_company_ids": 2,
}


def _mock_common(monkeypatch, companies=None, process_results=None):
    monkeypatch.setattr(full_pipeline_run.funding_edgar, "get_funding_signals", MagicMock(return_value=[{"company_name": "Acme"}]))
    monkeypatch.setattr(full_pipeline_run.hiring_signals, "get_hiring_signals", MagicMock(return_value=[{"company_name": "Beta"}]))
    monkeypatch.setattr(full_pipeline_run.producthunt_launches, "get_launch_signals", MagicMock(return_value=[{"company_name": "Gamma"}]))
    monkeypatch.setattr(full_pipeline_run.intent_g2, "get_intent_signals", MagicMock(return_value={"reviews": [{"review_id": "1"}]}))
    monkeypatch.setattr(full_pipeline_run.raw_landing, "save_raw_signals", MagicMock(return_value="data/raw/x.json"))

    mock_conn = MagicMock()
    monkeypatch.setattr(full_pipeline_run.db, "get_connection", MagicMock(return_value=mock_conn))
    monkeypatch.setattr(full_pipeline_run.merge_signals, "run_full_merge", MagicMock(return_value=MERGE_RESULT))
    monkeypatch.setattr(full_pipeline_run.db, "get_all_companies", MagicMock(return_value=companies or []))
    monkeypatch.setattr(full_pipeline_run.db, "get_all_competitor_intel", MagicMock(return_value={}))
    monkeypatch.setattr(full_pipeline_run.db, "get_signals_for_company", MagicMock(return_value=[]))
    monkeypatch.setattr(full_pipeline_run.leadership_monitor, "check_for_new_leadership", MagicMock(return_value=None))
    monkeypatch.setattr(
        full_pipeline_run.pipeline, "process_qualified_lead", MagicMock(side_effect=process_results or [])
    )
    monkeypatch.setattr(full_pipeline_run.discord, "send_progress_update", MagicMock())
    monkeypatch.setattr(full_pipeline_run.discord, "send_sdr_digest", MagicMock())
    monkeypatch.setattr(full_pipeline_run.discord, "send_clay_enrichment_request", MagicMock())

    monkeypatch.setattr(full_pipeline_run.enrichment, "process_incoming_domain_enrichment", MagicMock(return_value=[]))
    monkeypatch.setattr(
        full_pipeline_run.enrichment, "process_incoming_demographic_enrichment", MagicMock(return_value=[])
    )
    monkeypatch.setattr(full_pipeline_run.enrichment, "get_companies_needing_domain", MagicMock(return_value=[]))
    monkeypatch.setattr(full_pipeline_run.enrichment, "get_companies_needing_demographics", MagicMock(return_value=[]))
    monkeypatch.setattr(
        full_pipeline_run.enrichment, "export_companies_needing_domain", MagicMock(return_value="data/clay/x.csv")
    )
    monkeypatch.setattr(
        full_pipeline_run.enrichment,
        "export_companies_needing_demographics",
        MagicMock(return_value="data/clay/y.csv"),
    )

    return mock_conn


def test_run_full_cycle_runs_branch_a_b_d_but_not_c_by_default(monkeypatch):
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    full_pipeline_run.run_full_cycle()

    full_pipeline_run.funding_edgar.get_funding_signals.assert_called_once()
    full_pipeline_run.hiring_signals.get_hiring_signals.assert_called_once()
    full_pipeline_run.producthunt_launches.get_launch_signals.assert_called_once()
    full_pipeline_run.intent_g2.get_intent_signals.assert_not_called()


def test_run_full_cycle_includes_branch_c_when_opted_in(monkeypatch):
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    result = full_pipeline_run.run_full_cycle(include_branch_c=True, branch_c_competitors={"Aha!": "aha"})

    full_pipeline_run.intent_g2.get_intent_signals.assert_called_once_with(competitors={"Aha!": "aha"})
    assert result["branch_c_count"] == 1


def test_run_full_cycle_derives_branch_c_competitors_from_branch_b_mentions(monkeypatch):
    """Redesign v2, Tier 3: Branch C should be demand-driven by what Branch
    B actually found this run, not always scrape the fixed default 4 -
    confirms only the mentioned (and tracked) competitors are passed
    through, spanning mentions across multiple companies."""
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.hiring_signals,
        "get_hiring_signals",
        MagicMock(
            return_value=[
                {"company_name": "Beta", "current_tools_mentioned": ["Jira Product Discovery"]},
                {"company_name": "Gamma", "current_tools_mentioned": ["Craft.io", "Jira Product Discovery"]},
                {"company_name": "Delta", "current_tools_mentioned": []},
            ]
        ),
    )

    full_pipeline_run.run_full_cycle(include_branch_c=True)

    full_pipeline_run.intent_g2.get_intent_signals.assert_called_once_with(
        competitors={"Jira Product Discovery": "jira-product-discovery", "Craft.io": "craft-io-craft-io"}
    )


def test_run_full_cycle_skips_branch_c_when_no_tracked_competitors_mentioned(monkeypatch):
    """The actual point of 'demand-driven': don't spend real Apify money
    scraping competitors nobody mentioned this run. An untracked tool name
    (not one of the 4 known competitors) must not accidentally trigger a
    scrape either."""
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.hiring_signals,
        "get_hiring_signals",
        MagicMock(return_value=[{"company_name": "Beta", "current_tools_mentioned": ["Some Untracked Tool"]}]),
    )

    full_pipeline_run.run_full_cycle(include_branch_c=True)

    full_pipeline_run.intent_g2.get_intent_signals.assert_not_called()
    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    assert any("Branch C included but skipped" in m for m in messages)


def test_run_full_cycle_explicit_branch_c_competitors_overrides_derived_set(monkeypatch):
    """A caller-supplied branch_c_competitors must win over whatever Branch
    B happened to find this run - preserves the ability to force a
    specific set regardless of real-time discovery."""
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.hiring_signals,
        "get_hiring_signals",
        MagicMock(return_value=[{"company_name": "Beta", "current_tools_mentioned": ["Aha!"]}]),
    )

    full_pipeline_run.run_full_cycle(include_branch_c=True, branch_c_competitors={"ProductPlan": "productplan"})

    full_pipeline_run.intent_g2.get_intent_signals.assert_called_once_with(competitors={"ProductPlan": "productplan"})


def test_run_full_cycle_posts_progress_after_each_phase(monkeypatch):
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    full_pipeline_run.run_full_cycle()

    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    joined = " | ".join(messages)
    assert "Starting full pipeline run" in joined
    assert "Branch A" in joined
    assert "Branch B" in joined
    assert "Branch D" in joined
    assert "Branch C skipped" in joined
    assert "Merge complete" in joined
    assert "Leadership check" in joined
    assert "Scoring + outreach complete" in joined
    assert "complete" in messages[-1].lower()


def test_run_full_cycle_captures_full_processed_results_not_just_counts(monkeypatch):
    _mock_common(
        monkeypatch,
        companies=[COMPANY_NO_DOMAIN, COMPANY_WITH_DOMAIN],
        process_results=[NOT_QUALIFIED_RESULT, PROCESSED_RESULT],
    )

    result = full_pipeline_run.run_full_cycle()

    assert result["qualified_count"] == 1
    full_pipeline_run.discord.send_sdr_digest.assert_called_once()
    (sent_summary,), _ = full_pipeline_run.discord.send_sdr_digest.call_args
    assert sent_summary["qualified_leads"] == [PROCESSED_RESULT]
    assert sent_summary["qualified_leads"][0]["company_name"] == "Beta Inc"
    assert sent_summary["qualified_leads"][0]["priority_summary"] == "Act now."


def test_run_full_cycle_only_checks_leadership_for_domain_having_companies(monkeypatch):
    mock_check = MagicMock(return_value=None)
    mock_conn = _mock_common(
        monkeypatch,
        companies=[COMPANY_NO_DOMAIN, COMPANY_WITH_DOMAIN],
        process_results=[NOT_QUALIFIED_RESULT, NOT_QUALIFIED_RESULT],
    )
    monkeypatch.setattr(full_pipeline_run.leadership_monitor, "check_for_new_leadership", mock_check)

    full_pipeline_run.run_full_cycle()

    mock_check.assert_called_once_with(mock_conn, COMPANY_WITH_DOMAIN["id"], COMPANY_WITH_DOMAIN["domain"])


def test_run_full_cycle_closes_db_connection(monkeypatch):
    mock_conn = _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    full_pipeline_run.run_full_cycle()

    mock_conn.close.assert_called_once()


def test_run_full_cycle_posts_failure_and_reraises_on_branch_error(monkeypatch):
    monkeypatch.setattr(
        full_pipeline_run.funding_edgar, "get_funding_signals", MagicMock(side_effect=RuntimeError("EDGAR is down"))
    )
    monkeypatch.setattr(full_pipeline_run.discord, "send_progress_update", MagicMock())

    with pytest.raises(RuntimeError, match="EDGAR is down"):
        full_pipeline_run.run_full_cycle()

    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    assert any("❌" in m and "Branch A" in m for m in messages)


def test_run_full_cycle_closes_connection_even_when_a_later_phase_fails(monkeypatch):
    """The DB connection is opened before merge/leadership/scoring and must
    still be closed if one of those later phases raises - a leaked
    connection on every failed live run would be a real, accumulating bug."""
    mock_conn = _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.merge_signals, "run_full_merge", MagicMock(side_effect=RuntimeError("merge failed"))
    )

    with pytest.raises(RuntimeError, match="merge failed"):
        full_pipeline_run.run_full_cycle()

    mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# Redesign v2, Tier 3: digest watchlist + run-query logging
# ---------------------------------------------------------------------------


def test_run_full_cycle_builds_watchlist_from_non_qualified_results_sorted_by_score(monkeypatch):
    low = {**NOT_QUALIFIED_RESULT, "company_name": "Low Co", "icp_score": 10}
    high = {**NOT_QUALIFIED_RESULT, "company_name": "High Co", "icp_score": 45}
    mid = {**NOT_QUALIFIED_RESULT, "company_name": "Mid Co", "icp_score": 30}
    companies = [{"id": 1, "name": "Low Co", "domain": None}, {"id": 2, "name": "High Co", "domain": None}, {"id": 3, "name": "Mid Co", "domain": None}]
    _mock_common(monkeypatch, companies=companies, process_results=[low, high, mid])

    full_pipeline_run.run_full_cycle()

    (sent_summary,), _ = full_pipeline_run.discord.send_sdr_digest.call_args
    watchlist_names = [w["company_name"] for w in sent_summary["watchlist"]]
    assert watchlist_names == ["High Co", "Mid Co", "Low Co"]


def test_run_full_cycle_watchlist_excludes_processed_leads(monkeypatch):
    companies = [COMPANY_NO_DOMAIN, COMPANY_WITH_DOMAIN]
    _mock_common(monkeypatch, companies=companies, process_results=[NOT_QUALIFIED_RESULT, PROCESSED_RESULT])

    full_pipeline_run.run_full_cycle()

    (sent_summary,), _ = full_pipeline_run.discord.send_sdr_digest.call_args
    watchlist_names = [w["company_name"] for w in sent_summary["watchlist"]]
    assert "Beta Inc" not in watchlist_names  # PROCESSED_RESULT's company - already qualified, not a "prospect to watch"
    assert sent_summary["qualified_leads"][0]["company_name"] == "Beta Inc"


def test_run_full_cycle_watchlist_capped_at_watchlist_size(monkeypatch):
    companies = [{"id": i, "name": f"Co {i}", "domain": None} for i in range(full_pipeline_run.WATCHLIST_SIZE + 5)]
    results = [{**NOT_QUALIFIED_RESULT, "company_name": f"Co {i}", "icp_score": i} for i in range(len(companies))]
    _mock_common(monkeypatch, companies=companies, process_results=results)

    full_pipeline_run.run_full_cycle()

    (sent_summary,), _ = full_pipeline_run.discord.send_sdr_digest.call_args
    assert len(sent_summary["watchlist"]) == full_pipeline_run.WATCHLIST_SIZE


def test_run_full_cycle_lands_a_run_query_log(monkeypatch):
    """The 'learn from every scrape' record - confirms a run_log gets
    landed via the same raw_landing convention every branch already uses,
    with real per-branch query detail (not just aggregate counts)."""
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.hiring_signals,
        "get_hiring_signals",
        MagicMock(
            return_value=[
                {
                    "company_name": "Beta",
                    "source": "greenhouse",
                    "ats_matched_slug": "beta",
                    "current_tools_mentioned": ["Jira Product Discovery"],
                    "buying_intent": {"buying_intent_detected": True, "matched_phrase": "evaluate our stack"},
                }
            ]
        ),
    )

    result = full_pipeline_run.run_full_cycle()

    run_log_calls = [
        call for call in full_pipeline_run.raw_landing.save_raw_signals.call_args_list if call.args[0] == "run_log"
    ]
    assert len(run_log_calls) == 1
    logged = run_log_calls[0].args[1]
    assert logged["branch_a"]["count"] == 1
    assert logged["branch_b"]["companies"][0] == {
        "company_name": "Beta",
        "ats_source": "greenhouse",
        "matched_slug": "beta",
        "current_tools_mentioned": ["Jira Product Discovery"],
        "buying_intent_detected": True,
    }
    assert logged["branch_c"] == {"included": False, "skipped_reason": "opt-in only, ADR-009"}
    assert logged["scoring"] == [{"company_name": "Acme Corp", "icp_score": 20, "signal_type": "TIMING"}]
    assert "run_log_path" in result


# ---------------------------------------------------------------------------
# Redesign v2, Tier 5: Clay human-in-the-loop pickup/request + auto-resume
# ---------------------------------------------------------------------------


def test_run_full_cycle_picks_up_clay_enrichment_before_scoring(monkeypatch):
    """Pickup must run before the scoring phase so anything dropped back
    since the last run benefits THIS run's scoring, not the next one."""
    mock_conn = _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.enrichment, "process_incoming_domain_enrichment", MagicMock(return_value=[1, 2])
    )

    full_pipeline_run.run_full_cycle()

    full_pipeline_run.enrichment.process_incoming_domain_enrichment.assert_called_once_with(mock_conn)
    full_pipeline_run.enrichment.process_incoming_demographic_enrichment.assert_called_once_with(mock_conn)
    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    assert any("Clay enrichment picked up: 2 companies" in m for m in messages)


def test_run_full_cycle_does_not_announce_pickup_when_nothing_was_picked_up(monkeypatch):
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    full_pipeline_run.run_full_cycle()

    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    assert not any("Clay enrichment picked up" in m for m in messages)


def test_run_full_cycle_requests_clay_enrichment_for_non_empty_queues(monkeypatch):
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.enrichment,
        "get_companies_needing_domain",
        MagicMock(return_value=[{"company_id": 1, "company_name": "Acme"}]),
    )

    full_pipeline_run.run_full_cycle()

    full_pipeline_run.discord.send_clay_enrichment_request.assert_called_once_with("domain", 1, "data/clay/x.csv")


def test_run_full_cycle_skips_clay_request_for_empty_queues(monkeypatch):
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    full_pipeline_run.run_full_cycle()

    full_pipeline_run.discord.send_clay_enrichment_request.assert_not_called()


def test_run_full_cycle_excludes_demographics_request_when_opted_out(monkeypatch):
    """The new include_demographics_enrichment=False toggle - domain
    requests still fire normally, but demographics is skipped entirely,
    even though its queue is non-empty, and the skip is logged (not
    silent) - mirrors how a Branch C skip is already logged."""
    _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])
    monkeypatch.setattr(
        full_pipeline_run.enrichment,
        "get_companies_needing_domain",
        MagicMock(return_value=[{"company_id": 1, "company_name": "Acme"}]),
    )
    monkeypatch.setattr(
        full_pipeline_run.enrichment,
        "get_companies_needing_demographics",
        MagicMock(return_value=[{"company_id": 1, "company_name": "Acme", "domain": "acme.com"}]),
    )

    full_pipeline_run.run_full_cycle(include_demographics_enrichment=False)

    full_pipeline_run.discord.send_clay_enrichment_request.assert_called_once_with("domain", 1, "data/clay/x.csv")
    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    assert any("demographics enrichment request skipped" in m for m in messages)


def test_run_full_cycle_still_picks_up_demographics_when_opted_out_of_requesting(monkeypatch):
    """Excluding the demographics REQUEST must not disable demographics
    PICKUP - anything the user already dropped back should still be
    imported and benefit this run's scoring, regardless of whether a new
    request goes out this time."""
    mock_conn = _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[NOT_QUALIFIED_RESULT])

    full_pipeline_run.run_full_cycle(include_demographics_enrichment=False)

    full_pipeline_run.enrichment.process_incoming_demographic_enrichment.assert_called_once_with(mock_conn)


def test_resume_after_enrichment_returns_none_when_nothing_picked_up(monkeypatch):
    mock_conn = _mock_common(monkeypatch, companies=[COMPANY_NO_DOMAIN], process_results=[])

    result = full_pipeline_run.resume_after_enrichment()

    assert result is None
    full_pipeline_run.discord.send_sdr_digest.assert_not_called()
    mock_conn.close.assert_called_once()


def test_resume_after_enrichment_finishes_the_run_when_something_was_picked_up(monkeypatch):
    """Auto-resume must run the same real leadership/scoring/digest logic a
    fresh full run does - not a shortcut/partial version - so the two paths
    can never silently drift apart."""
    mock_conn = _mock_common(
        monkeypatch, companies=[COMPANY_WITH_DOMAIN], process_results=[PROCESSED_RESULT]
    )
    monkeypatch.setattr(
        full_pipeline_run.enrichment, "process_incoming_domain_enrichment", MagicMock(return_value=[2])
    )

    result = full_pipeline_run.resume_after_enrichment()

    assert result["qualified_count"] == 1
    full_pipeline_run.pipeline.process_qualified_lead.assert_called_once()
    full_pipeline_run.discord.send_sdr_digest.assert_called_once()
    messages = [call.args[0] for call in full_pipeline_run.discord.send_progress_update.call_args_list]
    assert any("New Clay enrichment detected" in m for m in messages)
    mock_conn.close.assert_called_once()
