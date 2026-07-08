#!/usr/bin/env bash
# Regenerate paper statistics, figures, and main.pdf from committed experiment data.
# Runs no experiment: everything here reads experiments/results/*. Run from anywhere.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python

echo "[1/3] paper statistics ..."
"$PY" experiments/paper_stats.py

echo "[2/3] paper figures (vector PDF) ..."
"$PY" experiments/paper_figures.py

echo "[3/3] pdflatex + bibtex ..."
cd paper
pdflatex -interaction=nonstopmode main.tex >/dev/null
bibtex main >/dev/null 2>&1 || true
pdflatex -interaction=nonstopmode main.tex >/dev/null
pdflatex -interaction=nonstopmode main.tex >/dev/null

fail=0
PAGES=$(pdfinfo main.pdf | awk '/^Pages/{print $2}')
OVERFULL=$(grep -c 'Overfull' main.log || true)
UNDEF=$(grep -ciE 'undefined (reference|citation|control)' main.log || true)
ERRS=$(grep -cE '^! ' main.log || true)

printf '  pages=%s overfull=%s undefined=%s errors=%s\n' "$PAGES" "$OVERFULL" "$UNDEF" "$ERRS"
[ "${PAGES:-0}" -eq 6 ]     || { echo "FAIL: expected 6 pages, got ${PAGES:-?}" >&2; fail=1; }
[ "${OVERFULL:-1}" -eq 0 ]  || { echo "FAIL: $OVERFULL overfull boxes" >&2; fail=1; }
[ "${UNDEF:-1}" -eq 0 ]     || { echo "FAIL: undefined references/citations" >&2; fail=1; }
[ "${ERRS:-1}" -eq 0 ]      || { echo "FAIL: $ERRS LaTeX errors" >&2; fail=1; }
[ "$fail" -eq 0 ] || exit 1
echo "OK: paper/main.pdf, 6 pages, clean."
