#!/usr/bin/env python3
"""
schema_lint.py — catch schema/SQL mismatches before deploy.

X21.24: After the user_notifications.delivered_at incident (X21.22 → X21.23
silent-rollback bug), this checker reads database_schema.py to build a
table → set(columns) map, then scans cleanup/maintenance modules for
SQL queries that reference columns. Any column not in the schema is
reported.

Run locally:
    python scripts/schema_lint.py

Exit code: 0 if clean, 1 if any mismatches found.

Limitations (intentionally simple — would need a proper SQL parser to do
more): only catches `WHERE <col>` / `AND <col>` / `<col> IS [NOT] NULL`
patterns where the table is named in the same statement. Bare aliases
(`alias.col`) are skipped. Goal is catching the obvious bugs, not 100%
coverage — manual review still required for complex queries.
"""

import os
import re
import sys

# Files to scan (relative to repo root). Keep this list focused on
# maintenance code — scanning every route would produce too much noise.
TARGETS = [
    "radim_sleep.py",
    "agent_loop.py",
    "audit_maintenance.py",
    "gdpr_routes.py",
    "memory_helpers.py",
]


def parse_schema_columns(schema_path):
    """Read database_schema.py and return {table_name: set(columns)}."""
    src = open(schema_path).read()
    tables = {}

    # Match `CREATE TABLE IF NOT EXISTS <name> ( ... )` blocks.
    # The schema file uses tuple-form: ('''CREATE TABLE ... ''', [indexes])
    table_re = re.compile(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\)\s*'''",
        re.IGNORECASE | re.DOTALL,
    )
    for m in table_re.finditer(src):
        name = m.group(1)
        body = m.group(2)
        cols = set()
        # Match column lines: `<col_name> TYPE ...`
        # Skip lines that are constraints (PRIMARY KEY, FOREIGN KEY, UNIQUE, etc.)
        for line in body.split(","):
            line = line.strip()
            if not line:
                continue
            # Skip constraint lines
            if line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "CONSTRAINT")):
                continue
            # First token = column name
            first = line.split()[0] if line.split() else ""
            if first and re.match(r"^[a-zA-Z_]\w*$", first):
                cols.add(first.lower())
        tables[name.lower()] = cols
    return tables


def find_column_refs(sql, table):
    """Heuristically extract column names referenced in `sql` for `table`.

    Returns a list of (column, kind) pairs where kind ∈ {"where", "set", "select"}.
    """
    refs = []
    # WHERE col [op] ... — matches col after WHERE/AND/OR keywords.
    # Allow patterns like `WHERE col IS NULL` and `WHERE col < ...`.
    for m in re.finditer(
        r"(?:WHERE|AND|OR)\s+([a-zA-Z_]\w*)\s+(?:IS\s+(?:NOT\s+)?NULL|=|<|>|<=|>=|!=|LIKE|IN)",
        sql,
        re.IGNORECASE,
    ):
        refs.append((m.group(1).lower(), "where"))
    # SET col = ...
    for m in re.finditer(r"SET\s+([a-zA-Z_]\w*)\s*=", sql, re.IGNORECASE):
        refs.append((m.group(1).lower(), "set"))
    return refs


def extract_sql_strings(py_path):
    """Pull all string literals from a Python file that look like SQL
    (start with SELECT/INSERT/UPDATE/DELETE/WITH). Return list of strings.
    """
    src = open(py_path).read()
    # Find triple-quoted and single-quoted strings
    sqls = []
    # Multi-line and single-line strings
    for m in re.finditer(
        r'(?:"""(.*?)"""|\'\'\'(.*?)\'\'\'|"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')',
        src,
        re.DOTALL,
    ):
        s = m.group(1) or m.group(2) or m.group(3) or m.group(4) or ""
        s = s.strip()
        if re.match(r"(SELECT|INSERT|UPDATE|DELETE|WITH)\b", s, re.IGNORECASE):
            sqls.append(s)
    return sqls


def lint(repo_root):
    schema_path = os.path.join(repo_root, "database_schema.py")
    if not os.path.exists(schema_path):
        print(f"FAIL: {schema_path} not found")
        return 1

    tables = parse_schema_columns(schema_path)
    print(f"Loaded {len(tables)} tables from schema")

    issues = []
    scanned_files = 0
    scanned_sqls = 0

    for rel in TARGETS:
        path = os.path.join(repo_root, rel)
        if not os.path.exists(path):
            continue
        scanned_files += 1
        for sql in extract_sql_strings(path):
            scanned_sqls += 1
            # Find FROM <table> or UPDATE <table> or INTO <table> or DELETE FROM <table>
            for tm in re.finditer(
                r"(?:FROM|UPDATE|INTO)\s+([a-zA-Z_]\w*)",
                sql,
                re.IGNORECASE,
            ):
                table = tm.group(1).lower()
                if table not in tables:
                    # Unknown table — could be a subquery alias or a view; skip.
                    continue
                cols = tables[table]
                for col, kind in find_column_refs(sql, table):
                    if col in cols:
                        continue
                    # Some SQL keywords slip through (e.g. NOT, EXISTS) — filter them.
                    if col in {"not", "exists", "and", "or", "null", "true", "false", "interval", "current_timestamp", "now"}:
                        continue
                    # Skip qualified refs (table.col) — they appear as `col` without alias
                    issues.append({
                        "file": rel,
                        "table": table,
                        "column": col,
                        "kind": kind,
                        "sql_excerpt": sql[:120].replace("\n", " "),
                    })

    print(f"Scanned {scanned_files} files, {scanned_sqls} SQL strings")
    print()

    if not issues:
        print("✓ schema_lint: clean")
        return 0

    print(f"✗ schema_lint: found {len(issues)} potential mismatches")
    seen = set()
    for iss in issues:
        key = (iss["file"], iss["table"], iss["column"])
        if key in seen:
            continue
        seen.add(key)
        print(f"  {iss['file']:<25} {iss['table']}.{iss['column']:<20} ({iss['kind']})")
        print(f"      {iss['sql_excerpt']}")
    return 1


if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.exit(lint(repo_root))
