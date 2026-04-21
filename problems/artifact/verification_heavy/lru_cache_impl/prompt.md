# Task: Implement LRU Cache

Implement a **Least-Recently-Used (LRU) cache** data structure in Python.

## Interface

```python
class LRUCache:
    def __init__(self, capacity: int) -> None:
        """Initialize with a positive integer capacity."""
        ...

    def get(self, key: int) -> int:
        """Return the value for key, or -1 if not present.
        Accessing an existing key marks it as most recently used.
        """
        ...

    def put(self, key: int, value: int) -> None:
        """Insert or update key/value.
        If the cache is at capacity and key is new, evict the least recently used entry first.
        Updating an existing key marks it as most recently used.
        """
        ...
```

## Semantics

- Keys and values are integers.
- `get(key)` returns `-1` if the key is not in the cache.
- Both `get` and `put` count as "uses" — they update the recency of the key.
- When capacity is exceeded on `put`, the **least recently used** key is evicted.
- `put` on an existing key updates its value **and** its recency (no eviction needed).

## Example

```python
cache = LRUCache(2)
cache.put(1, 1)   # cache: {1:1}
cache.put(2, 2)   # cache: {1:1, 2:2}
cache.get(1)      # returns 1; cache: {2:2, 1:1}  (1 is now MRU)
cache.put(3, 3)   # evicts 2 (LRU); cache: {1:1, 3:3}
cache.get(2)      # returns -1 (evicted)
```

## Output

Write your implementation to `output/lru_cache.py`.

The file must define a class `LRUCache` with the interface above.

All `get` and `put` operations must run in **O(1)** time. Standard Python's `collections.OrderedDict` or a doubly-linked list + hash map are both acceptable implementations.

## Verification

Run `python verify.py` to check that `output/lru_cache.py` imports and exports `LRUCache`. The hidden test suite will run 30 property tests against your implementation.
