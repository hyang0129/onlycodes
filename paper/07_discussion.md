# 07 — Discussion

**Target length:** 0.5 page (ceiling 0.75). Lead with the three numbered prescriptions for practitioners — that's what the workshop audience expects.

**Status:** outline; finalize after §5 numbers freeze.

---

## 7.1 Why the sign-flip exists (~3 sentences)

The per-turn cost ranking is regime-invariant: `tool_rich` costs ~$0.024/turn vs ~$0.019/turn for `bash_only` and `code_only` across both regimes. What changes is the *turn count*. On computation tasks, all three arms converge in ~5–6 turns because the problem is bounded by a single script; the per-turn tax dominates and `tool_rich` loses. On modification tasks, `bash_only` and `code_only` spend ~40% more turns exploring the codebase (the agent re-issues `find` / `cat` chains that the IDE-tool agent would replace with a single `Grep`/`Glob`/`Read`); this turn-count savings more than offsets the per-turn tax for `tool_rich`.

## 7.2 Where the method works / doesn't (~0.2 page)

- **Works.** The sign-flip holds across both seed_1 datapoints, across all 9 artifact categories, and across both major SWE-bench Mini subsets (Django/Sphinx and the datasci tail). The magnitude is large (22pp gap between cost-ratio deltas) relative to seed variance.
- **Doesn't (or unclear).** Per-repo SWE-bench splits show flatter `tool_rich` advantage on matplotlib and astropy than on Django/Sphinx — possibly because these repos have less exploration surface (smaller codebases, fewer files). The sign-flip framing predicts this; the per-repo evidence is weaker for the *magnitude* of the modification-regime tool_rich advantage than for its existence.
- **Open.** Whether the sign-flip widens or narrows on larger codebases (full SWE-bench Verified, not Mini) is unanswered. n=100 SWE-bench instances is sufficient for the qualitative claim, not for repo-level scaling laws.

## 7.3 Implications for agent design (~0.2 page)

The workshop audience expects actionable claims. Three:

1. **For agents on computation-dominated workflows** (notebook-style analyses, ML hyperparameter sweeps, data engineering jobs): drop the IDE surface. The `code_only` arm's 33% cost savings is real. The current default of shipping the full surface is a tax on this workload.
2. **For agents on modification-dominated workflows** (codebase bug-fix, multi-file refactor): keep the IDE surface, especially `Edit`. The per-turn tax is real but offset by exploration efficiency. Removing IDE tools to "save tokens" is a 11% cost regression at fixed pass rate.
3. **For agent surface designers:** the optimal surface depends on workload regime AND on the agent's prompt/training. Codex CLI's bash-first design makes `code_only` competitive on modification tasks where Claude Code's IDE-first design does not. There is no universal optimum; surface choice is a workload-conditional design decision.

## 7.4 Connection to prior trajectory (~0.15 page)

Place our result in the SWE-agent → mini-SWE-agent → Code Mode arc:

- SWE-agent (2024) was right about specialized tools — *on modification tasks with a 2024-era model.* The "+10.7pp pass rate" was real.
- mini-SWE-agent (2025) was right about bash sufficing — *on modification tasks with 2025-era models.* The capability gap closed; the cost-efficiency gap (which mini-SWE-agent does not measure) is what our paper recovers.
- Anthropic / Cloudflare (2025–2026) were right about Code Mode reducing tokens — *on external tool surfaces.* The internal-IDE-tool question they did not test is the one our paper answers, and the answer is: it's regime-dependent.

The arc is not "one trajectory" but a multi-axis design space. Our contribution is a regime-stratified cut through that space.

---

## Drafting notes

- §7.3 is what the workshop reviewers actually want — *what should practitioners do?* Make it concrete (the three numbered prescriptions) and avoid hedging.
- §7.4 is the framing payoff for reviewers who know the prior trajectory. Keep it short — 4 sentences max.
- **Do not extend the discussion to "implications for AGI."** This is a workshop paper about a specific empirical asymmetry. Speculation outside the regime cells we tested is reviewer-2 bait.
