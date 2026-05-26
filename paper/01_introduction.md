# 01 — Introduction

**Target length:** ~1 page (combined with abstract: 1.25 page; ceiling 1.5).

## Structure (5 beats)

### Beat 1: Open with the disagreement (~3 sentences)

The field has shipped three contradictory claims about coding-agent tool surfaces in the last 24 months:

- **SWE-agent (Yang et al., NeurIPS 2024):** specialized Agent-Computer Interface tools (`find_file`, `search_dir`, `goto`, structured `edit` with linter) beat raw shell by 10.7 points on SWE-bench Lite with GPT-4-Turbo. *Conclusion: build dedicated tools for agents.*
- **mini-SWE-agent (2025, same group):** bash-only, 100 lines of Python, no tool-calling interface, hits >74% on SWE-bench Verified with modern models. *Conclusion: as models improved, specialized tools became unnecessary.*
- **Anthropic "Code execution with MCP" (Nov 2025) + Cloudflare "Code Mode" (Sept 2025 / Feb 2026):** routing tool calls through a single `execute_code` MCP tool reduces tokens by 98.7–99.9% on external API surfaces (Drive, Salesforce, Stripe, Cloudflare's 2,500-endpoint API). *Conclusion: code-as-action beats discrete tool calls.*

None of these papers ran the crossed comparison.

### Beat 2: Why the gap matters (~3 sentences)

Liu et al. (arXiv:2604.14228, Apr 2026) provide a careful architectural taxonomy of Claude Code's tool surface (Read, Grep, Glob, Edit, Write, Bash, plus MCP/skills/hooks/agents) — but explicitly do not ablate. Rombaut (arXiv:2604.03515) catalogs 13 OSS coding-agent scaffolds along 12 dimensions, again descriptively. The empirical question — *which surface earns its tokens on which task* — has been studied for external tools (the Anthropic/Cloudflare blogs) and for two-arm comparisons (SWE-agent), but never for the internal IDE-tool surface with a crossed three-arm design and regime stratification.

### Beat 3: What we do (~3 sentences)

We hold model, harness, and prompts fixed and vary only the tool surface across three arms: `tool_rich` (the full Claude Code IDE surface), `bash_only` (the mini-SWE-agent setup ported into our harness), and `code_only` (a single MCP `execute_code` tool with persistent Python REPL and Bash). We evaluate on two regime-disjoint benchmarks: 93 synthetic computation tasks (`artifact`) with hidden deterministic graders, and 100 SWE-bench Mini instances (modification + multi-file) under the standard post-agent `test_patch` protocol. We run three independent seeds and report mean ± stderr.

### Beat 4: What we find (~3 sentences + the 3 contribution bullets)

We find a **regime-dependent sign-flip in cost asymmetry** that the prior trajectory does not predict. Specifically:

1. **Sign-flip:** On the computation regime, `code_only` is ~33% cheaper than `tool_rich` at equal pass rate (`code_only / tool_rich` median cost ratio = 0.67). On the modification regime, `tool_rich` is ~11% cheaper than `code_only` at equal pass rate (total cost \result{}). The ranking inverts.
2. **Capability invariance:** Pass rates are statistically tied across all three arms within each regime (≤2pp spread). The asymmetry lives entirely in cost/turns.
3. **Agent-design dependence:** Replicating on a second agent surface (Codex CLI) flips the SWE-bench ranking again — Codex's bash-first prompt design makes `code_only` cheaper than `tool_rich` even on modification. Optimal tool surface is jointly determined by regime AND agent design.

### Beat 5: Roadmap of the paper (~2 sentences)

Section 2 positions our contribution against SWE-agent's ACI claim, mini-SWE-agent's bash-only result, and the Code Mode external-MCP trajectory. Section 3 describes the three-arm harness and the post-Issue-#287 integrity protocol. Section 4 specifies benchmarks and metrics; Section 5 reports the headline numbers and sign-flip; Section 6 establishes the IDE-bash redundancy table; Section 7 interprets through the Capability Overlap Principle.

---

## Drafting notes

- **Lead with disagreement, not with the contribution.** The three-contradictory-claims framing buys reviewer attention faster than "we ablate tool surfaces."
- **Cite Liu et al. (2604.14228) early** — this is the paper our work directly complements. Reviewers who know that paper will read ours as the empirical follow-up.
- **The Capability Overlap Principle citation goes in §3.4 and §7**, not the intro. Intro stays empirical-forward.
- **No claim of "always" or "universally."** The contribution is the regime-dependence; absolute claims are walking into reviewer-2 fire.
- **Do not call the project "OnlyCode" or "Code Mode."** Both phrases collide with prior work and the sign-flip finding makes them inaccurate anyway. Use `code_only` (the arm name, in `\texttt{}`) when referring to the single-MCP-execute arm.
