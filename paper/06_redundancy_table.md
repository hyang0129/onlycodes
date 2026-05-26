# 06 — IDE Tool ↔ Bash Redundancy

**Target length:** 0.5 page total (text + Table 1); ceiling 0.75.

**Status:** static content; can be written immediately. Does not depend on numbers freeze.

---

## Lead paragraph

*"Five of six IDE primitives in Claude Code are bash subsets in capability (Table 1). The sign-flip in §5 shows that even subset-capability tools nevertheless earn their token budget on the modification regime — by saving exploration turns, not by adding capability."*

## Table 1 — IDE primitive ↔ bash redundancy

| Claude Code primitive | Bash equivalent | Capability beyond bash? |
|---|---|---|
| `Read` | `cat`, `head`, `tail`, `sed -n` | Bounded output, line numbering — UX, not capability |
| `Grep` | `grep -rn`, `rg` | None |
| `Glob` | `find`, `ls **/` | None |
| `Edit` | `sed -i`, `patch`, heredoc redirect | **Yes — atomic byte-precise replace with lint** |
| `Write` | `cat > file <<EOF` | None |
| `Bash` | (itself) | — |

## Trailing paragraph

*"The Capability Overlap Principle (Zhang et al., 2026) predicts that tools with high capability-overlap with the existing action surface (here: bash) impose tax without gain. Of the six primitives, only `Edit` provides non-overlapping capability — the structured patch-and-lint flow `sed -i` cannot match. On the computation regime, where no instance requires `Edit` (the agent writes one self-contained script per task), the tax dominates and `code_only` wins. On the modification regime, where every instance requires multi-file structured edits, `Edit`'s unique capability anchors the IDE surface's cost advantage."*

---

## Drafting notes

- This is the **pedagogical anchor** of the paper. It can be written today — no numbers required.
- The "Yes — atomic byte-precise replace with lint" line for `Edit` is load-bearing. Defend it in §6's text by noting that the structured-edit flow guards against (a) whitespace drift from heredoc, (b) lint failures from `sed -i` regex mistakes, and (c) the no-such-target failure mode of `patch`. These are real Edit-tool implementation details the maintainers cite.
- If a reviewer asks "but isn't `Edit` just sugar over `patch`?" the response is: no, because Edit's contract is *byte-exact replace OR fail*, whereas `patch` succeeds on partial application. The behavior diverges on real codebases.
- **Do not claim** that `Edit` is unique to Claude Code — Cursor and Aider have analogous tools. The claim is about the IDE-tool *category*, not the specific implementation.
