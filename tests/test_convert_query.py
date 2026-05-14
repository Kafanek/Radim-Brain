"""
Unit tests for database._convert_query — SQLite-to-PostgreSQL query translator.

X21.29: Locks down the X21.24 fix where `?` placeholders were being naively
replaced everywhere, breaking JSONB has-key operators (`data ? 'key'`) and
JSONB array operators (`?|` and `?&`). The translator now distinguishes:

  • `?` as placeholder (SQLite-style positional bind) → `%s`
  • `data ? 'key'` (JSONB has-key)                    → leave as `?`
  • `data ?| array[...]` (JSONB has any key)          → leave as `?|`
  • `data ?& array[...]` (JSONB has all keys)         → leave as `?&`
  • `?` inside string literals                        → leave as `?`

If this test ever fails, the SQL wrapper is breaking something — either
admin queries (the symptom that surfaced X21.24) or normal placeholder
binding.
"""

import pytest

from database import _convert_query


# ── Placeholder conversion (the legacy case) ───────────────────────────

def test_simple_placeholder():
    assert _convert_query("SELECT * FROM t WHERE id = ?") == \
        "SELECT * FROM t WHERE id = %s"


def test_multiple_placeholders():
    assert _convert_query("INSERT INTO t (a, b, c) VALUES (?, ?, ?)") == \
        "INSERT INTO t (a, b, c) VALUES (%s, %s, %s)"


def test_placeholder_no_spaces():
    # `id=?` with no spaces — still a placeholder
    assert _convert_query("WHERE id=?") == "WHERE id=%s"


def test_placeholder_in_complex_where():
    sql = "DELETE FROM t WHERE created_at < ? AND user_id = ?"
    out = _convert_query(sql)
    assert out == "DELETE FROM t WHERE created_at < %s AND user_id = %s"


# ── JSONB has-key operator: `data ? 'key'` ─────────────────────────────

def test_jsonb_has_key_basic():
    sql = "SELECT user_id FROM memory_profiles WHERE data ? 'long_term_context'"
    out = _convert_query(sql)
    # The `?` between two operands (with surrounding spaces and a quoted
    # string next) must remain `?` — it's a JSONB operator.
    assert "?" in out, f"Expected `?` kept as JSONB operator, got: {out}"
    assert "%s" not in out, f"No `%s` expected, got: {out}"


def test_jsonb_has_key_in_case_when():
    # The exact pattern that surfaced X21.24
    sql = (
        "SELECT user_id, "
        "CASE WHEN data ? 'long_term_context' THEN 'yes' ELSE 'no' END "
        "FROM memory_profiles"
    )
    out = _convert_query(sql)
    assert "data ? 'long_term_context'" in out, \
        f"JSONB has-key got mangled: {out}"


def test_jsonb_has_key_mixed_with_placeholder():
    # Both in the same query — placeholder converted, JSONB op preserved.
    sql = "SELECT id FROM memory_profiles WHERE user_id = ? AND data ? 'name'"
    out = _convert_query(sql)
    assert "user_id = %s" in out, f"Placeholder not converted: {out}"
    assert "data ? 'name'" in out, f"JSONB op got mangled: {out}"


# ── JSONB array operators: `?|` and `?&` ───────────────────────────────

def test_jsonb_has_any_key_operator():
    sql = "SELECT id FROM t WHERE data ?| array['a','b']"
    out = _convert_query(sql)
    assert "?|" in out, f"JSONB has-any-key operator broken: {out}"


def test_jsonb_has_all_keys_operator():
    sql = "SELECT id FROM t WHERE data ?& array['a','b']"
    out = _convert_query(sql)
    assert "?&" in out, f"JSONB has-all-keys operator broken: {out}"


# ── `?` inside string literals must be left alone ──────────────────────

def test_question_mark_in_single_quoted_string():
    sql = "SELECT 'really?' AS msg"
    out = _convert_query(sql)
    assert "'really?'" in out, f"`?` in string literal got converted: {out}"
    assert "%s" not in out


def test_question_mark_in_double_quoted_string():
    sql = 'SELECT "Got?" FROM t'
    out = _convert_query(sql)
    assert '"Got?"' in out, f"`?` in double-quoted ident got converted: {out}"


def test_placeholder_alongside_quoted_question_mark():
    sql = "SELECT 'really?' FROM t WHERE id = ?"
    out = _convert_query(sql)
    assert "'really?'" in out
    assert "id = %s" in out, f"Placeholder after string broken: {out}"


# ── Edge cases ─────────────────────────────────────────────────────────

def test_empty_query():
    assert _convert_query("") == ""


def test_no_question_marks():
    sql = "SELECT 1 FROM t"
    assert _convert_query(sql) == sql


def test_placeholder_at_query_start():
    # Unusual but legal — placeholder right after a keyword
    sql = "VALUES (?, ?)"
    assert _convert_query(sql) == "VALUES (%s, %s)"


def test_placeholder_followed_by_paren():
    sql = "WHERE id IN (?)"
    out = _convert_query(sql)
    assert out == "WHERE id IN (%s)"
