# Codex Call-1 Cache Rate: seed1 vs seed2 (code_only arm)

**Theory:** Codex prompt cache is dynamically allocated, resulting in unpredictable
first-turn cache hits across otherwise identical runs.

| Category | seed1 avg cached | seed1 % | seed2 avg cached | seed2 % | diff |
|----------|-----------------|---------|-----------------|---------|------|
| algorithmic | 4,864 | 47.0% | 0 | 0.0% | -47.0% |
| data_engineering | 7,782 | 70.6% | 2,594 | 23.5% | -47.1% |
| data_processing | 6,080 | 57.4% | 6,080 | 57.4% | +0.0% |
| data_science | 9,114 | 85.9% | 2,594 | 24.5% | -61.5% |
| enumeration | 6,080 | 59.1% | 4,864 | 47.3% | -11.8% |
| iterative_numerical | 8,512 | 82.0% | 4,864 | 46.9% | -35.2% |
| ml_engineering | 7,483 | 71.7% | 5,837 | 55.8% | -15.9% |
| stateful_reasoning | 8,512 | 81.6% | 6,080 | 58.3% | -23.3% |
| verification_heavy | 7,296 | 68.7% | 7,296 | 68.7% | +0.0% |
| **OVERALL** | **7,489** | **70.9%** | **4,289** | **40.6%** | **-30.3%** |

n(seed1)=91, n(seed2)=93 tasks with rollout data.

## Run Conditions

| | seed1 | seed2 |
|-|-------|-------|
| Execution | **serial** | **parallel** |
| Cache contention | none — sole occupant of GPT account | yes — multiple tasks competing simultaneously |

Seed1 ran tasks one at a time with no other runs on the account, so each task's prompt
prefix had uncontested access to cache slots. Seed2 ran tasks in parallel, meaning
multiple concurrent requests from the same account were competing for the same
dynamically allocated cache space.

## Observations

- `data_processing` and `verification_heavy` show **0% difference** — their call-1 prefix
  is identical across seeds, suggesting fully stable cached content for those categories.
- `algorithmic` drops to **0% cached** in seed2 (from 47% in seed1) — complete cache miss.
- `data_science` swings **−61.5 pp**, the largest drop of any category.
- Overall 30 pp drop (70.9% → 40.6%) with no change to the prompt or model.
