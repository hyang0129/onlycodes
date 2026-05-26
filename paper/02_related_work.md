# Related Work

Inventory of prior work relevant to onlycodes, with one to two sentences on how onlycodes differs. Maintained as the canonical "defend the novelty gap" document — keep it current before any draft circulates.

Last updated: 2026-05-16 (initial population from issue #158 related-work investigation).

---

## Direct precedent (must distinguish carefully)

### SWE-agent — Yang, Jimenez, Wettig, Lieret, Yao, Narasimhan, Press. *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering.* NeurIPS 2024. arXiv:2405.15793.
Introduced the Agent-Computer Interface (ACI): `find_file`, `search_dir`, `goto`, structured `edit` with linter. Two-arm ablation (ACI vs raw shell) on 300 SWE-bench issues with GPT-4-Turbo, ACI won by +10.7pp. **Delta:** we run three arms (`tool_rich` / `bash_only` / `code_only`), evaluate on 2026 models where the bash-only baseline is now competitive, and stratify by task regime — directly updating the 2024 ACI claim with the missing code-execution arm and regime breakdown.

### Terminal Agents Suffice for Enterprise Automation — Bechard et al. (ServiceNow). arXiv:2604.00073, Mar 2026.
Argues terminal+filesystem agents match more elaborate architectures on enterprise API automation. Same "less is more" thesis as ours but on enterprise APIs, not code repair. **Delta:** different task domain; no crossed three-arm tool-surface design; no regime stratification. We ask the analogous question for code-repair tasks with a three-surface design.

---

## Industry priors (motivate but don't pre-empt the `code_only` arm)

### Anthropic — *Code execution with MCP.* Engineering blog, Nov 2025.
Reports ~98.7% token reduction (~150k → ~2k) by having the model write code that calls MCP tools rather than calling them directly. **Delta:** focused on external MCP tools (Drive, Salesforce, Stripe); no SWE-bench evaluation; no internal IDE tool comparison. Motivates our `code_only` arm.

### Cloudflare — *Code Mode* (Sept 2025) and *Code Mode MCP: give agents an entire API in 1,000 tokens* (Feb 2026).
TypeScript sandbox over MCP; ~99.9% token reduction on the 2,500-endpoint Cloudflare API. **Delta:** engineering blog, no benchmark, external API surface, no coding-agent context.

### Verdent — SWE-bench Verified Technical Report (blog, 2025).
Anecdotally reports an ablation removing advanced tools while keeping bash+read+write+edit, with little performance change. **Delta:** informal, single-vendor, no public methodology. Closest *informal* signal of our finding — cite as motivation, not as a scoop.

---

## Bash-only lineage (`bash_only` arm precedent)

### mini-SWE-agent — SWE-agent group, 2025. GitHub `SWE-agent/mini-swe-agent`. No standalone paper.
~100 lines of Python, bash-only, no tool-calling interface, >74% on SWE-bench Verified. Canonical "bash-only" scaffold on the HAL SWE-bench Verified Mini leaderboard. **Delta:** our `bash_only` arm is a direct re-implementation. They never run the IDE-rich or code-only contrasts on the same harness.

### Live-SWE-agent — Xia, Wang, Yang, Wei, Zhang. arXiv:2511.13646, Nov 2025.
Self-evolves a scaffold starting from mini-SWE-agent; 77.4% SWE-bench Verified. Ablates "removing tool-creation" but not code-only MCP. **Delta:** their axis is scaffold evolution; ours is fixed-surface ablation with a code-only arm and regime stratification.

---

## Code-as-action lineage (orthogonal axis)

### CodeAct — Wang et al. *Executable Code Actions Elicit Better LLM Agents.* ICML 2024. arXiv:2402.01030.
Python interpreter as unified action space, contrasted with JSON tool calls; +20% over JSON tool-calling on general agent benchmarks. **Delta:** CodeAct's contrast is "code as action" vs "JSON tool calls" at the *action-encoding* level. We ask "which **tools** should sit behind the API." Foundational citation, orthogonal contribution.

### OpenHands platform — Wang et al. ICLR 2025. *OpenHands Software Agent SDK.* arXiv:2511.03690 (Nov 2025).
CodeAct-style platform for general agents. **Delta:** platform paper; no tool-surface ablation on internal IDE primitives.

---

## Theoretical framing (citation must be Zhang et al., NOT Wang et al.)

### Are Tools All We Need? Unveiling the Tool-Use Tax in LLM Agents — Zhang, Xiong, Zhong, Jiang, Yuan, Li, Lin. arXiv:2605.00136, Apr 30, 2026.
Introduces the **Capability Overlap Principle** ("many apparent tool gains arise on samples already solvable by native CoT") and a **tool-use tax**. **Delta:** general-purpose (math/QA), not coding agents. We use their vocabulary to frame why five of six Claude Code IDE tools are bash-subsets in capability, but supply the empirical evidence on a coding benchmark.

> **Citation hygiene:** earlier roadmap drafts attributed this to "Wang et al." That is wrong. It is Zhang et al. Fix anywhere it leaks.

---

## Claude-Code-specific architectural descriptions (no ablation — empirical gap we fill)

### Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems — Liu et al. (MBZUAI/UCL). arXiv:2604.14228, Apr 2026.
Architectural walkthrough of Claude Code's Read/Grep/Glob/Edit/Write/Bash + MCP + skills + hooks. **Delta:** explicitly no ablation on SWE-bench. Our paper is the natural empirical complement — the experiment Liu et al. described the design space for but never ran.

### Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures — Rombaut. arXiv:2604.03515, Apr 2026.
Twelve-dimension taxonomy of 13 OSS coding scaffolds. **Delta:** descriptive, no ablation. Useful vocabulary to borrow for the methodology section.

### Building AI Coding Agents for the Terminal / OpenDev — Bui. arXiv:2603.05344, Mar 2026.
Design-lessons document. **Delta:** not empirical.

---

## Stratified SWE-bench evaluation (regime taxonomy precedents)

### SWE-Bench Pro — Scale AI. arXiv:2509.16941, Sept 2025.
Long-horizon, multi-file split with easy/medium/hard difficulty tiers. **Delta:** difficulty stratification, not tool-surface × regime crossing.

### Multi-SWE-bench — ByteDance. arXiv:2504.02605, Apr 2025.
Time-based difficulty stratification. **Delta:** same as above.

### SWE-PolyBench — Amazon, 2025.
File-level + CST-node retrieval metrics, multi-language. **Delta:** retrieval-focused.

### SWE Atlas — arXiv:2605.08366.
Codebase Q&A / Test Writing / Refactoring split. Closest to a regime taxonomy in spirit. **Delta:** doesn't cross with tool-surface arms.

### Ganhotra — *Multi-File Frontier* (blog, Mar 2025).
Empirically shows SWE-bench Verified is 85.8% single-file. **Delta:** motivates our (modification, multi-file) cell needing dedicated subset selection rather than uniform sampling.

---

## Tool-pruning / tool-budget literature (orthogonal problem)

All ask "select the right *k* tools from a large pool" rather than "compare three fixed surfaces":

- Budget-Aware Tool Use — arXiv:2511.17006
- ToolTree — arXiv:2603.12740
- Trajectory Reduction — arXiv:2509.23586
- ToolScope (semantic-redundancy merging)
- *MCP tool descriptions are smelly!* — arXiv:2602.14878 (ablates descriptions, not the tool set)

**Delta:** different problem (selection vs surface design).

---

## Efficiency / cost analysis (adjacent axis)

### SWE-Effi — Fan et al. arXiv:2509.09853, Sept 2025.
Accuracy vs token/time effectiveness; scaffold-vs-model interaction. **Delta:** orthogonal axis. Cite for the cost-asymmetry observation (our bash_only arm uses ~1.7× the dollars of baseline at the same pass rate).

---

## Scaffold-component ablations (component-level, not surface-level)

- Confucius Code Agent — arXiv:2512.10398
- Agentic Harness Engineering — arXiv:2604.25850

**Delta:** ablate components (memory, middleware, individual tools) on evolved harnesses; we hold the harness fixed and swap the entire tool surface.

---

## Bottom line for the related-work section

Three arcs the paper sits between:

1. **The SWE-agent → mini-SWE-agent → onlycodes trajectory** on IDE tool design. We are the third data point.
2. **The CodeAct → Anthropic/Cloudflare Code Mode lineage** on code-as-action. We port it from external tools to internal IDE primitives, with a coding benchmark.
3. **The Zhang et al. "tool-use tax" framing.** We supply coding-agent evidence for a principle stated on general reasoning.

The risks reviewers will press hardest:
- "How is this not SWE-agent?" → 2026 models, three arms, regime stratification.
- "How is this not Terminal Agents Suffice?" → code repair domain, three-surface crossed design, regime stratification.
- "How is this not Anthropic/Cloudflare?" → internal IDE primitives (not external APIs), evaluated on a coding benchmark.

Keep this document updated each time a 2026 preprint relevant to coding-agent tool surfaces appears.
