"""Tests for python/enrichment.py's export side (Phase 6, ADR-017).
The import side (import_enriched_companies) isn't built yet - waiting on a
real sample of Clay's exported CSV column names before writing its parser,
per the 2026-07-10 plan notes. Postgres calls are mocked throughout."""
import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock

import psycopg2.errors
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import enrichment  # noqa: E402


def test_get_companies_needing_domain_maps_rows_to_dicts():
    """Confirms the raw (id, name) tuples psycopg2 returns get mapped to the
    company_id/company_name dict shape the rest of this module (and Clay's
    CSV import) expects - a mismatch here would silently corrupt every
    downstream column mapping."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [(1, "Acme Corp"), (2, "Beta Inc")]

    result = enrichment.get_companies_needing_domain(mock_conn)

    assert result == [
        {"company_id": 1, "company_name": "Acme Corp"},
        {"company_id": 2, "company_name": "Beta Inc"},
    ]


def test_export_companies_needing_domain_writes_valid_csv_with_expected_columns(tmp_path):
    """End-to-end check of the actual file this function produces: real CSV
    on disk, correct header, correct row content, company_id column present
    (not just company_name) - critical since it's what lets the not-yet-built
    import step match enriched rows back to the right Postgres row instead of
    re-guessing on name alone."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [(1, "Acme Corp"), (2, "Beta Inc")]

    path = enrichment.export_companies_needing_domain(mock_conn, export_dir=str(tmp_path))

    with open(path) as f:
        rows = list(csv.DictReader(f))

    assert rows == [
        {"company_id": "1", "company_name": "Acme Corp"},
        {"company_id": "2", "company_name": "Beta Inc"},
    ]


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> str:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def test_import_enriched_companies_writes_domain_using_clays_real_column_name(tmp_path, monkeypatch):
    """Clay's actual export (2026-07-11 real user data) uses the column name
    "Domain" (capital D), not "domain" - this test uses that exact real
    shape so a regression here (e.g. someone 'cleaning up' to lowercase
    without checking) would be caught immediately."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path = _write_csv(
        tmp_path / "enriched.csv",
        [{"company_id": "3", "company_name": "Sapphire Software Parent, LLC", "Domain": "sapphireventures.com"}],
        fieldnames=["company_id", "company_name", "Domain"],
    )
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_companies(mock_conn, csv_path)

    assert updated_ids == [3]
    enrichment.db.update_company_by_id.assert_called_once_with(mock_conn, 3, domain="sapphireventures.com")


def test_import_enriched_companies_skips_rows_with_no_domain(tmp_path, monkeypatch):
    """An enrichment miss (Clay found no domain for a company) must be
    skipped, not written as an empty-string domain - domain is UNIQUE in
    the schema, and writing "" for multiple companies would collide."""
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

    updated_ids = enrichment.import_enriched_companies(mock_conn, csv_path)

    assert updated_ids == [3]
    enrichment.db.update_company_by_id.assert_called_once()


def test_import_enriched_companies_skips_a_row_that_collides_with_an_existing_domain(tmp_path, monkeypatch):
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

    updated_ids = enrichment.import_enriched_companies(mock_conn, csv_path)

    assert updated_ids == [1, 3]
    mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Redesign v2, Tier 4: demographic enrichment pass (employee_count/is_saas)
# ---------------------------------------------------------------------------


def test_get_companies_needing_demographics_maps_rows_including_domain():
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [(1, "Acme Corp", "acme.com")]

    result = enrichment.get_companies_needing_demographics(mock_conn)

    assert result == [{"company_id": 1, "company_name": "Acme Corp", "domain": "acme.com"}]


def test_export_companies_needing_demographics_writes_valid_csv_with_domain_column(tmp_path):
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = [(1, "Acme Corp", "acme.com")]

    path = enrichment.export_companies_needing_demographics(mock_conn, export_dir=str(tmp_path))

    with open(path) as f:
        rows = list(csv.DictReader(f))

    assert rows == [{"company_id": "1", "company_name": "Acme Corp", "domain": "acme.com"}]


def test_import_enriched_demographics_parses_employee_count_and_derives_is_saas(monkeypatch):
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    csv_path_rows = [
        {"company_id": "1", "company_name": "Acme Corp", "Employee Count": "250", "Industry": "Business Software"}
    ]
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_id", "company_name", "Employee Count", "Industry"])
        writer.writeheader()
        writer.writerows(csv_path_rows)
        path = f.name
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_demographics(mock_conn, path)

    assert updated_ids == [1]
    enrichment.db.update_company_by_id.assert_called_once_with(mock_conn, 1, employee_count=250, is_saas=True)


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


def test_derive_is_saas_none_for_unrecognized_or_missing_industry():
    assert enrichment._derive_is_saas("Aerospace") is None
    assert enrichment._derive_is_saas(None) is None
    assert enrichment._derive_is_saas("") is None


def test_import_enriched_demographics_skips_rows_with_neither_value_determinable(monkeypatch):
    """A row where employee count is blank AND industry doesn't match
    either keyword list must be skipped entirely - nothing to write, same
    'skip on no real data' behavior as the domain import already has."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_id", "company_name", "Employee Count", "Industry"])
        writer.writeheader()
        writer.writerow({"company_id": "2", "company_name": "Mystery Co", "Employee Count": "", "Industry": "Aerospace"})
        path = f.name
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_demographics(mock_conn, path)

    assert updated_ids == []
    enrichment.db.update_company_by_id.assert_not_called()


def test_import_enriched_demographics_writes_only_the_determinable_field(monkeypatch):
    """A row with a real employee count but an unrecognized industry should
    still write employee_count alone - one missing/undeterminable field
    shouldn't block writing the other real one."""
    monkeypatch.setattr(enrichment.db, "update_company_by_id", MagicMock())
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_id", "company_name", "Employee Count", "Industry"])
        writer.writeheader()
        writer.writerow({"company_id": "5", "company_name": "Rocket Co", "Employee Count": "80", "Industry": "Aerospace"})
        path = f.name
    mock_conn = MagicMock()

    updated_ids = enrichment.import_enriched_demographics(mock_conn, path)

    assert updated_ids == [5]
    enrichment.db.update_company_by_id.assert_called_once_with(mock_conn, 5, employee_count=80)


def test_export_companies_needing_domain_writes_empty_csv_when_nothing_to_enrich(tmp_path):
    """Edge case: if every company already has a domain (e.g. a repeat run
    after enrichment already ran), the export should still succeed and
    produce a valid CSV with just a header - not error, not skip writing
    the file entirely."""
    mock_conn = MagicMock()
    mock_cursor = mock_conn.cursor.return_value.__enter__.return_value
    mock_cursor.fetchall.return_value = []

    path = enrichment.export_companies_needing_domain(mock_conn, export_dir=str(tmp_path))

    with open(path) as f:
        rows = list(csv.DictReader(f))

    assert rows == []
    assert Path(path).exists()


# ---------------------------------------------------------------------------
# Redesign v2, Tier 5: known-folder auto-pickup
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


def test_process_incoming_domain_enrichment_uses_import_enriched_companies(monkeypatch, tmp_path):
    monkeypatch.setattr(enrichment, "CLAY_INCOMING_DOMAIN_DIR", str(tmp_path / "incoming_domain"))
    monkeypatch.setattr(enrichment, "CLAY_PROCESSED_DIR", str(tmp_path / "processed"))
    mock_import = MagicMock(return_value=[])
    monkeypatch.setattr(enrichment, "import_enriched_companies", mock_import)
    mock_conn = MagicMock()

    enrichment.process_incoming_domain_enrichment(mock_conn)

    # no files present, but confirms it's wired to the right import function
    # via a real file to exercise the call
    incoming = Path(tmp_path / "incoming_domain")
    incoming.mkdir(exist_ok=True)
    (incoming / "x.csv").write_text("company_id,Domain\n1,acme.com\n")

    enrichment.process_incoming_domain_enrichment(mock_conn)

    mock_import.assert_called_once()


def test_process_incoming_demographic_enrichment_uses_import_enriched_demographics(monkeypatch, tmp_path):
    monkeypatch.setattr(enrichment, "CLAY_INCOMING_DEMOGRAPHICS_DIR", str(tmp_path / "incoming_demographics"))
    monkeypatch.setattr(enrichment, "CLAY_PROCESSED_DIR", str(tmp_path / "processed"))
    mock_import = MagicMock(return_value=[])
    monkeypatch.setattr(enrichment, "import_enriched_demographics", mock_import)
    mock_conn = MagicMock()

    incoming = Path(tmp_path / "incoming_demographics")
    incoming.mkdir(exist_ok=True)
    (incoming / "x.csv").write_text("company_id,Employee Count\n1,50\n")

    enrichment.process_incoming_demographic_enrichment(mock_conn)


# ---------------------------------------------------------------------------
# Redesign v2, Tier 6: content-based enrichment-kind detection + Discord
# bot upload landing
# ---------------------------------------------------------------------------


def test_detect_enrichment_kind_recognizes_demographics_header():
    assert enrichment._detect_enrichment_kind(["company_id", "company_name", "domain", "Employee Count", "Industry"]) == "demographics"


def test_detect_enrichment_kind_recognizes_domain_header():
    assert enrichment._detect_enrichment_kind(["company_id", "company_name", "Domain"]) == "domain"


def test_detect_enrichment_kind_returns_none_for_unrecognized_header():
    assert enrichment._detect_enrichment_kind(["company_id", "company_name"]) is None


def test_detect_enrichment_kind_prefers_demographics_when_both_shapes_present():
    """A demographics-enriched file also has a plain "domain" column (it
    was already known before Clay added firmographic data) - demographics
    detection must win, not the domain-only fallback."""
    assert enrichment._detect_enrichment_kind(["company_id", "domain", "Employee Count"]) == "demographics"


def test_save_incoming_enrichment_file_writes_to_the_domain_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(enrichment, "KNOWN_FOLDER_DIRS", {"domain": str(tmp_path / "incoming_domain"), "demographics": str(tmp_path / "incoming_demographics")})

    path = enrichment.save_incoming_enrichment_file("domain", "export.csv", b"company_id,Domain\n1,acme.com\n")

    assert Path(path).exists()
    assert Path(path).read_bytes() == b"company_id,Domain\n1,acme.com\n"
    assert Path(path).parent == tmp_path / "incoming_domain"
    assert path.endswith("_export.csv")


def test_save_incoming_enrichment_file_writes_to_the_demographics_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(enrichment, "KNOWN_FOLDER_DIRS", {"domain": str(tmp_path / "incoming_domain"), "demographics": str(tmp_path / "incoming_demographics")})

    path = enrichment.save_incoming_enrichment_file("demographics", "export.csv", b"data")

    assert Path(path).parent == tmp_path / "incoming_demographics"


def test_save_incoming_enrichment_file_timestamp_prefixes_to_avoid_collisions(tmp_path, monkeypatch):
    """Two uploads with the identical original filename must not overwrite
    each other - a real scenario since Clay's default export filename is
    often the same generic name every time."""
    monkeypatch.setattr(enrichment, "KNOWN_FOLDER_DIRS", {"domain": str(tmp_path / "incoming_domain"), "demographics": str(tmp_path / "incoming_demographics")})

    path_1 = enrichment.save_incoming_enrichment_file("domain", "export.csv", b"first")
    path_2 = enrichment.save_incoming_enrichment_file("domain", "export.csv", b"second")

    assert path_1 != path_2
    assert Path(path_1).read_bytes() == b"first"
    assert Path(path_2).read_bytes() == b"second"
