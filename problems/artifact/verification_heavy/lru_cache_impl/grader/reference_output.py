"""Reference implementation of LRUCache for verification_heavy__lru_cache_impl."""

from collections import OrderedDict


class LRUCache:
    """Least-Recently-Used cache with O(1) get and put.

    get(key) -> value or -1 if not present.
    put(key, value) -> None. Evicts LRU entry when capacity is exceeded.
    Both get and put update recency (most recently used).
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        self.capacity = capacity
        self._cache: OrderedDict = OrderedDict()

    def get(self, key: int) -> int:
        if key not in self._cache:
            return -1
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: int, value: int) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = value
        else:
            if len(self._cache) >= self.capacity:
                self._cache.popitem(last=False)  # evict LRU (first item)
            self._cache[key] = value
