# Event Ledger: Bank Transaction Replay

You are given two files in the current working directory:

- **`transactions.jsonl`** — 1000 bank transactions in chronological order, one JSON object per line
- **`initial_balances.json`** — starting balances for all 30 accounts (ACC01 through ACC30)

## Transaction Types

Each transaction has one of three types:

**Deposit** — always succeeds, adds amount to the account balance:
```json
{"txn_id": "T0001", "type": "deposit", "account": "ACC01", "amount": 150.00}
```

**Withdrawal** — succeeds only if the account has sufficient funds:
```json
{"txn_id": "T0002", "type": "withdrawal", "account": "ACC01", "amount": 50.00}
```

**Transfer** — moves funds from one account to another, succeeds only if the source account has sufficient funds:
```json
{"txn_id": "T0003", "type": "transfer", "from": "ACC01", "to": "ACC02", "amount": 75.00}
```

## Rejection Rules

A transaction is **rejected** if processing it would cause any account balance to go negative:

- A `withdrawal` is rejected if `balance[account] - amount < 0`
- A `transfer` is rejected if `balance[from_account] - amount < 0`
- `deposit` transactions are **never** rejected

**Rejected transactions do not change any balances.** Processing continues with the next transaction.

## Task

Process all 1000 transactions in order, starting from the initial balances. Then write your results to `output/result.json`.

## Output Format

Create the directory `output/` and write `output/result.json` with the following schema:

```json
{
  "balances": {
    "ACC01": 1234.56,
    "ACC02": 789.10,
    "...": "..."
  },
  "rejected": ["T0042", "T0183", "..."]
}
```

Requirements:
- `balances`: a JSON object mapping each account ID to its final balance (a number). All 30 accounts (ACC01 through ACC30) must appear.
- `rejected`: a JSON array of transaction IDs that were rejected, in chronological order (the order they were encountered while processing).

## Example

Given initial balance `ACC01: 100.00` and these transactions:
1. `{"txn_id": "T0001", "type": "withdrawal", "account": "ACC01", "amount": 80.00}` → succeeds, ACC01 = 20.00
2. `{"txn_id": "T0002", "type": "withdrawal", "account": "ACC01", "amount": 50.00}` → **rejected** (20.00 - 50.00 < 0), ACC01 stays 20.00
3. `{"txn_id": "T0003", "type": "deposit", "account": "ACC01", "amount": 200.00}` → succeeds, ACC01 = 220.00

Result: `{"balances": {"ACC01": 220.00, ...}, "rejected": ["T0002"]}`
