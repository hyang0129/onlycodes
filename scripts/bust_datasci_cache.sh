#!/usr/bin/env bash
# bust_datasci_cache.sh — one-time cache-bust for scikit-learn + matplotlib instances
#
# Removes the lockfile.txt for each affected cache entry so the harness
# triggers a full venv rebuild on the next run (picking up the new Python
# version + pre-install pins added in issue #203).
#
# Usage:
#   bash scripts/bust_datasci_cache.sh
#
# The SWEBENCH_CACHE_ROOT env var controls where cache entries live.
# Defaults to ~/.cache/swebench if unset.

set -euo pipefail

CACHE_ROOT="${SWEBENCH_CACHE_ROOT:-${HOME}/.cache/swebench}"
INSTANCES_DIR="${CACHE_ROOT}/instances"

# scikit-learn 0.20–0.22 instances (Python 3.10 + setuptools/numpy/cython pins)
SKLEARN_IDS=(10427 10803 11206 11596 3840 12704 13283 13496 13013 13864 14125 14710 15094)

# matplotlib 3.1–3.7 era instances (Python 3.11 + numpy<2 + cython<3 + setuptools<65 pins)
MPL_IDS=(13859 19763 21042 22767 23088 23476 24177 24637 25126 25442 25772 26160)

bust() {
    local prefix="$1"; shift
    for id in "$@"; do
        local entry="${INSTANCES_DIR}/${prefix}-${id}"
        local lockfile="${entry}/lockfile.txt"
        if [[ -f "${lockfile}" ]]; then
            echo "Busting ${prefix}-${id} (removing lockfile)"
            rm -f "${lockfile}"
        elif [[ -d "${entry}" ]]; then
            echo "  ${prefix}-${id}: directory exists but no lockfile — skipping"
        else
            echo "  ${prefix}-${id}: not cached — nothing to do"
        fi
    done
}

echo "=== bust_datasci_cache.sh ==="
echo "Cache root: ${CACHE_ROOT}"
echo ""

echo "--- scikit-learn (${#SKLEARN_IDS[@]} instances) ---"
bust scikit-learn__scikit-learn "${SKLEARN_IDS[@]}"

echo ""
echo "--- matplotlib (${#MPL_IDS[@]} instances) ---"
bust matplotlib__matplotlib "${MPL_IDS[@]}"

echo ""
echo "Done. Affected entries will rebuild on next swebench run."
echo "(New builds will use Python 3.10 for scikit-learn and pre-install pins for matplotlib.)"
