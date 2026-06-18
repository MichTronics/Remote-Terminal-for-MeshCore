#!/usr/bin/env bash
set -euo pipefail

# Backend-only quality gate (no npm / frontend build).
# Use all_quality.sh before handoff when frontend may also be affected.

if command -v enablenvm >/dev/null 2>&1; then
    enablenvm >/dev/null 2>&1 || true
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo -e "${YELLOW}=== RemoteTerm Backend Quality Checks ===${NC}"
echo

echo -e "${YELLOW}=== Lint & Format ===${NC}"

echo -ne "${BLUE}[ruff check]${NC} "
cd "$REPO_ROOT"
uv run ruff check app/ tests/ --fix --quiet
echo -e "${GREEN}Passed!${NC}"

echo -ne "${BLUE}[ruff format]${NC} "
uv run ruff format app/ tests/ --quiet
echo -e "${GREEN}Passed!${NC}"

echo
echo -e "${YELLOW}=== Typecheck & Tests ===${NC}"

echo -ne "${BLUE}[pyright]${NC} "
cd "$REPO_ROOT"
pyright_json="$(mktemp)"
if uv run pyright app/ --outputjson >"$pyright_json"; then
    python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
s = d.get('summary', {})
print(f\"{s.get('filesAnalyzed', 0)} files, {s.get('errorCount', 0)} errors\")
" "$pyright_json"
else
    uv run pyright app/
    rm -f "$pyright_json"
    exit 1
fi
rm -f "$pyright_json"
echo -e "${GREEN}Passed!${NC}"

echo -ne "${BLUE}[pytest]${NC} "
cd "$REPO_ROOT"
PYTHONPATH=. uv run pytest tests/ -q --no-header --tb=short
echo -e "${GREEN}Passed!${NC}"

echo
echo -e "${GREEN}=== Backend quality checks passed! ===${NC}"
echo -e "${YELLOW}Note:${NC} Run ./scripts/quality/all_quality.sh before PR/handoff if frontend may be affected."
