# Supply-chain security — Mini Shai-Hulud / Miasma / Hades (issue #350)

Durable record of the supply-chain exposure analysis for this repo and the
mitigations applied. The campaign (471 poisoned artifacts: 411 npm + 60 PyPI)
**explicitly targets MCP and AI-developer environments**, which matches this
repo's setup (an MCP exec-server + Claude-driven harness).

**Status at analysis (2026-06-10):** *not known to be compromised.* No named IOC
packages in the manifests; `~/.ssh` held only `known_hosts` (no private keys).
This is hardening + passive-exposure reduction, not incident response.

Source advisory: socket.dev — "Mini Shai-Hulud, Miasma, and Hades worms target
bioinformatics and MCP developers via malicious …".

---

## How the campaign is relevant here

- **PyPI vectors:** rogue `*-setup.pth` startup hooks, obfuscated `_index.js`
  loaders searching `sys.path`, trojanized `.abi3.so` native extensions — all
  download a Bun runtime and run the Hades JS stealer.
- **npm vectors:** typosquats / MCP-impersonation packages with malicious
  install hooks.
- **Hades stealer targets:** GitHub/npm/PyPI/RubyGems/JFrog creds, cloud tokens,
  Kubernetes SA material, SSH keys, Docker config, shell history, `.env`,
  AI-tool credentials.
- **Worm propagation:** SSH key abuse (`/tmp/.sshu-setup.js`), **Docker socket
  exploitation** (`/var/run/docker.sock`), CI/CD workflow manipulation.
- **Anti-analysis:** `_index.js` opens with fake LLM instructions "designed to
  derail LLM-based scanners / analyst copilots."

---

## Indicators of compromise (IOCs)

Swept by [`scripts/scan_supplychain_iocs.sh`](../scripts/scan_supplychain_iocs.sh)
(offline, idempotent; exit non-zero on any hit):

| Indicator | Type |
|---|---|
| `thebeautifulmarchoftime` | fallback C2 host string |
| `thebeautifulsnadsoftime` | fallback C2 host string (sic) |
| `/tmp/.sshu-setup.js` | SSH-worm dropper path |
| `6506d31707a39949f89534bf9705bcf889f1ecae3dbc6f4ff88d67a8be3d01b2` | payload SHA256 |
| `*.stepsecurity.io` egress block | defense-evasion marker |
| stray `_index.js` | JS stealer loader |
| `*-setup.pth` / other executable non-editable `.pth` | PyPI startup hook |
| Bun runtime under `/tmp`, `/var/tmp` | payload runtime drop |

Whitelisted as legitimate (not flagged): `easy-install.pth`,
`__editable__*.pth` / `__editable___*.pth` (PEP 660 editable installs **do**
contain executable `import` lines), `distutils-precedence.pth`. The onlycodes
harness also legitimately rewrites editable `.pth` files (see
`swebench/cache.py`).

**No named poisoned packages** were published for our ecosystem in the advisory;
`POISONED_PKGS` in the scanner is the place to add them if/when named.

---

## Mitigations applied (Track A — this repo)

| Item | What | Where |
|---|---|---|
| Python dep pinning | `requirements.txt` is now a hash-locked lockfile generated from `requirements.in`; install with `pip install --require-hashes`. Pinned to the validated known-good set (numpy 1.26.x, scikit-learn 1.8.x, datasets 4.8.x). | `requirements.in`, `requirements.txt` |
| npm hygiene | Documented **`npm ci` only** (never bare `npm install`); lockfile has 114 integrity hashes. | `README.md` → Dependencies |
| IOC sweep | Offline detector for the table above. | `scripts/scan_supplychain_iocs.sh` |
| Analyst-copilot guardrail | The `analyze/` pipeline now fences untrusted transcript text and instructs subagent + synthesizer to treat it as inert data, never instructions — defeats the `_index.js` "fake instruction" anti-analysis trick. New `prompt_injection` pathology slug. | `swebench/analyze/run.py`, `analyze/subagent_prompt.md`, `analyze/synthesizer_prompt.md` |

## Mitigations applied (Track B — shared hub_1 devcontainer)

> The devcontainer at `/workspaces/hub_1/.devcontainer/` is **shared by all repos
> in the workspace**, not owned by onlycodes. Changes here were authorized as an
> explicit exception to workspace context-segregation (owner migrating other
> repos off later). See `docs/issue-350-supplychain-plan.md` Track B.

| Item | What | Where |
|---|---|---|
| `npm ci` on provision | exec-server node deps install from the locked tree by default. | `.devcontainer/post-create.sh` |
| `--require-hashes` install | repo requirements install hash-locked. | `.devcontainer/post-create.sh` |
| docker.sock containment | see residual-risk register below. | `.devcontainer/` |

---

## Residual-risk register

1. **`/var/run/docker.sock` is reachable from the devcontainer (HIGH, accepted).**
   The SWE-bench **image runtime backend (ADR-0004, the default & only supported
   path)** *requires* the Docker daemon — the harness shells out to the `docker`
   CLI (`swebench/container*.py`, `image_store.py`) to pull official images, run
   per-arm containers, and `docker cp` artifacts. The socket cannot simply be
   removed without disabling the benchmark. **Mitigation:** access is gated to
   the `vscode` user via group membership rather than left world-writable
   (`chmod a+rw` removed); a `docker-socket-proxy` least-privilege allowlist is
   the recommended next step (not yet applied — would need an allowlist derived
   from the exact daemon calls the harness makes). Worm-amplification risk
   (Hades' "Docker socket exploitation" vector) is **documented and accepted**
   for as long as the socket is bind-mounted.

2. **Transitive Python tree is large (`datasets` pull).** Now hash-pinned, so a
   poisoned *new* release is not pulled until the lockfile is deliberately
   regenerated — but the lockfile must be refreshed consciously and re-reviewed.

3. **SWE-bench runs each instance's spec `install` command verbatim** and agent
   code can `pip install` arbitrary packages. **Bounded:** the agent now runs
   *inside ephemeral official SWE-bench containers* (`swebench/container_agent.py`),
   executed code is network-isolated (`unshare -n`), and credentials are
   `docker cp`'d into throwaway containers that are never committed — so an
   agent-installed package cannot reach host devcontainer credentials. Residual
   risk is confined to the disposable container.

4. **Credential blast radius.** Live Claude Max creds (`~/.claude/.credentials.json`,
   `~/.claude-profiles/`) are bind-mounted; `GH_TOKEN`/`GITHUB_TOKEN` are in the
   environment. These map directly onto Hades' target list. (Operational note:
   `GH_TOKEN` was observed *invalid* during this work — `gh` auth failing.)

---

## Compromise runbook (if an IOC ever fires)

Treat any hit as full credential rotation — Hades exfiltrates broadly:

1. **Isolate:** stop running containers; disconnect the devcontainer from the
   daemon (`unset DOCKER_HOST` / stop Docker Desktop) before further triage.
2. **Rotate everything reachable:** GitHub tokens (`GH_TOKEN`/`GITHUB_TOKEN` +
   PATs), npm/PyPI/RubyGems/JFrog tokens, **all Claude Max profiles in
   `~/.claude-profiles/`** (rotate via maxmanager), cloud tokens, SSH keys.
3. **Scrub:** rebuild the devcontainer from a clean image; purge venvs and
   `node_modules`; reinstall from the locked manifests (`npm ci`,
   `pip install --require-hashes`).
4. **Hunt:** re-run `scripts/scan_supplychain_iocs.sh`; grep process trees and
   egress logs for the C2 strings; check `/tmp` for Bun and `.sshu-setup.js`.
5. **CI/CD:** review recent workflow changes (registry poisoning + workflow
   manipulation are named propagation vectors).

---

## Re-running the sweep

```bash
scripts/scan_supplychain_iocs.sh            # repo + .venv + active interpreter
scripts/scan_supplychain_iocs.sh --venv /workspaces/.venvs/onlycodes
```

Exit 0 = clean; exit 1 = indicator(s) found (review the `FINDING:` lines).
