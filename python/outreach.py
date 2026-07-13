"""Phase 8: Gemini-based signal-specific outreach generation.

Per the original blueprint's Phase 7 design: the outreach angle depends on
signal_type (TIMING/INTENT/BOTH), computed by scoring.py. This is where
Branch C's G2 pain-point corpus (competitor_intel) and ADR-013's
current_tool_mentioned finally get used for their intended purpose - real,
specific evidence in outreach copy, not just a gating score.

Adds one field beyond the blueprint's original four outreach fields:
priority_summary - a short "why contact now" rationale synthesizing
score_breakdown into plain English for a human skimming a CRM-style sheet
(Phase 9). Added per explicit user request (2026-07-11), not blueprint scope.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "utils"))

from gemini import generate_content, parse_json_response  # noqa: E402

EXPECTED_FIELDS = [
    "priority_summary",
    "email_subject_a",
    "email_subject_b",
    "email_body",
    "linkedin_message",
    "call_script",
]

OUTPUT_CONTRACT = """Return ONLY strict JSON, no other text, in exactly this shape:
{{
  "priority_summary": "1-2 sentences on why this lead is worth contacting now, synthesizing the facts above",
  "email_subject_a": "first subject line variant",
  "email_subject_b": "second subject line variant, different angle",
  "email_body": "under 150 words, no fluff",
  "linkedin_message": "under 300 characters",
  "call_script": "3 bullet opening points, then 2 discovery questions"
}}"""

TIMING_ANGLE = """Angle: this company is at a growth inflection point. Signals observed:
{timing_facts}
Scaling the product team is the right move at this stage - the message should focus on preventing roadmap chaos as they grow, referencing the SPECIFIC facts above (don't invent details not listed)."""

INTENT_ANGLE = """Angle: this company shows active intent signals. Signals observed:
{intent_facts}
{pain_quotes_block}The message should reference these SPECIFIC facts (not generic complaints) and position Productboard as the answer, the way teams facing similar friction have found."""

BOTH_ANGLE = """Angle: this is the highest-priority lead type - both timing AND intent signals. Signals observed:
{timing_facts}
{intent_facts}
{pain_quotes_block}Combine both angles: timing urgency (they're scaling/changing now) plus proof of pain/intent (the specific evidence above). This is the strongest, most specific message of all three signal types."""

PROMPT_TEMPLATE = """You are a GTM outreach copywriter for Productboard, a product management platform. Write outreach copy for this lead:

Company: {company_name}
ICP score: {icp_score}/120

{angle}

{output_contract}"""


def _format_pain_quotes(quotes: list[dict] | None) -> str:
    if not quotes:
        return "(no specific quotes available)"
    return "\n".join(f'- "{q.get("text", "")}"' for q in quotes[:3])


def _bullet_list(facts: list[str]) -> str:
    return "\n".join(f"- {fact}" for fact in facts) if facts else "- (no specific facts identified)"


def _timing_facts(lead: dict) -> list[str]:
    """Redesign v2, Tier 1: TIMING can now fire from funding/hiring (the
    original two facts) OR from a leadership hire OR a product launch alone
    (scoring.py's score_timing() awards TIMING points for any of the four).
    Built as a list of only the facts actually present, rather than a fixed
    template assuming funding_stage/pm_job_post_count are always set - a
    lead whose only TIMING evidence is a fresh leadership hire would
    otherwise render literal "None" into the prompt."""
    facts = []
    if lead.get("funding_stage") and lead.get("funding_date"):
        facts.append(f"Raised {lead['funding_stage']} funding on {lead['funding_date']}")
    if lead.get("pm_job_post_count"):
        facts.append(f"Actively hiring for product management ({lead['pm_job_post_count']} open PM postings)")
    if lead.get("recent_product_launch"):
        facts.append(f'Just launched a new product: "{lead["recent_product_launch"]}"')
    if lead.get("new_leadership_hire"):
        facts.append(f"Recently hired new product leadership: {lead['new_leadership_hire']}")
    return facts


def _intent_facts(lead: dict) -> list[str]:
    """Redesign v2, Tier 1: INTENT can now fire from a known competitor tool
    (the original fact) OR from buying-intent language in a job posting
    alone (scoring.py's score_intent() awards INTENT points for either)."""
    facts = []
    if lead.get("current_tool_mentioned"):
        facts.append(f"Job postings mention {lead['current_tool_mentioned']} as their current product management tool")
    if lead.get("buying_intent_phrase"):
        facts.append(f'A recent job posting explicitly signals active tool evaluation: "{lead["buying_intent_phrase"]}"')
    return facts


def _pain_quotes_block(lead: dict) -> str:
    """Only relevant when a specific competitor tool is known (pain quotes
    are keyed by competitor in competitor_intel) - a lead whose only INTENT
    evidence is buying-intent language (no current_tool_mentioned) has no
    competitor to quote against, so this block is omitted entirely rather
    than rendering an empty/misleading "Real customer reviews of None"."""
    tool = lead.get("current_tool_mentioned")
    if not tool:
        return ""
    quotes = _format_pain_quotes(lead.get("competitor_pain_quotes"))
    return f"Real customer reviews of {tool} include these pain points:\n{quotes}\n"


def build_outreach_prompt(lead: dict) -> str:
    """Builds the signal-specific prompt for one lead. Raises ValueError for
    any signal_type other than TIMING/INTENT/BOTH - by the time a lead
    reaches Phase 8 (past scoring.py's >=70 threshold and Phase 7's dedupe
    check), it should never be NONE; failing loudly here catches an upstream
    bug rather than silently generating a broken/generic prompt."""
    signal_type = lead.get("signal_type")

    if signal_type == "TIMING":
        angle = TIMING_ANGLE.format(timing_facts=_bullet_list(_timing_facts(lead)))
    elif signal_type == "INTENT":
        angle = INTENT_ANGLE.format(
            intent_facts=_bullet_list(_intent_facts(lead)),
            pain_quotes_block=_pain_quotes_block(lead),
        )
    elif signal_type == "BOTH":
        angle = BOTH_ANGLE.format(
            timing_facts=_bullet_list(_timing_facts(lead)),
            intent_facts=_bullet_list(_intent_facts(lead)),
            pain_quotes_block=_pain_quotes_block(lead),
        )
    else:
        raise ValueError(f"build_outreach_prompt requires signal_type TIMING/INTENT/BOTH, got: {signal_type!r}")

    return PROMPT_TEMPLATE.format(
        company_name=lead.get("company_name"),
        icp_score=lead.get("icp_score"),
        angle=angle,
        output_contract=OUTPUT_CONTRACT,
    )


def generate_outreach(lead: dict) -> dict:
    """Full Phase 8 flow for one lead: build the signal-specific prompt,
    call Gemini, parse the structured response. Raises RuntimeError if
    Gemini's response is unparseable or missing expected fields - unlike
    classify.py's best-effort extraction, outreach copy going out to a real
    prospect must not silently degrade to partial/garbage content."""
    prompt = build_outreach_prompt(lead)
    raw_response = generate_content(prompt)
    parsed = parse_json_response(raw_response)

    if not parsed:
        raise RuntimeError(f"Gemini returned unparseable outreach content for {lead.get('company_name')!r}")

    missing = [field for field in EXPECTED_FIELDS if field not in parsed]
    if missing:
        raise RuntimeError(f"Gemini outreach response missing fields {missing} for {lead.get('company_name')!r}")

    return {field: parsed[field] for field in EXPECTED_FIELDS}
