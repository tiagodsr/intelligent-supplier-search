import hashlib
import os
import sqlite3
import subprocess
import sys

import pytest

from assistant.db import DEFAULT_DB_PATH, get_readonly_connection
from conftest import BUILD_SCRIPT, SEED

TABLES = {
    "meta", "exchange_rates", "plants", "categories", "suppliers", "supplier_aliases",
    "contracts", "catalog_items", "shopping_carts", "shopping_cart_items",
}
VIEWS = {"v_completed_lines", "v_supplier_summary"}


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def meta(conn, key):
    return conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()[0]


def dump_hash(path):
    with sqlite3.connect(path) as c:
        return hashlib.sha256("\n".join(c.iterdump()).encode()).hexdigest()


def build_in_subprocess(out, seed, hashseed):
    env = {**os.environ, "PYTHONHASHSEED": str(hashseed)}
    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--seed", str(seed), "--out", str(out)],
        env=env, check=True, capture_output=True,
    )
    return dump_hash(out)


# --------------------------------------------------------------------------- #
# Structure and integrity
# --------------------------------------------------------------------------- #


def test_expected_tables_and_views_exist(conn):
    rows = conn.execute("SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
    assert {n for t, n in rows if t == "table"} == TABLES
    assert {n for t, n in rows if t == "view"} == VIEWS


@pytest.mark.parametrize("table, lo, hi", [
    ("suppliers", 96, 96),
    ("categories", 16, 16),
    ("plants", 8, 8),
    ("exchange_rates", 7, 7),
    ("supplier_aliases", 30, 200),
    ("contracts", 50, 300),
    ("catalog_items", 200, 1500),
    ("shopping_carts", 6500, 7200),
    ("shopping_cart_items", 10000, 30000),
])
def test_row_counts_in_sane_ranges(conn, table, lo, hi):
    assert lo <= scalar(conn, f"SELECT COUNT(*) FROM {table}") <= hi


def test_integrity_check_ok(conn):
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_foreign_key_check_clean(conn):
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# --------------------------------------------------------------------------- #
# Data properties the agent relies on
# --------------------------------------------------------------------------- #


def test_supplier_status_and_risk_distribution(conn):
    status = dict(conn.execute("SELECT status, COUNT(*) FROM suppliers GROUP BY 1"))
    risk = dict(conn.execute("SELECT risk_rating, COUNT(*) FROM suppliers GROUP BY 1"))
    assert set(status) == {"active", "inactive", "blocked"}
    assert status["active"] > status["inactive"] + status["blocked"]
    assert set(risk) == {"low", "medium", "high"}
    assert scalar(conn, "SELECT COUNT(*) FROM suppliers WHERE status = 'blocked' AND risk_rating != 'high'") == 0


def test_cart_status_distribution(conn):
    status = dict(conn.execute("SELECT status, COUNT(*) FROM shopping_carts GROUP BY 1"))
    assert set(status) == {"completed", "cancelled", "rejected", "in_approval"}
    assert status["completed"] / sum(status.values()) > 0.75


def test_completed_at_set_only_for_completed_carts(conn):
    assert scalar(conn, """
        SELECT COUNT(*) FROM shopping_carts
        WHERE (status = 'completed') != (completed_at IS NOT NULL)""") == 0


def test_some_alias_maps_to_multiple_suppliers(conn):
    assert scalar(conn, """
        SELECT COUNT(*) FROM (
            SELECT alias FROM supplier_aliases
            GROUP BY alias HAVING COUNT(DISTINCT supplier_id) > 1)""") >= 1


def test_no_truncated_legal_suffix_in_aliases(conn):
    assert scalar(conn, """
        SELECT COUNT(*) FROM supplier_aliases
        WHERE alias LIKE '% Sp. z' OR alias LIKE '% Co.,'""") == 0


def test_expired_and_draft_contracts_exist(conn):
    as_of = meta(conn, "as_of_date")
    status = dict(conn.execute("SELECT status, COUNT(*) FROM contracts GROUP BY 1"))
    assert status.get("expired", 0) > 0
    assert status.get("draft", 0) > 0
    assert scalar(conn, f"SELECT COUNT(*) FROM contracts WHERE status = 'draft' AND start_date <= '{as_of}'") == 0
    assert scalar(conn, f"SELECT COUNT(*) FROM contracts WHERE status = 'expired' AND end_date >= '{as_of}'") == 0


def test_some_cart_lines_have_null_category(conn):
    total = scalar(conn, "SELECT COUNT(*) FROM shopping_cart_items")
    nulls = scalar(conn, "SELECT COUNT(*) FROM shopping_cart_items WHERE category_id IS NULL")
    assert 0 < nulls < 0.10 * total


@pytest.mark.parametrize("status", ["inactive", "blocked"])
def test_non_active_suppliers_have_purchases(conn, status):
    assert scalar(conn, f"""
        SELECT COUNT(*) FROM v_completed_lines v
        JOIN suppliers s ON s.supplier_id = v.supplier_id
        WHERE s.status = '{status}'""") > 0


def test_total_value_matches_unit_price_times_quantity(conn):
    assert scalar(conn, """
        SELECT COUNT(*) FROM shopping_cart_items
        WHERE ABS(total_value - unit_price * quantity) > 0.01""") == 0


def test_dates_inside_data_window(conn):
    start, end, as_of = meta(conn, "data_from"), meta(conn, "data_to"), meta(conn, "as_of_date")
    for table in ("shopping_carts", "shopping_cart_items", "catalog_items"):
        lo, hi = conn.execute(f"SELECT MIN(created_at), MAX(created_at) FROM {table}").fetchone()
        assert start <= lo and hi <= end, table
    # completed_at may fall after data_to (it is capped at as_of_date), never before created_at
    assert scalar(conn, f"""
        SELECT COUNT(*) FROM shopping_carts
        WHERE completed_at < created_at OR completed_at > '{as_of}'""") == 0
    assert scalar(conn, f"SELECT COUNT(*) FROM suppliers WHERE onboarded_at > '{as_of}'") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM contracts WHERE start_date > end_date") == 0


def test_views_return_rows(conn):
    completed_lines = scalar(conn, """
        SELECT COUNT(*) FROM shopping_cart_items l
        JOIN shopping_carts c ON c.cart_id = l.cart_id WHERE c.status = 'completed'""")
    assert completed_lines > 0
    assert scalar(conn, "SELECT COUNT(*) FROM v_completed_lines") == completed_lines
    assert scalar(conn, "SELECT COUNT(*) FROM v_supplier_summary") == scalar(conn, "SELECT COUNT(*) FROM suppliers")


def test_eur_amounts_plausible(conn):
    lo, hi, nulls = conn.execute("""
        SELECT MIN(total_value_eur), MAX(total_value_eur), SUM(total_value_eur IS NULL)
        FROM v_completed_lines""").fetchone()
    assert nulls == 0
    assert lo > 0
    assert hi < 1_000_000
    assert scalar(conn, "SELECT COUNT(*) FROM v_supplier_summary WHERE spend_eur < 0") == 0


# --------------------------------------------------------------------------- #
# Reproducibility
# --------------------------------------------------------------------------- #


def test_build_is_deterministic_across_hash_seeds(tmp_path):
    a = build_in_subprocess(tmp_path / "a.db", SEED, hashseed=1)
    b = build_in_subprocess(tmp_path / "b.db", SEED, hashseed=2)
    assert a == b


def test_build_matches_in_process_fixture(built_db, tmp_path):
    assert build_in_subprocess(tmp_path / "c.db", SEED, hashseed=3) == dump_hash(built_db)


def test_different_seed_gives_different_data(built_db, tmp_path):
    assert build_in_subprocess(tmp_path / "s7.db", 7, hashseed=0) != dump_hash(built_db)


# --------------------------------------------------------------------------- #
# Read-only access
# --------------------------------------------------------------------------- #


def test_query_only_pragma_is_on(conn):
    assert scalar(conn, "PRAGMA query_only") == 1


@pytest.mark.parametrize("sql", [
    "INSERT INTO plants VALUES (99, 'Site 99', 'DE', 'Berlin')",
    "DROP TABLE suppliers",
])
def test_write_attempt_raises(conn, sql):
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(sql)
    assert scalar(conn, "SELECT COUNT(*) FROM plants") == 8
    assert scalar(conn, "SELECT COUNT(*) FROM suppliers") == 96


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_db.py"):
        get_readonly_connection(tmp_path / "nope.db")


def test_db_path_env_var_is_used(built_db, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(built_db))
    c = get_readonly_connection()
    try:
        assert scalar(c, "SELECT COUNT(*) FROM suppliers") == 96
    finally:
        c.close()


def test_committed_db_opens_readonly_with_as_of_date(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    c = get_readonly_connection()
    try:
        assert DEFAULT_DB_PATH.is_file()
        assert scalar(c, "PRAGMA query_only") == 1
        assert meta(c, "as_of_date") == "2026-10-03"
    finally:
        c.close()
