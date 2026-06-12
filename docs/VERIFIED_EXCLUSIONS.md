# Verified-buildable exclusions (verbatim grading, #354)

`sets/verified-buildable.txt` = the SWE-bench Verified instances whose **gold patch
resolves** under official `swebench.harness.run_evaluation` (swebench==4.1.0) on the
unmodified prebuilt image. **494 of 500.** This file records the 6 non-resolvers and
the 3 flaky-but-kept, with evidence that the failures are **benchmark/harness
environment drift — not our harness, and not defects in the gold code**.

Each gold patch was graded **3× on a quiet host** (`grade_one`, verbatim). Raw logs
were captured under `/tmp/inv/` during the #354 investigation.

## Excluded (6) — gold does NOT resolve under swebench-4.1.0

### Group 1 — env/dependency drift, documented by SWE-bench itself (4)

These are on SWE-bench's own ["5 Instances in Verified Fail for Gold Patch" (issue #267)](https://github.com/SWE-bench/SWE-bench/issues/267)
and detailed in [issue #484](https://github.com/SWE-bench/SWE-bench/issues/484). Our
independent root-cause analysis matched the maintainers' line-for-line.

| instance | cause (ours == maintainers') |
|---|---|
| `astropy__astropy-7606` | test-id drift: expected `[]` vs versioned `[unit0]` param ids; test passes |
| `astropy__astropy-8707` | `PytestRemovedIn8Warning: Support for nose tests is deprecated` (nose `setup(self)`) + NumPy ≥1.24 type-alias removal |
| `astropy__astropy-8872` | `DeprecationWarning: distutils Version classes are deprecated` (`LooseVersion`) → collection error, 0 collected |
| `django__django-10097` | subset test-isolation: admin templates unconfigured when only the curated F2P+P2P subset runs → `TemplateDoesNotExist: admin/change_form.html` |

> The 5th instance on issue #267, `matplotlib__matplotlib-20488`, **does resolve** under
> 4.1.0 (fixed since the issue was filed) — it is in the buildable set. This confirms
> the failing set is **version-dependent**.

### Group 2 — swebench-4.1.0 parser drift, NOT on any official list (2)

| instance | cause |
|---|---|
| `sphinx-doc__sphinx-8595` | single-node `-rA` run emits no `PASSED ::…` summary line → parser counts 0 tests; the test **actually passes** (`1 passed`) |
| `sphinx-doc__sphinx-9711` | same parser interaction; test passes but is scored unresolved |

These are **not** in SWE-bench issues #267/#484. They consistently fail under our
verbatim 4.1.0 grading (0/3) but the gold code is correct — likely a 4.1.0
single-node test-selection/parser interaction. Candidate to revisit or file upstream;
excluded for now because they do not resolve under the harness we grade with.

## Flaky-but-KEPT (3) — resolve intermittently; grade with retry

| instance | evidence |
|---|---|
| `psf__requests-1921` | resolved **3/3** on a quiet host; surfaced only under `--parallel 6` load. SWE-bench [#484] documents requests tests as httpbin.org-dependent (intermittent 503). |
| `django__django-13089` | flaky timing cache tests (`test_touch`/`test_expiration`); a *different* subset regresses each run; F2P always pass. |
| `django__django-13344` | same flaky cache-timing signature. |

Recommendation: grade with retry-on-not-resolved (the original gold-gate had 3×; the
verbatim path should too). A loaded host can dip any of these — the single-pass count
is a **floor**.

## External corroboration (published)

This class of false negative is documented and quantified in the literature:
- **SWE-Bench+** ([arXiv:2410.06992](https://arxiv.org/pdf/2410.06992)) — quality audit of SWE-bench.
- **SWE-ABS** ([arXiv:2603.00520](https://arxiv.org/html/2603.00520v1)) — ~**10.6% false-negative rate** attributed to test issues.
- **SWE-Bench Pro** ([arXiv:2509.16941](https://arxiv.org/pdf/2509.16941)) and **SWE-Bench++** ([arXiv:2512.17419](https://arxiv.org/html/2512.17419v1)) — both run gold tests **3×** and drop flaky/non-resolving instances by construction.
- **Cross-Context Verification** ([arXiv:2603.21454](https://arxiv.org/html/2603.21454)) — notes gold patches failing in Verified + flaky tests.

## Bottom line

Verbatim grading reproduces the **known** SWE-bench gold-fail set (version-adjusted),
not new breakage of ours. 494 buildable; 4 excluded match SWE-bench's own documented
gold-failures; 2 sphinx are a 4.1.0 parser artifact (gold correct); 3 flaky are kept
with retry. Supersedes the strip+reinstall framing in `docs/GOLD_GATE_DRIFT.md`.
