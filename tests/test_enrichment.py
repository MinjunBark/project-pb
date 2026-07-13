"""Tests for python/enrichment.py's Clay "Company Enrichment" round-trip
(Phase 6, ADR-017). Consolidated 2026-07-13 from two separate round-trips
(domain-only, demographics-only) into one - Clay's real "Company
Enrichment" waterfall already returns domain (via Website) + employee
count + industry together in a single pass. Postgres calls are mocked
throughout."""
import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock

import psycopg2.errors
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import enrichment  # noqa: E402


def test_get_companies_needing_enrichment_maps_rows_to_dicts():
    """Confirms the raw (id, name, domain) tuples psycopg2 returns get
    mapped to the company_id/company_name/domain dict shape the rest of
    this module (and Clay's CSV import) expects."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [(1, "Acme Corp", None), (2, "Beta Inc", "beta.com")]

    result = enrichment.get_companies_needing_enrichment(mock_conn)

    assert result == [
        {"company_id": 1, "company_name": "Acme Corp", "domain": None},
        {"company_id": 2, "company_name": "Beta Inc", "domain": "beta.com"},
    ]


def test_export_companies_needing_enrichment_writes_valid_csv_with_expected_columns(tmp_path):
    """End-to-end check of the actual file this function produces: real CSV
    on disk, correct header, correct row content, company_id column present
    (not just company_name) - critical since it's what lets the import step
    match enriched rows back to the right Postgres row instead of
    re-guessing on name alone."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [(1, "Acme Corp", None), (2, "Beta Inc", "beta.com")]

    path = enrichment.export_companies_needing_enrichment(mock_conn, export_dir=str(tmp_path))

    with open(path) as f:
        rows = list(csv.DictReader(f))

    assert rows == [
        {"company_id": "1", "company_name": "Acme Corp", "domain": ""},
        {"company_id": "2", "company_name": "Beta Inc", "domain": "beta.com"},
    ]


def test_export_companies_needing_enrichment_writes_empty_csv_when_nothing_to_enrich(tmp_path):
    """Edge case: if every company is already fully enriched, the export
    should still succeed and produce a valid CSV with just a header - not
    error, not skip writing the file entirely."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = []

    path = enrichment.export_companies_needing_enrichment(mock_conn, export_dir=str(tmp_path))

    with open(path) as f:
        rows = list(csv.DictReader(f))

    assert rows == []
    assert Path(path).exists()


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> str:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def test_import_enriched_dataset_writes_domain_using_clays_real_column_name(tmp_path, monkeypatch):
    """Clay's actual export uses the column name "Domain" (capital D), not
    "domain" - this test uses that exact real shape so a regression here
    (e.g. someone 'cleaning up' to lowercase without checking) would be
    caught immediately."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [{"company_id": "3", "company_name": "Sapphire Software Parent, LLC", "Domain": "sapphireventures.com"}],
        fieldnames=["company_id", "company_name", "Domain"],
    )
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_dataset(mock_conn, csv_path)

    assert updated_ids == [3]
    enrichment.db.update_company_by_id.assert_called_once_with(mock_conn, 3, domain="sapphireventures.com")


def test_import_enriched_dataset_derives_domain_from_website_when_domain_blank(tmp_path, monkeypatch):
    """Real "Company Enrichment" shape (2026-07-13 real user export): a
    "Website" full-URL column, not just a bare "Domain" - must be used as a
    fallback when the row's own Domain/domain is blank, since that's the
    only domain signal Company Enrichment gives for a company that had no
    domain at export time."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [{"company_id": "4", "company_name": "Smith Micro", "Domain": "", "Website": "https://www.smithmicro.com"}],
        fieldnames=["company_id", "company_name", "Domain", "Website"],
    )
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_dataset(mock_conn, csv_path)

    assert updated_ids == [4]
    enrichment.db.update_company_by_id.assert_called_once_with(mock_conn, 4, domain="smithmicro.com")


def test_import_enriched_dataset_prefers_domain_column_over_website(tmp_path, monkeypatch):
    """A row's own Domain/domain (carried through from export - a fact
    already known) must win over a freshly-derived Website guess, never be
    silently overwritten by it."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [{"company_id": "5", "company_name": "Acme", "domain": "acme.com", "Website": "https://www.wrongsite.com"}],
        fieldnames=["company_id", "company_name", "domain", "Website"],
    )
    mock_conn = MagicMock()

    enrichment.import_enriched_dataset(mock_conn, csv_path)

    enrichment.db.update_company_by_id.assert_called_once_with(mock_conn, 5, domain="acme.com")


def test_import_enriched_dataset_skips_rows_with_nothing_determinable(tmp_path, monkeypatch):
    """A real Clay "❌ Company Not Found" row (2026-07-13 real user export -
    every other column blank) must be skipped entirely, not written as an
    empty-string domain - domain is UNIQUE in the schema, and writing ""
    for multiple companies would collide."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [
            {"company_id": "3", "company_name": "Sapphire Software Parent, LLC", "Domain": "sapphireventures.com"},
            {"company_id": "4", "company_name": "No Match Co", "Domain": ""},
        ],
        fieldnames=["company_id", "company_name", "Domain"],
    )
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_dataset(mock_conn, csv_path)

    assert updated_ids == [3]
    enrichment.db.update_company_by_id.assert_called_once()


def test_import_enriched_dataset_skips_a_row_that_collides_with_an_existing_domain(tmp_path, monkeypatch):
    """Real, live-hit case (2026-07-13): Clay's waterfall mismatched multiple
    different companies to the same placeholder domain (several Chrome-
    extension-style Product Hunt launches all resolving to "google.com").
    companies.domain is UNIQUE, so the 2nd/3rd such row raises psycopg2's
    UniqueViolation - must be caught and skipped per-row (with a rollback,
    since a raised statement aborts that row's transaction), not left to
    kill the whole import and re-crash on every retry."""
    monkeypatch.setattr(
        enrichment.db,
        "update_company_by_id",
        MagicMock(side_effect=[None, psycopg2.errors.UniqueViolation("duplicate key"), None]),
    )
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [
            {"company_id": "1", "company_name": "First Match", "Domain": "google.com"},
            {"company_id": "2", "company_name": "Second Match", "Domain": "google.com"},
            {"company_id": "3", "company_name": "Real Match", "Domain": "realcompany.com"},
        ],
        fieldnames=["company_id", "company_name", "Domain"],
    )
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_dataset(mock_conn, csv_path)

    assert updated_ids == [1, 3]
    mock_conn.rollback.assert_called_once()


def test_import_enriched_dataset_writes_domain_and_demographics_together(tmp_path, monkeypatch):
    """The real, consolidated shape: one row can carry domain AND
    employee_count AND is_saas all at once (Clay's real "Company
    Enrichment" export) - all three must land in a single update_company_by_id
    call, not three separate round-trips."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [
            {
                "company_id": "1",
                "company_name": "Acme Corp",
                "Domain": "acme.com",
                "Employee Count": "250",
                "Industry": "Business Software",
            }
        ],
        fieldnames=["company_id", "company_name", "Domain", "Employee Count", "Industry"],
    )
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_dataset(mock_conn, csv_path)

    assert updated_ids == [1]
    enrichment.db.update_company_by_id.assert_called_once_with(
        mock_conn, 1, domain="acme.com", employee_count=250, is_saas=True
    )


def test_parse_employee_count_takes_lower_bound_of_a_range():
    """Real Clay firmographic exports often give a range like '501-1000',
    not a bare number - must extract the first/lower number, not
    concatenate every digit in the string into a nonsensical value."""
    assert enrichment._parse_employee_count("501-1000") == 501


def test_parse_employee_count_handles_bare_number_and_missing_value():
    assert enrichment._parse_employee_count("250") == 250
    assert enrichment._parse_employee_count(None) is None
    assert enrichment._parse_employee_count("") is None


def test_derive_is_saas_true_for_software_industry():
    assert enrichment._derive_is_saas("Computer Software") is True


def test_derive_is_saas_false_for_non_saas_industry():
    assert enrichment._derive_is_saas("Restaurant") is False


def test_derive_is_saas_false_for_staffing_and_recruiting():
    """Real value confirmed 9x in a real Company Enrichment export
    (2026-07-13): Jobot, Robert Half, Salt, CultureMill, LaSalle Network,
    Tandym Group, Kforce, Optomi, Equal Platform Solutions - the same
    non-ICP category hiring_adzuna.py's staffing-agency filter already
    excludes upstream."""
    assert enrichment._derive_is_saas("Staffing and Recruiting") is False


def test_derive_is_saas_false_for_government():
    assert enrichment._derive_is_saas("Government Administration") is False


def test_derive_is_saas_none_for_unrecognized_or_missing_industry():
    assert enrichment._derive_is_saas("Aerospace") is None
    assert enrichment._derive_is_saas(None) is None
    assert enrichment._derive_is_saas("") is None


def test_extract_domain_from_url_strips_protocol_and_www():
    assert enrichment._extract_domain_from_url("https://www.smithmicro.com") == "smithmicro.com"
    assert enrichment._extract_domain_from_url("http://acme.com") == "acme.com"


def test_extract_domain_from_url_handles_bare_domain_with_no_protocol():
    assert enrichment._extract_domain_from_url("acme.com") == "acme.com"


def test_extract_domain_from_url_handles_missing_value():
    assert enrichment._extract_domain_from_url(None) is None
    assert enrichment._extract_domain_from_url("") is None


# ---------------------------------------------------------------------------
# Redesign v2, Tier 5/6: known-folder auto-pickup (single consolidated queue)
# ---------------------------------------------------------------------------


def test_process_incoming_files_returns_empty_list_when_folder_is_empty(tmp_path):
    mock_conn = MagicMock()
    incoming = tmp_path / "incoming"
    processed = tmp_path / "processed"
    import_fn = MagicMock()

    result = enrichment._process_incoming_files(mock_conn, str(incoming), import_fn, processed_dir=str(processed))

    assert result == []
    import_fn.assert_not_called()
    assert incoming.exists()  # created even when nothing was there yet


def test_process_incoming_files_imports_and_moves_each_csv_found(tmp_path):
    mock_conn = MagicMock()
    incoming = tmp_path / "incoming"
    processed = tmp_path / "processed"
    incoming.mkdir()
    (incoming / "a.csv").write_text("company_id,Domain\n1,acme.com\n")
    (incoming / "b.csv").write_text("company_id,Domain\n2,beta.com\n")
    (incoming / "notes.txt").write_text("ignore me")  # non-csv, must be skipped

    import_fn = MagicMock(side_effect=[[1], [2]])

    result = enrichment._process_incoming_files(mock_conn, str(incoming), import_fn, processed_dir=str(processed))

    assert result == [1, 2]
    assert import_fn.call_count == 2
    assert (processed / "a.csv").exists()
    assert (processed / "b.csv").exists()
    assert not (incoming / "a.csv").exists()  # moved out, not left behind (would be re-imported next check)
    assert (incoming / "notes.txt").exists()  # non-csv untouched


def test_process_incoming_enrichment_uses_import_enriched_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(enrichment, "CLAY_INCOMING_ENRICHMENT_DIR", str(tmp_path / "incoming_enrichment"))
    monkeypatch.setattr(enrichment, "CLAY_PROCESSED_DIR", str(tmp_path / "processed"))
    mock_import = MagicMock(return_value=[1])
    monkeypatch.setattr(enrichment, "import_enriched_dataset", mock_import)
    mock_conn = MagicMock()

    incoming = Path(tmp_path / "incoming_enrichment")
    incoming.mkdir(exist_ok=True)
    (incoming / "x.csv").write_text("company_id,Domain\n1,acme.com\n")

    result = enrichment.process_incoming_enrichment(mock_conn)

    assert result == [1]
    mock_import.assert_called_once()


def test_save_incoming_enrichment_file_writes_to_the_known_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(enrichment, "CLAY_INCOMING_ENRICHMENT_DIR", str(tmp_path / "incoming_enrichment"))

    path = enrichment.save_incoming_enrichment_file("export.csv", b"company_id,Domain\n1,acme.com\n")

    assert Path(path).exists()
    assert Path(path).read_bytes() == b"company_id,Domain\n1,acme.com\n"
    assert Path(path).parent == tmp_path / "incoming_enrichment"
    assert path.endswith("_export.csv")


def test_save_incoming_enrichment_file_timestamp_prefixes_to_avoid_collisions(tmp_path, monkeypatch):
    """Two uploads with the identical original filename must not overwrite
    each other - a real scenario since Clay's default export filename is
    often the same generic name every time."""
    monkeypatch.setattr(enrichment, "CLAY_INCOMING_ENRICHMENT_DIR", str(tmp_path / "incoming_enrichment"))

    path_1 = enrichment.save_incoming_enrichment_file("export.csv", b"first")
    path_2 = enrichment.save_incoming_enrichment_file("export.csv", b"second")

    assert path_1 != path_2
    assert Path(path_1).read_bytes() == b"first"
    assert Path(path_2).read_bytes() == b"second"
