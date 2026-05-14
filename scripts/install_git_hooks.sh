#!/usr/bin/env bash
# X21.30: Install Git pre-commit + pre-push hooks for this repo.
#
# What the hooks check:
#
#   pre-commit  — fast syntax checks on staged Python files (catches typos
#                 before they hit the index). Skipped if no .py files staged.
#
#   pre-push    — runs the schema_lint and convert_query unit tests against
#                 the working tree. These are the two locks I want to never
#                 regress:
#                   • schema_lint  (catches column-mismatches like X21.22's
#                                   user_notifications.delivered_at bug)
#                   • _convert_query tests (the JSONB ? operator fix)
#                 Both run in <1 second so they don't slow you down.
#
# Hooks are NOT committed (they live in .git/hooks/ which is not tracked).
# Re-run this script after a fresh clone.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "✗ Not a git repo (no .git/hooks/ directory)"
    exit 1
fi

# ── pre-commit ──────────────────────────────────────────────────────
cat > "$HOOKS_DIR/pre-commit" <<'HOOK_EOF'
#!/usr/bin/env bash
# X21.30: fast Python syntax check on staged .py files.
set -e

# Find staged Python files (relative paths)
staged=$(git diff --cached --name-only --diff-filter=ACMR | grep '\.py$' || true)
if [ -z "$staged" ]; then
    exit 0
fi

failed=0
while IFS= read -r f; do
    if [ -f "$f" ]; then
        if ! python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
            echo "✗ Syntax error in $f"
            python3 -c "import ast; ast.parse(open('$f').read())" || true
            failed=1
        fi
    fi
done <<< "$staged"

if [ $failed -ne 0 ]; then
    echo "→ Fix the syntax error(s) above, then re-commit."
    exit 1
fi
exit 0
HOOK_EOF
chmod +x "$HOOKS_DIR/pre-commit"
echo "✓ Installed pre-commit hook (Python syntax check)"

# ── pre-push ────────────────────────────────────────────────────────
cat > "$HOOKS_DIR/pre-push" <<'HOOK_EOF'
#!/usr/bin/env bash
# X21.30: schema_lint + _convert_query sanity tests before push.
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "→ Running schema_lint…"
if ! python3 scripts/schema_lint.py > /tmp/.schema_lint.out 2>&1; then
    cat /tmp/.schema_lint.out
    echo
    echo "✗ schema_lint failed — column-level SQL mismatch detected."
    echo "  Push aborted. Override with: git push --no-verify"
    exit 1
fi
tail -1 /tmp/.schema_lint.out

echo
echo "→ Running _convert_query tests…"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, '.')
from database import _convert_query
cases = [
    ('simple',            'SELECT * FROM t WHERE id = ?', 'SELECT * FROM t WHERE id = %s'),
    ('multi',             'INSERT INTO t (a,b) VALUES (?, ?)', 'INSERT INTO t (a,b) VALUES (%s, %s)'),
    ('jsonb_has_key',     "WHERE data ? 'k'", "WHERE data ? 'k'"),
    ('jsonb_has_any',     "WHERE data ?| array['a']", "WHERE data ?| array['a']"),
    ('jsonb_has_all',     "WHERE data ?& array['a']", "WHERE data ?& array['a']"),
    ('mixed',             "WHERE id = ? AND data ? 'k'", "WHERE id = %s AND data ? 'k'"),
    ('quoted_question',   "SELECT 'huh?' AS m", "SELECT 'huh?' AS m"),
    ('no_space',          'WHERE id=?', 'WHERE id=%s'),
    ('empty',             '', ''),
    ('no_q',              'SELECT 1', 'SELECT 1'),
    ('values',            'VALUES (?, ?)', 'VALUES (%s, %s)'),
    ('in_paren',          'WHERE id IN (?)', 'WHERE id IN (%s)'),
]
failed = []
for name, sql, expected in cases:
    got = _convert_query(sql)
    if got != expected:
        failed.append((name, sql, got, expected))
if failed:
    for name, sql, got, exp in failed:
        print(f'✗ {name}: got={got!r} expected={exp!r}', file=sys.stderr)
    sys.exit(1)
print(f'  ✓ {len(cases)}/{len(cases)} _convert_query tests passed')
PYEOF

echo
echo "✓ Pre-push checks passed."
exit 0
HOOK_EOF
chmod +x "$HOOKS_DIR/pre-push"
echo "✓ Installed pre-push hook (schema_lint + _convert_query tests)"

echo
echo "Hooks installed in $HOOKS_DIR"
echo "  • pre-commit : Python syntax check on staged .py files"
echo "  • pre-push   : schema_lint + _convert_query tests"
echo
echo "Override with --no-verify if you ever need to bypass."
