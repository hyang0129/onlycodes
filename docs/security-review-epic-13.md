# Security Review: Epic #13 MCP Passthrough

**Date**: 2026-04-17
**Reviewer**: Claude Code (Opus)
**Scope**: Interceptor bypass surface in `execute_code` and the MCP passthrough architecture shipped by Epic #13
**Status**: COMPLETE
**Related**: `ADR-001-mcp-passthrough.md`, `.claude-work/EPIC_13_ADR.md`, `.claude-work/EPIC_13_DECOMPOSITION.md`, issue #26

---

## Executive Summary

The passthrough architecture has a sound trust model: **dispatch interception in
`bridge-server.js` is the real security boundary**, content scanning in
`interceptor.js` is defense-in-depth (and trivially bypassable by design), and
credential isolation via `buildStrippedEnv()` + `unshare -n` prevents the
obvious exfiltration paths.

No critical findings. Two high findings concern (a) the `delete_repo` dispatch
rule relying on a hard-coded tool name that the upstream `@github/mcp` server
can change or alias, and (b) `unshare --user --map-root-user --net` leaving a
root-mapped user namespace available to agent code, which expands the sandbox
escape surface beyond the ADR's "network isolation only" framing. Several
medium and low findings document the residual bypass surface. The
`\bgh\b` content rule is bypassable in dozens of ways and this report does
**not** treat those bypasses as findings — they are expected and the ADR
already accepts this ("content scanner bypassable (ADR-accepted)" in the risk
register).

The report closes with a recommendations list ordered by severity. All
high-severity items have proposed mitigations that are small, well-scoped, and
suitable for a Wave 4 follow-up issue.

---

## Trust Model

The Epic #13 design layers multiple defenses, each with a different purpose.
It is important not to conflate them, because they have very different
strength properties.

| Layer | Purpose | Strength | Where |
|-------|---------|----------|-------|
| **Content scanning** | Nudge the agent away from disallowed patterns (e.g. `gh`) with an actionable error | **Defense-in-depth. Bypassable by design.** | `interceptor.js` `checkContent()` |
| **Dispatch interception** | Block specific sub-MCP tool names (e.g. `delete_repo`) before they reach the sub-MCP manager | **Real trust boundary.** Applied uniformly at the single call path on the bridge server. | `bridge-server.js` + `interceptor.js` `checkDispatch()` |
| **Network isolation** | Prevent the `execute_code` subprocess from reaching the internet or non-UDS network sockets | **Real trust boundary** (for network egress), with caveats around the user-namespace variant. | `exec-server.js` `unshare --user --map-root-user --net` / `unshare -n` |
| **Credential isolation** | Keep secrets (`GITHUB_TOKEN`, API keys, SSH agent) out of the subprocess environment and the session log | **Real trust boundary.** Relies on `STRIPPED_VARS` + heuristic regex + allowlist. | `exec-server.js` `buildStrippedEnv()`; `sub-mcp-manager.js` `buildSubMcpEnv()` |
| **UDS scoping** | Per-PID socket path prevents cross-talk between parallel `exec-server` instances | Correctness property, not a hostile-code defense. AF_UNIX enforces FS permissions. | `config-loader.js` `getBridgeSocketPath()`; bridge-server SIGTERM handler |

**Key architectural statement (ADR-001 Decision 3):** the agent is treated as
*curious but not hostile*. The threat model is "an LLM tries something that
would bypass an intended restriction" — not "an attacker with shell access
tries to exfiltrate." Under that threat model:

- The content-scan deny rule is adequate as a *steering signal* (the agent
  reads the actionable error and tries the sanctioned path).
- The dispatch deny rule is adequate as a *hard block* (the agent cannot
  invoke `delete_repo` even if it emits it explicitly via `mcp_bridge.call`).
- Network isolation is adequate as a *fail-closed default* (no accidental
  reach to the open internet).
- Credential isolation is adequate as a *no-leak default* (no accidental token
  exposure in subprocess env or session logs).

If the threat model were upgraded to "adversarial agent with goal-directed
exploit capability," several of the medium/low findings in this report would
escalate. That re-scoping is explicitly out of scope for Epic #13.

---

## Findings

### Critical Findings

None.

### High Findings

#### H1 — `delete_repo` dispatch rule is tied to a specific tool name that the upstream sub-MCP can rename or alias

**Severity**: High
**Surface**: Dispatch interception (`bridge-server.js` + `interceptor.js`)
**Exploitability**: Medium. Requires `@github/mcp` to ship a rename, alias, or
batch tool — out of `onlycodes`'s control.

**Description**:

`checkDispatch()` in `interceptor.js` matches on **exact tool-name equality**:

```js
if (rule.tool === toolName) { ... }
```

The shipped rule denies the literal string `"delete_repo"`. The upstream
`@modelcontextprotocol/server-github` package can:

1. Rename `delete_repo` to `delete_repository` (or any variant) in a future
   version — the deny rule would silently stop firing with no warning.
2. Expose a batch tool such as `bulk_update_repos` or `admin_action` that
   internally performs deletion given the right arguments — the deny rule
   would not cover it.
3. Expose a generic `graphql` or `rest_api_call` tool that routes arbitrary
   GitHub API requests — trivially bypasses any name-based rule.

Any of these upstream changes converts a blocked action into an allowed one
with no code change on the `onlycodes` side. The interceptor has no notion
of tool *semantics*, only names.

**Mitigation (proposed)**:

- Pin `@modelcontextprotocol/server-github` to an exact version in
  `package.json` (use `=` or a `package-lock.json` hash), not a caret range.
- Add an **allow-list** variant of `checkDispatch` as a config option:
  instead of denying specific names, allow only specific names. This flips
  the failure mode to closed — upstream adding new tools requires an explicit
  `onlycodes` config change to enable them.
- Add a startup check in `sub-mcp-manager.js` that calls `listTools` on each
  sub-MCP and *logs* any tool name that isn't in a known-set, so changes are
  at least visible in operator logs.
- Document in `passthrough-config.json` comments that dispatch rules are
  string-matched against upstream tool names and must be reviewed on every
  sub-MCP version bump.

---

#### H2 — `unshare --user --map-root-user --net` creates a privileged user namespace, expanding sandbox surface beyond network isolation

**Severity**: High
**Surface**: `exec-server.js` subprocess spawn
**Exploitability**: Low under the stated threat model (curious agent). Medium
if the threat model were adversarial.

**Description**:

`executeCode()` in `exec-server.js` tries two forms of `unshare` in order:

```js
{ check: ["unshare", ["--user", "--map-root-user", "--net", "true"]], ... },
{ check: ["unshare", ["-n", "true"]], ... },
```

The first form — `--user --map-root-user --net` — creates **both** a new user
namespace and a new network namespace. Inside the user namespace, the caller
appears as UID 0 (mapped root). This is standard rootless-container behavior,
but it has side effects the ADR does not address:

1. **Inside the namespace, the agent's code runs as "root"**, with
   capabilities over objects scoped to that namespace. This includes:
   - Ability to `mount --bind`, `mount -t tmpfs`, and `chroot` within the
     namespace (useful for some escape tricks against loosely-defined outer
     paths).
   - Ability to create additional nested namespaces.
   - Ability to use BPF / netfilter operations scoped to the namespace (low
     concern in practice but expands the kernel attack surface).
2. **The `/proc/self` view changes**: files inside the namespace can show
   root ownership even though the outer system treats the process as the
   unprivileged host user. Code that introspects `/proc/self/status` or
   `/proc/self/uid_map` to decide "am I sandboxed?" will mis-detect.
3. **The user namespace is itself a well-known attacker-useful primitive**:
   historical Linux kernel CVEs (CVE-2022-0185, CVE-2023-0386, CVE-2023-3269,
   etc.) have leveraged user-namespaces-as-unprivileged-user as the entry
   point. Every one of these CVEs is patched in supported kernels, but the
   residual surface is nonzero and growing.
4. The `unshare -n` fallback (second attempt) does **not** open a user
   namespace; it only opens a network namespace and requires `CAP_SYS_ADMIN`
   from the parent. On a hardened host the fallback would fail; on a
   privileged container both forms work — and the first one is chosen
   preferentially, expanding the surface unnecessarily.

**Mitigation (proposed)**:

- **Prefer `unshare -n` when `CAP_SYS_ADMIN` is available**, and only fall
  back to `--user --map-root-user --net` when the privileged form fails. The
  current ordering is inverted (it prefers the user-namespace variant).
  Changing the preference order is a one-line edit in `exec-server.js`.
- If the user-namespace variant must remain (to support unprivileged hosts),
  pair it with `seccomp` to block namespace-creation syscalls inside the
  sandbox (`unshare`, `clone` with namespace flags, `setns`). This requires
  a `--setuid`/seccomp wrapper like `bubblewrap` (`bwrap`) or a small
  syscall filter program.
- Document the kernel-CVE residual risk in the ADR and the operator README
  so the trade-off is explicit.
- Add a startup self-test that asserts the chosen form actually denies
  network egress (e.g. `curl --max-time 2 https://1.1.1.1`) and fails closed
  if it does not.

---

### Medium Findings

#### M1 — `STRIPPED_VARS` uses a regex-plus-allowlist; regex is conservative and new credential-shaped env vars may still leak

**Severity**: Medium
**Surface**: `exec-server.js` `buildStrippedEnv()`
**Exploitability**: Low — requires a specific env var naming convention in
the parent environment.

**Description**:

```js
for (const key of Object.keys(env)) {
  if (
    /KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL/i.test(key) &&
    key !== "TERM" &&
    key !== "COLORTERM"
  ) {
    delete env[key];
  }
}
```

This is a belt-and-braces heuristic on top of the explicit `STRIPPED_VARS`
list. It catches most common credential-shaped names, but:

1. Env vars that hold credentials without any of those substrings pass
   through: e.g. `DATABASE_URL` (often contains an embedded password),
   `OPENAI_BASE_URL` (sometimes contains an API key in the path), `NPM_AUTH`,
   `DOCKER_CONFIG` (path to a file that contains credentials), `KUBECONFIG`,
   `AZURE_STORAGE_CONNECTION_STRING`.
2. The `TERM` / `COLORTERM` exception is an allowlist of *two* specific names
   to preserve terminal behavior, but any other benign var with `TOKEN` /
   `KEY` in the name would also be stripped with no exception — a
   correctness nuisance, not a security issue, but worth noting.
3. The regex is applied to *names*, not *values*. An env var named
   `MY_SETTING` whose value is `ghp_xxxxxxxxxxxxxxxxxxxx` (a literal
   GitHub personal access token) flows through untouched.

**Mitigation (proposed)**:

- Invert the scheme: use an **allowlist** of safe env var names that are
  explicitly passed through to `execute_code` subprocesses (similar to
  `SAFE_VARS` in `sub-mcp-manager.js`), plus `ONLYCODES_BRIDGE_SOCK`. Strip
  everything else.
- Alternately: ship a `passthrough-config.json` field `executeCodeEnvAllow`
  that operators can extend per deployment without code edits.
- Add a value-side regex check that warns (not blocks) when a passthrough
  env var's *value* matches a known credential shape like `ghp_[A-Za-z0-9]{36,}`
  or `sk-[A-Za-z0-9]{20,}` — for detection, not enforcement.

---

#### M2 — `mcp_bridge.py` default socket path uses `os.getppid()`, which is not the exec-server PID when the subprocess is not a direct child

**Severity**: Medium
**Surface**: `mcp_bridge.py` fallback socket resolution
**Exploitability**: Low. Requires `ONLYCODES_BRIDGE_SOCK` env to be missing
AND the caller to be in a non-trivial process tree.

**Description**:

```python
def _get_socket_path():
    if 'ONLYCODES_BRIDGE_SOCK' in os.environ:
        return os.environ['ONLYCODES_BRIDGE_SOCK']
    ppid = os.getppid()
    return f'/tmp/onlycodes-bridge-{ppid}.sock'
```

If `ONLYCODES_BRIDGE_SOCK` is stripped or unset and the `mcp_bridge.py`
module is imported from, say, a grandchild process (a subprocess spawned by
the `execute_code` subprocess — which is legal and common in bash scripts),
`os.getppid()` returns the parent's PID, not the `exec-server.js` PID. This
produces a socket path that does not exist → `McpBridgeError` at connect
time. A benign failure, but worth noting that the fallback is fragile.

More importantly: **if an attacker could guess another parallel
`exec-server.js` process's PID**, an `mcp_bridge.call` from one sandbox
could — in principle — land on a neighbor's bridge. This requires:

1. The attacker to win a PID guess (PIDs on Linux are a 32-bit space by
   default but are usually reused in the low 100k range; predictable).
2. The target `exec-server` to be running with permissive socket
   permissions. AF_UNIX stream sockets created by `net.createServer()` in
   Node.js default to `0666`-ish permissions on most setups.

AF_UNIX permissions are enforced by the filesystem, so if the target socket
is in `/tmp` and world-readable/connectable, any local user could connect.
On multi-tenant systems (multiple `exec-server.js` instances running under
the same UID), one sandbox can reach another sandbox's bridge if it knows
the PID.

**Mitigation (proposed)**:

- Create the bridge socket with an explicit `fs.chmodSync(sockPath, 0o600)`
  after `listen()` in `bridge-server.js`. AF_UNIX check mode is enforced at
  `connect()` time on Linux, so 0600 prevents cross-user connections. Same
  UID connections are *not* prevented by mode bits — see M3.
- Put the socket in a per-invocation directory `/tmp/onlycodes-${pid}/bridge.sock`
  with `chmod 0700` on the directory. This prevents even same-UID enumeration
  if combined with a hardened `/tmp` mount (sticky bit / user-dir separation).
- Remove the `os.getppid()` fallback in `mcp_bridge.py` entirely: if
  `ONLYCODES_BRIDGE_SOCK` is not set, raise `McpBridgeError` immediately
  with a clear message. This eliminates the fragile fallback without loss
  of functionality under normal operation (the env var is always set by
  `exec-server.js`).

---

#### M3 — UDS does not enforce cross-sandbox isolation within a single UID

**Severity**: Medium
**Surface**: `bridge-server.js` socket access control
**Exploitability**: Low. Requires multiple `exec-server.js` instances
running as the same UID (currently uncommon; `swebench run --parallel` is
the prototypical case).

**Description**:

Even with the per-PID socket path from ADR Decision 2, if two
`exec-server.js` instances (PIDs A and B) both run as the same UID, and both
bridge sockets are created with default mode `0666` / `0777` — a sandbox
launched by instance A can `connect()` to instance B's socket if it can
enumerate PIDs (trivial via `/proc/`).

The per-PID path is a *collision-avoidance* mechanism, not an
*access-control* mechanism. The ADR correctly identifies this in its
Decision 2 discussion but does not enforce mode bits on the socket.

Under the stated threat model (curious agent, not adversarial), this is not
immediately exploitable: the agent has no reason to hunt for sibling
bridges. Under an adversarial threat model, it is a cross-sandbox channel.

**Mitigation (proposed)**: Same as M2 — `chmod 0600` on the socket file, or
place it in a `0700` per-invocation directory.

---

#### M4 — `checkContent()` rebuilds `new RegExp(rule.pattern)` on every call

**Severity**: Medium (performance / DoS, not confidentiality)
**Surface**: `interceptor.js` `checkContent()`
**Exploitability**: Low — requires a malicious config, not malicious code.

**Description**:

```js
for (const rule of rules) {
  const regex = new RegExp(rule.pattern);
  if (regex.test(code)) { ... }
}
```

Each `execute_code` invocation re-compiles every `pattern` regex against the
rule array. Rules loaded from `passthrough-config.json` are validated at
load time (`config-loader.js` calls `new RegExp(rule.pattern)` to catch
malformed patterns), but the compiled form is not cached. Cost scales with
rules × request rate.

More importantly: a malicious config could include a catastrophic-backtracking
regex (ReDoS) that hangs the whole MCP server on crafted input. Since the
config is trusted (it lives in the repo and is only updated by repo
committers), this is not a practical exploit vector — but pre-compiling
regexes at load time instead of on each call would also let the loader
reject patterns that take too long to test against a calibration string.

**Mitigation (proposed)**:

- Cache compiled regexes in `_rules` at load time: `rule._compiled = new RegExp(rule.pattern)`.
- On config load, run each compiled regex against a 1 KB calibration string
  with a time budget (say 10 ms); reject patterns that exceed it. Catches
  obvious ReDoS at load time.

---

### Low / Informational Findings

#### L1 — `\bgh\b` is trivially bypassable — expected and by design

**Severity**: Low (informational)
**Surface**: `interceptor.js` `checkContent()`

The content-scan rule is a steering signal, not a trust boundary. It is
bypassable in dozens of ways (examples, non-exhaustive):

- **Word-boundary evasion**: `"g""h" status` (shell string concatenation),
  `g\h status` (bash backslash elision), `g""h status`, `eval "gh status"`
  (the `eval` argument is expanded after the scan).
- **Environment variable expansion**: `X=gh; $X status`, `alias g=gh; g status`
  (aliases only work in interactive shells but the agent could write to
  `.bashrc`), `CMD=$(echo gh); $CMD status`.
- **Base64 / encoding**: `echo Z2g= | base64 -d | xargs` — runs `gh`.
- **PATH lookup via abspath**: `/usr/bin/gh status` — `\bgh\b` matches both
  `gh` and `/usr/bin/gh` here because `/` is a word boundary, so this
  specific vector is caught. But `./gh status` does match the rule as well.
  However `$(command -v gh) status` splits `gh` across `$()` — the regex
  still matches inside `command -v gh`.
- **Alternative clients**: `curl -H "Authorization: Bearer $TOKEN" https://api.github.com/...`
  — does not mention `gh`, reaches the same endpoints. Blocked by network
  isolation (`unshare -n`), not by content scan.
- **Python requests**: `import urllib.request; urllib.request.urlopen("https://api.github.com/...")`
  — same.
- **Heredocs and subshells**: `bash <<EOF\ngh status\nEOF` — the regex still
  matches because the pattern is applied to the source string literally and
  the string `gh` appears in the heredoc body.
- **Dynamic code**: `python -c "__import__('os').system('g'+'h'+' status')"`
  — the concatenation `'g'+'h'` hides the substring from a simple regex
  that expects `gh` as a contiguous byte run.
- **File-first**: write a wrapper script with `gh` in its *body* (which is
  a file that the agent creates — content scanning runs on the script sent
  to `execute_code`, not on files the script writes), then execute the
  wrapper. Any execution of a file containing `gh` from a separate
  `execute_code` call is blocked (same scan); but if the agent writes
  `/tmp/w.sh` in call N and runs `bash /tmp/w.sh` in call N+1, call N+1's
  source does not contain `gh`.

**Why this is NOT a finding**: the ADR explicitly accepts this. The rule's
purpose is to produce an *actionable* error when the agent instinctively
reaches for `gh` — the error message tells it to use `mcp_bridge.call`
instead. Bypassing requires the agent to *want* to bypass, which is outside
the threat model (curious, not hostile). Even if the agent did bypass, the
network isolation layer blocks the outbound API call.

**Action**: Document in the interceptor source and in `passthrough-config.json`
that content rules are steering signals, not security boundaries. (Already
done partially in `.claude-work/EPIC_13_ADR.md` and
`EPIC_13_DECOMPOSITION.md` Risk Register; should be echoed in source
comments to prevent future contributors from over-relying on them.)

---

#### L2 — `execute_code` has full filesystem access (read/write) within the sandbox's view

**Severity**: Low (informational)
**Surface**: `exec-server.js` subprocess spawn
**Exploitability**: N/A (by design)

**Description**:

The `unshare -n` / `unshare --user --map-root-user --net` variants create a
*network* namespace only — they do not create a *mount* namespace. The
subprocess shares the host filesystem view. It can read:

- `/etc/passwd`, `/etc/resolv.conf`, other world-readable system files.
- `$HOME` of the user running `exec-server.js` — but note that `HOME` is
  stripped from the subprocess env, so the subprocess does not *know* its
  real home. `os.path.expanduser("~")` may return `/` or `None` depending
  on Python's defaults.
- The repo directory (including `passthrough-config.json`, the interceptor
  rules, the session log, all committed source) if the subprocess happens
  to chdir there.
- Mounted bind-volumes in a Docker context — including the
  `~/.claude-profiles/` credentials bind-mount in this workspace's devcontainer
  config.

Write access is limited to what the user can write (typically `/tmp`, the
temp cwd, `/var/tmp`).

**Why this is low**: this is explicitly the design. The ADR does not
promise filesystem isolation (only network + credential isolation). A full
filesystem sandbox would require `bwrap` / `nsjail` / a mount namespace and
is out of scope for Epic #13.

**Informational mitigation**: If filesystem isolation is a future goal,
`bubblewrap` is a drop-in replacement for `unshare -n` that also gives a
mount namespace with declarative path allow-lists. `bwrap --ro-bind / /
--proc /proc --dev /dev --unshare-all <cmd>` is a reasonable starting
point.

---

#### L3 — `execute_code` can spawn long-lived background processes that outlive the request

**Severity**: Low
**Surface**: `exec-server.js` subprocess lifecycle

**Description**:

`executeCode()` uses `spawn(...)` with `detached: false` and kills the
immediate child on timeout via `child.kill("SIGKILL")`. However:

1. The child can `nohup some_script.sh &` or `setsid`-fork a grandchild.
2. `child.kill("SIGKILL")` kills only the immediate child (the `unshare`
   wrapper process), not its descendants. Grandchildren detached with
   `setsid` will not receive the signal and will outlive the request.
3. Those grandchildren inherit the stripped environment (good) and are
   inside the namespace-isolated network (good), but they continue consuming
   CPU / memory / open files on the host. A benchmark run that expects
   clean cleanup will accumulate zombie-root processes.

Same-UID process enumeration then lets a later `execute_code` invocation
signal or read `/proc/$pid` of prior invocations' grandchildren.

**Mitigation (proposed)**: Spawn the child as a process-group leader
(`detached: true, stdio: ...` then `process.kill(-child.pid, "SIGKILL")`
to signal the whole group on timeout). Standard node.js idiom.

---

#### L4 — Session logs contain the full `code` payload; a prompt-injected script could write sensitive data into them

**Severity**: Low
**Surface**: `exec-server.js` `logSession`

**Description**:

`logSession()` writes the full `code` string into `logs/session.jsonl`.
Stdout is also captured. If the agent's script prints a sensitive value
(e.g. it reads a file from the host filesystem — see L2 — and prints it),
that value is persisted to the session log unfiltered.

**Why this is low**: the session log is local to the `exec-server` host
and is intended for debugging. It is not a confidentiality boundary. The
existing integration test (`test-integration.js` Test 9) already verifies
that `GITHUB_TOKEN`'s *value* never lands in the log — because the log
records only what the subprocess prints, and the subprocess can't print a
stripped env var.

**Mitigation (informational)**: Document the session log as "may contain
any content the agent printed" in `README.md` so operators don't treat it
as clean.

---

#### L5 — `sub-mcp-manager` inherits `stderr: "inherit"` from the sub-MCP child

**Severity**: Low (informational / observability)
**Surface**: `sub-mcp-manager.js` `StdioClientTransport` config

**Description**:

```js
const transport = new StdioClientTransport({
  command: serverConfig.command,
  args: serverConfig.args,
  env,
  stderr: "inherit",
});
```

The sub-MCP's stderr is inherited by the main `exec-server.js` process.
This is useful for debugging (surfacing sub-MCP crash messages), but:

1. If the sub-MCP has a bug that prints credentials to stderr (some tools
   do this on auth errors), those credentials land on the `exec-server.js`
   stderr and — depending on how Claude Code runs the MCP server — may be
   captured in Claude Code's logs.
2. The main `exec-server.js` stderr is *not* itself content-scanned or
   filtered.

**Why this is low**: `@github/mcp` is known to not print `GITHUB_TOKEN` to
stderr under normal operation. Future sub-MCPs might. The isolation property
the ADR promises is about the `execute_code` subprocess env and the session
log — not about MCP-server-internal stderr.

**Mitigation (proposed)**: Change `stderr: "inherit"` to `stderr: "pipe"`
with a sanitizing reader that strips obvious credential substrings before
re-emitting. Low priority.

---

#### L6 — `interceptor.checkContent` is not called on `mcp_bridge.call` tool arguments

**Severity**: Low (by design)
**Surface**: `bridge-server.js` request handling

**Description**:

The bridge handles `call` requests by:

```js
const denied = checkDispatch(req.tool);
if (denied) { ... }
const result = await manager.callTool(req.server, req.tool, req.args || {});
```

Only the *tool name* is checked. The `args` payload is forwarded verbatim.
For `@github/mcp`, this means an argument like `{"title": "gh status"}` in
a `create_issue` call is sent through untouched — as it should be (the
string `gh` appearing in an issue title is legitimate).

**Why this is informational**: this is the correct design. Content scanning
is for `execute_code` source; dispatch scanning is for tool names. Mixing
them (scanning tool args) would produce false positives and would not add
security because the sub-MCP is trusted to handle its own inputs.

---

#### L7 — `exec-server.bundle.mjs` is a committed build artifact — supply-chain trust is shifted to the committer

**Severity**: Low (informational)
**Surface**: Bundle build process

**Description**:

The bundle is a committed 21k-LOC artifact. ADR Decision 3 pins `esbuild`
as a dev-dep and commits a `build` script, so from #22 forward any reviewer
can reproduce the bundle byte-for-byte. Before #22 landed, the bundle was
unreviewable in practice — any reviewer trusted the committer to have not
inserted a change in the bundle that diverges from the source.

This is not a live exploit vector; it is a historical note. Going forward,
CI should verify `npm run build` produces the committed artifact.

**Mitigation (informational)**: Add a CI check that runs `npm run build` and
`diff exec-server.bundle.mjs <(git show HEAD:exec-server.bundle.mjs)` to
enforce source↔bundle consistency. If they differ, fail CI. Same pattern as
`go generate ./... && git diff --exit-code`.

---

## Bypass Surface Analysis

### Content Scanning (Defense-in-Depth)

**Characterization**: The `\bgh\b` regex is an *agent-steering signal*, not a
*security boundary*. Its purpose is to emit an actionable error when the
agent instinctively reaches for the `gh` CLI, nudging it toward
`mcp_bridge.call("github", ...)` instead.

**Bypass vectors** (non-exhaustive, documented as L1 above):

| Vector | Severity | Exploitability | Mitigation |
|--------|----------|---------------|-----------|
| String concat in bash (`g""h`, `g\h`) | Low | Trivial | None — accept; rely on dispatch + network |
| Base64/encoding | Low | Trivial | None — accept |
| Alternative HTTP clients (curl, requests) | Low | Trivial | Blocked by `unshare -n`, not by content scan |
| Heredocs (string literally contains `gh`) | Low | Not actually a bypass — rule matches | N/A |
| Python string concat `'g'+'h'` | Low | Trivial | None — accept |
| Wrapper-file indirection | Low | Moderate (two calls) | None — accept |
| Process substitution `$(echo gh)` | Low | Trivial (pattern matches the literal `gh` in `echo gh`) | N/A |

**Conclusion**: Content scanning cannot be relied upon as a hard block. The
deny rule is valuable for its *steering* effect, not its *enforcement*
effect. This is documented in the ADR and is not a finding.

### Dispatch Interception (Trust Boundary)

**Characterization**: Dispatch interception is **the real trust boundary**.
It is applied uniformly at a single code path (`handleRequest` in
`bridge-server.js`), before any sub-MCP call is forwarded. There is no
alternative route to the sub-MCP manager that skips the interceptor:

1. Agent-written code in `execute_code` cannot reach the sub-MCP manager
   except via `mcp_bridge.py`, which speaks NDJSON over the UDS.
2. The UDS is served by `bridge-server.js`, whose only `method: "call"`
   handler runs `checkDispatch(req.tool)` before dispatching.
3. The sub-MCP manager (`sub-mcp-manager.js`) exposes no public surface
   other than the JS module API, which is only used by `bridge-server.js`
   (and by tests). `execute_code` subprocesses cannot `import` JS modules
   from the main MCP process.

**Residual risks**:

- **H1 above**: name-based rules are fragile against upstream renames /
  aliases / batch tools. Mitigation proposed.
- Config hot-reloading: the interceptor caches rules on first call
  (`_rules` in `interceptor.js`); a config change to `passthrough-config.json`
  is not picked up until the process restarts. This is a correctness /
  ops issue, not a security one — but operators should know to restart
  `exec-server.js` after editing the config.
- `checkDispatch` is not applied to `method: "get_schema"`. This is
  intentional: schema enumeration is read-only. But an auditor should note
  that `get_schema` returns the full input-schema for potentially blocked
  tools (`delete_repo`'s schema is fetchable). The agent can *see* that the
  tool exists even though it cannot *call* it. Acceptable by design.

**Conclusion**: Dispatch interception is a real, reliable boundary for
tool-name-based denial, modulo H1. There is no identified path to reach
`sub-mcp-manager.callTool` that skips `checkDispatch`.

### Credential Isolation

**Characterization**: Two independent stripping layers:

1. **`buildStrippedEnv()`** in `exec-server.js`: applied to `execute_code`
   subprocess env. Explicit deny list (`STRIPPED_VARS`) + heuristic regex
   (`/KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL/i`). Critical
   integration test (`test-integration.js` Test 8 and 9) verifies
   `GITHUB_TOKEN` is absent from both the subprocess env and the session
   log.
2. **`buildSubMcpEnv()`** in `sub-mcp-manager.js`: applied to each
   sub-MCP child process env. Uses an *allowlist* of safe vars plus the
   explicit `serverConfig.env` (e.g. `["GITHUB_TOKEN"]` for `@github/mcp`).
   This is a stronger pattern than the `execute_code` side.

**Residual risks**: M1 (regex-plus-allowlist can miss credential-shaped
vars that don't match the regex). Mitigation proposed.

**Side channels**:
- `/proc/${exec_server_pid}/environ` is readable by the owning UID. An
  `execute_code` subprocess can read its parent's full env (including the
  stripped-from-subprocess credentials) via `/proc`. **This is a real
  leak.** See **M5 below — promoting from hidden to explicit finding.**

---

#### M5 — `/proc/${parent_pid}/environ` is readable from the sandbox and exposes credentials that were stripped from the subprocess env

**Severity**: Medium-High (depending on threat model)
**Surface**: Kernel `/proc` filesystem
**Exploitability**: Trivial if the agent knows to try it. Under the
"curious agent" threat model the agent would not think to look. Under an
adversarial threat model this is a 1-line exfiltration.

**Description**:

On Linux, `/proc/${pid}/environ` is readable by the process owner. The
`execute_code` subprocess runs as the same UID as its `exec-server.js`
parent, so:

```python
# Inside execute_code:
ppid = os.getppid()  # exec-server.js PID
with open(f"/proc/{ppid}/environ", "rb") as f:
    env_blob = f.read()
# env_blob now contains GITHUB_TOKEN, ANTHROPIC_API_KEY, etc. — the full
# unstripped parent env.
```

`unshare -n` creates a network namespace but does **not** mount a separate
`/proc`. The subprocess sees the host `/proc`. User-namespace variant is
the same.

**Moreover**: `/proc/self/environ` of the subprocess is stripped (correct),
but the subprocess can walk `/proc` and read `environ` of any same-UID
process — not just its parent. It can enumerate:

- The main `exec-server.js` PID's env (has all credentials).
- The sub-MCP children's env (has `GITHUB_TOKEN`).
- Any other same-UID process (a Claude Code instance's env, a VS Code
  extension's env, etc.).

`test-integration.js` Test 8 verifies `GITHUB_TOKEN` is absent from
`os.environ.get("GITHUB_TOKEN")` — this correctly passes because
`os.environ` reflects only the subprocess's own env. It does NOT cover the
`/proc/$parent/environ` read path.

**Why this is medium-high and not critical under the stated threat model**:
The agent has no reason to look at `/proc` — it is not trying to exfiltrate.
But the defense this subverts (env stripping) is advertised as a real trust
boundary. If it can be trivially bypassed, the promised property
("credentials absent from the subprocess") is weaker than implied.

**Mitigation (proposed)**:

- **Best**: Run the subprocess under a different UID. Create a dedicated
  unprivileged user `onlycodes-sandbox` (or use the `--setuid` feature of
  `bubblewrap`) and drop privileges before `exec()`. `/proc/$other_uid_pid/environ`
  is not readable across UIDs.
- **Good**: Mount a fresh `/proc` in a PID namespace (`unshare --pid
  --mount-proc`) — this hides processes outside the namespace. Combined
  with the existing network namespace. Non-trivial (requires mount
  namespace permissions) but achievable.
- **Decent**: Explicitly spawn the subprocess with
  `prctl(PR_SET_DUMPABLE, 0)` — no, that doesn't help here, `environ` is
  readable regardless.
- **Minimum**: Spawn `exec-server.js` itself with `prctl(PR_SET_DUMPABLE, 0)` —
  the parent's `/proc/${pid}/environ` then requires root to read. On Linux
  this turns off the owner-readable default and only `ptrace`-capable
  readers can read it.
- **Documentation-only**: Add to the ADR that env stripping is bypassable
  via `/proc` and is only effective against tools that look at their own
  env. Update the integration test to cover the `/proc/parent/environ`
  case as a negative test that the token value *is* present in the parent
  (documenting the known limitation).

I am adding this as **M5** to the Medium Findings section; it was
originally hidden inside the credential-isolation prose.

---

### Unix Socket Security

**Characterization**: The bridge socket is created at
`/tmp/onlycodes-bridge-${pid}.sock`. AF_UNIX stream sockets are
filesystem objects with mode bits.

**Current state**:

- `net.createServer()` in Node.js creates the socket with mode derived from
  the `umask` (typically `0666 & ~umask` → `0644` or `0600`+world-none
  depending on umask). There is no explicit `chmod` in `bridge-server.js`
  after `listen()`.
- Per-PID path prevents collision but not access.
- Both `SIGTERM` and `SIGINT` unlink the socket on shutdown. `SIGKILL`
  leaves a stale socket file (mitigated by the `unlinkSync` at the start
  of the next `start()`).

**Findings**: M2 (getppid fallback) and M3 (same-UID access control).

**Conclusion**: The bridge socket is correctly scoped for correctness
(collision-avoidance across parallel `exec-server.js`). It is NOT hardened
against hostile same-UID access. Under the stated threat model this is
acceptable; under an adversarial model it is not.

### Sandbox (`unshare -n` / User-namespace variant)

**Characterization**: Network namespace creation via `unshare`. Two forms
tried in order, `--user --map-root-user --net` first.

**Network properties confirmed by the integration test**: the subprocess
cannot reach the internet (the `curl https://...` pattern in any language
would fail to resolve DNS even before connecting — `/etc/resolv.conf` may
be readable but the network stack has no route).

**Remaining attack surface**:

- **H2 above**: user-namespace variant creates additional privilege
  primitives inside the namespace. Mitigation proposed.
- **L2 above**: no mount / FS isolation.
- **L3 above**: process-group escape via setsid/detached forks.
- **M5 above**: `/proc/$other_pid/environ` is readable.
- **AF_UNIX is NOT isolated by the network namespace**. The ADR correctly
  notes this (ADR-001 Decision 2, `EPIC_13_ADR.md` Decision 2 rationale).
  The subprocess can `connect()` to the bridge socket because AF_UNIX uses
  the filesystem, not the network namespace.
- **AF_UNIX to arbitrary same-UID sockets is also not blocked**. The
  subprocess could `connect()` to any world-reachable UDS — system service
  sockets (`/var/run/docker.sock` if present, dbus, etc.). This is a
  first-class sandbox-escape primitive if such a socket happens to be
  accessible. See the devcontainer config: if the host mounts any
  privileged UDS, an `execute_code` subprocess can talk to it.

**Conclusion**: Network isolation is effective for *IP* egress; it is
ineffective against *UDS* egress. This is by design (the bridge itself
relies on UDS).

---

## Characterization of Trust Boundaries

**Content scanning is defense-in-depth.** It is a best-effort
agent-steering mechanism. It is NOT a security boundary. Any comment in the
source, ADR, or config that implies otherwise should be corrected.

**Dispatch interception is the real trust boundary** for *which sub-MCP
tools* the agent can invoke. It is reliable for name-equality denial and is
applied at a single, unavoidable chokepoint (`handleRequest` in
`bridge-server.js`). Its reliability is constrained only by name-stability
of upstream sub-MCPs (H1).

**Network isolation (`unshare -n`) is the real trust boundary** for IP
egress. It is reliable for that purpose. It does NOT isolate filesystem,
process, or UDS.

**Credential isolation (`buildStrippedEnv` + `buildSubMcpEnv`) is the real
trust boundary** for env-var-based credential exposure, with the caveat of
M5 (`/proc/parent/environ`).

The layered design is sound. No single layer is a complete defense on its
own; they are meant to compose, and they do. The main residual risks are:

1. H1 — dispatch rule name-brittleness (mitigation: pin versions + allow-list semantics).
2. H2 — user-namespace variant over-preference (mitigation: prefer plain `unshare -n`).
3. M5 — `/proc/parent/environ` bypasses env stripping (mitigation: PID namespace or separate UID).

---

## Recommendations (ordered by severity)

### High priority (should land before public release, if any)

1. **Fix H2**: swap the `unshare` preference order in `exec-server.js` so
   that plain `unshare -n` is tried first, falling back to
   `--user --map-root-user --net` only when the privileged form is
   unavailable. One-line change, no functional regression on privileged
   hosts. (**~1 hour**)

2. **Fix H1**: pin `@modelcontextprotocol/server-github` to an exact
   version (no caret) and document the "review-on-bump" rule for dispatch
   deny-list maintenance in `passthrough-config.json`. (**~1 hour**)

3. **Mitigate M5**: either
   (a) run `execute_code` under a dedicated unprivileged UID, or
   (b) add `unshare --pid --mount-proc --fork` to the sandbox wrapper so
       `/proc` shows only the subprocess tree.
   Option (b) is simpler; option (a) is stronger. (**~1 day for (b); ~2–3 days for (a)**)

### Medium priority

4. **Fix M2 / M3**: `fs.chmodSync(sockPath, 0o600)` in `bridge-server.js`
   after `server.listen()`. Drop the `os.getppid()` fallback in
   `mcp_bridge.py`. (**~2 hours, including integration test updates**)

5. **Fix M1**: invert `STRIPPED_VARS` from a deny-list to an allow-list,
   or add a `passthrough-config.json` field `executeCodeEnvAllow`.
   (**~3 hours**)

6. **Fix M4**: precompile regexes at config-load time and reject slow
   patterns with a calibration string. (**~1 hour**)

### Low priority

7. **L3**: spawn subprocess as process-group leader, kill the whole group
   on timeout. (**~30 min**)

8. **L7**: add a CI check that `npm run build` produces the committed
   `exec-server.bundle.mjs`. (**~30 min**)

9. **L5 / L6**: document in source comments and README. (**~30 min**)

### Documentation

10. Update `interceptor.js` and `passthrough-config.json` to explicitly
    state that content rules are steering signals, not security
    boundaries.

11. Update ADR-001 with an "Out of scope" section documenting: no FS
    isolation, no PID isolation, no UID isolation, no same-UID UDS
    isolation. Makes future reviewers' lives easier.

---

## Conclusion

No critical unmitigated findings. Two high findings (H1, H2) have simple,
low-risk mitigations that should be applied before any external use. One
additional medium-high finding (M5 — `/proc/parent/environ` credential
readback) should be tracked even though the current threat model does not
make it immediately exploitable, because it subverts a property the ADR
advertises as a trust boundary.

The epic's stated architecture holds up: **dispatch interception is the
real trust boundary for sub-MCP invocations**, content scanning is
defense-in-depth (as intended), and the credential + network isolation
layers are reliable within the threat model. The attack surface documented
here is almost entirely inherent to running arbitrary agent code with a
same-UID subprocess and a network namespace; moving to a stricter sandbox
(`bubblewrap`, UID separation, PID namespace) would close the remaining
items but is beyond the scope of Epic #13.

The findings in this review should be filed as follow-up issues (one per
high, one per medium at minimum) and addressed as part of Wave 4 hardening
or a subsequent security-focused epic.
