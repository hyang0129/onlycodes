# Citation Prose Audit — §02 Related Work
**Date:** 2026-05-28 | **Auditor:** Claude Code (automated, WebFetch against paper HTML)

---

## TL;DR

Of the five claims audited, **one is accurate** (claim 5 — the 77.4% figure and mini-SWE-agent starting point), **one is correct-but-incomplete** (claim 4 — ToolScope named only by its merger half), and **three are misleading or wrong**: claim 1 names the ablation correctly but misstates what is ablated; claim 2 labels an execution-graded benchmark as "retrieval-focused"; and claim 3 asserts a "scaffold-vs-model interaction" framing that is secondary to the paper's actual resource-constraint / token-snowball thesis, and the basis for citing SWE-Effi for our cost-asymmetry observation is unsupported by the paper.

---

## Claim 1 — Live-SWE-agent ablation specifics

**Paper:** Xia et al. arXiv:2511.13646  
**Prose location:** line 72–73

**Current prose:**
> Ablates "removing tool-creation" but not code-only MCP.

**What the paper actually says (§4.3, Table 4):**
The paper runs three ablations on 50 SWE-bench Verified problems: (1) removing tool-creation (drops to 62.0%), (2) removing reflection (drops to 64.0%), and (3) full Live-SWE-agent (76.0%). The paper explicitly says "removing the on-the-fly tool creation ability…i.e., using the base mini-SWE-agent." So the name "removing tool-creation" is accurate. However, the ablation is specifically about *on-the-fly, during-run* tool creation — the scaffold writes new Python tool wrappers mid-run — not about removing a tool category from the tool surface. It is an architectural self-evolution ablation, not a tool-surface ablation in the same sense as onlycodes. "Code-only MCP" is not discussed anywhere in the paper.

**Verdict:** ⚠️ misleading

**Proposed rewrite:**
> Ablates removing on-the-fly *tool-creation* (scaffold self-writing new wrappers during a run) and removing reflection; neither ablation studies a code-only MCP surface.

---

## Claim 2 — SWE-PolyBench framing

**Paper:** Amazon arXiv:2504.08703  
**Prose location:** line 123–124

**Current prose:**
> File-level + CST-node retrieval metrics, multi-language. **Delta:** retrieval-focused.

**What the paper actually says (§1, §3, §4):**
SWE-PolyBench is an execution-graded repository-level benchmark (pass rate on fail-to-pass / pass-to-pass tests is the primary metric, mirroring SWE-bench). The CST-node metrics (file and node recall/precision) are *secondary diagnostic* tools; the authors explicitly say "pass rate is a central metric" and that CST metrics "fail to capture" full performance, making them complementary. The benchmark covers 2,110 instances across Java, JS, TypeScript, and Python. Calling it "retrieval-focused" inverts the relationship: execution grading is primary, CST analysis is supplementary.

**Verdict:** ❌ wrong

**Proposed rewrite:**
> Execution-graded repo-level benchmark across four languages (Java, JS, TS, Python), 2,110 instances; adds CST-node retrieval diagnostics as secondary metrics alongside pass rate. **Delta:** multi-language execution eval with syntax-tree diagnostics; does not cross tool-surface arms or vary the agent's tool surface.

---

## Claim 3 — SWE-Effi framing

**Paper:** Fan et al. arXiv:2509.09853  
**Prose location:** line 171–172

**Current prose:**
> Accuracy vs token/time effectiveness; scaffold-vs-model interaction. **Delta:** orthogonal axis. Cite for the cost-asymmetry observation (our bash_only arm uses ~1.7× the dollars of baseline at the same pass rate).

**What the paper actually says (§1, §3, Obs. 1, Table 3):**
The paper's primary frame is resource-constrained effectiveness — introducing metrics that jointly score accuracy and resource consumption (tokens, time). Within that frame it identifies two empirical findings: the "token snowball" effect (naive memory accumulation causing super-linear token growth) and "expensive failures" (failed attempts consume ~4× the tokens/time of successes). The scaffold-model synergy finding ("effectiveness is not an inherent property of its scaffold but emerges from synergy with the base LLM") is a secondary observation derived from comparing five scaffolds × multiple models. Crucially, the paper compares scaffolds at their *default* tool configurations — it does not compare different tool surfaces at the same pass rate, so the basis for citing SWE-Effi "for the cost-asymmetry observation (our bash_only arm uses ~1.7× the dollars)" is a stretch: the paper's asymmetry is about *failed vs. successful attempts within the same configuration*, not across tool surfaces at matched pass rates. The framing in §02 swaps primary and secondary contributions.

**Verdict:** ⚠️ misleading

**Proposed rewrite:**
> Introduces resource-aware effectiveness metrics for coding agents; primary findings are a "token snowball" effect (super-linear token growth from memory accumulation) and "expensive failures" (failed runs consume ~4× the resources of successes); also notes scaffold effectiveness depends on model synergy. **Delta:** orthogonal axis (resource-constrained eval, not tool-surface ablation). Cite for the expensive-failures framing as motivation that cost comparisons across arms need to control for pass-rate differences.

---

## Claim 4 — ToolScope framing

**Paper:** arXiv:2510.20036  
**Prose location:** line 162

**Current prose:**
> ToolScope (semantic-redundancy merging)

**What the paper actually says (Abstract, §3, §4, Table 3 ablations):**
ToolScope has two equally-presented components: ToolScopeMerger (semantic-redundancy consolidation) and ToolScopeRetriever (context-compressive tool ranking). In ablation, merging delivers the larger accuracy gain (22% on Seal-Tools) while the retriever delivers the larger *context* reduction (98.6% token reduction on BFCL). Both are framed as essential: the abstract addresses "two distinct problems simultaneously." Naming only the merger understates the system and misses the retrieval half, which is the component closest in spirit to tool-pruning/selection literature. The collective "tool-pruning / tool-budget" bucket framing is still defensible — both components address selecting from a large pool — but the parenthetical description is incomplete.

**Verdict:** ⚠️ correct-but-incomplete

**Proposed rewrite:**
> ToolScope (semantic-redundancy merging + context-compressive retrieval)

---

## Claim 5 — Live-SWE-agent score and starting point

**Paper:** Xia et al. arXiv:2511.13646  
**Prose location:** line 72

**Current prose:**
> Self-evolves a scaffold starting from mini-SWE-agent; 77.4% SWE-bench Verified.

**What the paper actually says (Abstract, §1, Table 1):**
77.4% is the headline number in the abstract, achieved with Gemini 3 Pro without test-time scaling. With Claude 4.5 Sonnet the score is 75.4%. The paper states "Live-SWE-agent starts with the most basic agent scaffold with only access to bash tools (e.g., mini-SWE-agent)" and confirms it is "implemented on top of mini-SWE-agent." Both sub-claims check out.

**Verdict:** ✅ accurate

---

## Risks if Not Fixed

- **Claim 1 (ablation description):** A reviewer familiar with Live-SWE-agent will note that "removing tool-creation" means *scaffold self-writing wrappers during a run*, not removing a tool category. They may argue we conflate architectural self-evolution ablation with tool-surface ablation, weakening the novelty framing of our fixed-surface design.

- **Claim 2 (SWE-PolyBench "retrieval-focused"):** If a reviewer has read SWE-PolyBench, they will object that it is execution-graded and our delta is wrong — execution grading and multi-language coverage are the actual distinguishing features, not retrieval. This makes the delta look uninformed.

- **Claim 3 (SWE-Effi "scaffold-vs-model interaction" + cost-asymmetry cite):** The cite-for sentence claims SWE-Effi supports a cross-arm, matched-pass-rate cost comparison, but SWE-Effi's cost asymmetry is within-arm (failed vs. successful runs). A reviewer who reads SWE-Effi will call this a misuse of the citation and may question the 1.7× figure's provenance.

- **Claim 4 (ToolScope named by merger only):** Minor, but a reviewer who knows ToolScope will notice the retriever is omitted. Given the retriever is the component most analogous to "tool-pruning," leaving it out looks like cherry-picking the component that fits the bucket framing.
