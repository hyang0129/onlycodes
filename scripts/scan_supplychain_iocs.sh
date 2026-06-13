#!/usr/bin/env bash
# scan_supplychain_iocs.sh — offline IOC sweep for the Mini Shai-Hulud /
# Miasma / Hades supply-chain campaign (issue #350).
#
# Targets the campaign's CONCRETE indicators against this repo + the Python
# environments it uses. Detection only — never modifies anything. Idempotent.
#
# Usage:
#   scripts/scan_supplychain_iocs.sh [--venv PATH ...] [--quiet]
#
# By default scans the repo tree and any venv found at ./.venv plus the active
# interpreter's site-packages. Pass --venv to add more environments.
#
# Exit codes:
#   0  clean — no indicators found
#   1  one or more indicators found (review the FINDING lines)
#   2  usage / environment error
#
# References: socket.dev advisory; issue #350 plan
# (docs/issue-350-supplychain-plan.md), SECURITY doc
# (docs/SECURITY_SUPPLYCHAIN.md).
#
# NOTE: intentionally NOT `set -e` — a scanner runs many greps that correctly
# return non-zero on "no match"; findings are tracked explicitly via $FINDINGS.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUIET=0
EXTRA_VENVS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --venv) shift; EXTRA_VENVS+=("${1:?--venv needs a path}");;
    --quiet) QUIET=1;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
  shift
done

FINDINGS=0
note()    { [ "$QUIET" -eq 1 ] || printf '  %s\n' "$*"; }
section() { [ "$QUIET" -eq 1 ] || printf '\n== %s ==\n' "$*"; }
finding() { printf 'FINDING: %s\n' "$*" >&2; FINDINGS=$((FINDINGS + 1)); }

# ---------------------------------------------------------------------------
# Concrete IOC strings from the advisory (C2 hosts, drop paths, payload hash).
# ---------------------------------------------------------------------------
IOC_STRINGS=(
  'thebeautifulmarchoftime'                                              # fallback C2
  'thebeautifulsnadsoftime'                                              # fallback C2 (sic)
  '/tmp/.sshu-setup.js'                                                  # SSH-worm dropper
  '6506d31707a39949f89534bf9705bcf889f1ecae3dbc6f4ff88d67a8be3d01b2'    # payload sha256
)
# stepsecurity.io egress-block marker is an evasion signal, matched separately
# (a bare grep would false-positive on this script + the docs).

# Named poisoned packages would go here as the advisory publishes them.
# Empty for now — the advisory named none concretely for our ecosystem.
POISONED_PKGS=()

# ---------------------------------------------------------------------------
# site-packages roots to scan (repo venv + active interpreter + --venv args).
# ---------------------------------------------------------------------------
SITE_DIRS=()
add_site() {
  local py="$1"
  [ -x "$py" ] || return 0
  local d
  d="$("$py" -c 'import site,sys; print("\n".join(site.getsitepackages()+[site.getusersitepackages()]))' 2>/dev/null || true)"
  while IFS= read -r line; do [ -n "$line" ] && [ -d "$line" ] && SITE_DIRS+=("$line"); done <<<"$d"
  return 0
}
[ -x "$REPO_ROOT/.venv/bin/python" ] && add_site "$REPO_ROOT/.venv/bin/python"
add_site "$(command -v python3 || true)"
for v in "${EXTRA_VENVS[@]:-}"; do [ -n "$v" ] && add_site "$v/bin/python" && add_site "$v"; done
# de-dup
if [ "${#SITE_DIRS[@]}" -gt 0 ]; then
  mapfile -t SITE_DIRS < <(printf '%s\n' "${SITE_DIRS[@]}" | sort -u)
fi

# ---------------------------------------------------------------------------
# 1. IOC string grep across repo tree (excluding this scanner + the IOC docs)
#    and across site-packages.
# ---------------------------------------------------------------------------
section "IOC string sweep"
EXCLUDES=( --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv
           --exclude-dir=dist --exclude="scan_supplychain_iocs.sh"
           --exclude="SECURITY_SUPPLYCHAIN.md" --exclude="issue-350-supplychain-plan.md" )
for ioc in "${IOC_STRINGS[@]}"; do
  if grep -rIlF "${EXCLUDES[@]}" -- "$ioc" "$REPO_ROOT" 2>/dev/null | grep -q .; then
    finding "IOC string '$ioc' present in repo tree:"
    grep -rIlF "${EXCLUDES[@]}" -- "$ioc" "$REPO_ROOT" 2>/dev/null | sed 's/^/    /' >&2
  fi
done
for sp in "${SITE_DIRS[@]:-}"; do
  [ -d "$sp" ] || continue
  for ioc in "${IOC_STRINGS[@]}"; do
    if grep -rIlF -- "$ioc" "$sp" 2>/dev/null | grep -q .; then
      finding "IOC string '$ioc' present in site-packages ($sp)"
    fi
  done
done
# stepsecurity.io egress block (evasion) — anywhere outside docs/this script
if grep -rIl --exclude-dir=.git --exclude="scan_supplychain_iocs.sh" \
     --exclude="SECURITY_SUPPLYCHAIN.md" --exclude="issue-350-supplychain-plan.md" \
     -E 'stepsecurity\.io' "$REPO_ROOT" 2>/dev/null | grep -q .; then
  finding "Reference to stepsecurity.io (campaign blocks it for evasion) found in repo"
fi
note "IOC string sweep complete."

# ---------------------------------------------------------------------------
# 2. Stray _index.js (the JS stealer loader/payload).
# ---------------------------------------------------------------------------
section "_index.js loader sweep"
for root in "$REPO_ROOT" "${SITE_DIRS[@]:-}"; do
  [ -d "$root" ] || continue
  while IFS= read -r f; do
    [ -n "$f" ] && finding "stray _index.js (Hades loader pattern): $f"
  done < <(find "$root" -name '_index.js' -not -path '*/node_modules/*' 2>/dev/null)
done
note "_index.js sweep complete."

# ---------------------------------------------------------------------------
# 3. Executable / suspicious .pth files.
#    Legit: easy-install.pth and PEP 660 editable installs (__editable__*.pth)
#    DO contain executable `import` lines — whitelist them. The campaign ships
#    rogue *-setup.pth startup hooks; flag any other .pth with executable code.
# ---------------------------------------------------------------------------
section ".pth startup-hook sweep"
for sp in "${SITE_DIRS[@]:-}"; do
  [ -d "$sp" ] || continue
  while IFS= read -r pth; do
    base="$(basename "$pth")"
    case "$base" in
      __editable__*.pth|__editable___*.pth|easy-install.pth|distutils-precedence.pth) continue;;  # legit
    esac
    case "$base" in
      *-setup.pth) finding "campaign-pattern *-setup.pth: $pth"; continue;;
    esac
    # any remaining .pth with an executable line (starts with 'import' or 'exec')
    if grep -qE '^[[:space:]]*(import|exec[ (])' "$pth" 2>/dev/null; then
      finding "non-editable .pth contains executable code: $pth"
    fi
  done < <(find "$sp" -maxdepth 1 -name '*.pth' 2>/dev/null)
done
note ".pth sweep complete."

# ---------------------------------------------------------------------------
# 4. Bun runtime dropped in temp dirs (the campaign downloads Bun to run JS).
# ---------------------------------------------------------------------------
section "Bun-in-temp sweep"
for tmp in /tmp /var/tmp "${TMPDIR:-/tmp}"; do
  [ -d "$tmp" ] || continue
  while IFS= read -r f; do
    [ -n "$f" ] && finding "Bun runtime in temp dir (campaign drop site): $f"
  done < <(find "$tmp" -maxdepth 3 \( -name 'bun' -o -name 'bun-*' -o -name '.bun' \) 2>/dev/null)
done
note "Bun-in-temp sweep complete."

# ---------------------------------------------------------------------------
# 5. Named poisoned packages must not resolve in any environment.
# ---------------------------------------------------------------------------
section "Poisoned-package resolution check"
if [ "${#POISONED_PKGS[@]}" -eq 0 ]; then
  note "No named poisoned packages in the IOC list (advisory named none for our ecosystem)."
else
  for sp_py in "$REPO_ROOT/.venv/bin/python" "$(command -v python3 || true)"; do
    [ -x "$sp_py" ] || continue
    installed="$("$sp_py" -m pip list --format=freeze 2>/dev/null | cut -d= -f1 | tr '[:upper:]' '[:lower:]')"
    for pkg in "${POISONED_PKGS[@]}"; do
      if printf '%s\n' "$installed" | grep -qixF "$(echo "$pkg" | tr '[:upper:]' '[:lower:]')"; then
        finding "poisoned package '$pkg' is installed in $sp_py"
      fi
    done
  done
  # npm lockfile
  if [ -f "$REPO_ROOT/package-lock.json" ]; then
    for pkg in "${POISONED_PKGS[@]}"; do
      grep -qF "\"$pkg\"" "$REPO_ROOT/package-lock.json" 2>/dev/null \
        && finding "poisoned package '$pkg' referenced in package-lock.json"
    done
  fi
fi
note "Poisoned-package check complete."

# ---------------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------------
echo
if [ "$FINDINGS" -eq 0 ]; then
  echo "CLEAN: no supply-chain indicators found (issue #350 IOC set)."
  exit 0
else
  echo "$FINDINGS indicator(s) found — review FINDING lines above." >&2
  exit 1
fi
