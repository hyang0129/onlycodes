# Oracle: reference changes to HTTPAdapter in src/requests/adapters.py
# Task: Add a default_timeout parameter to HTTPAdapter.__init__() that is
# stored as self.default_timeout. In send(), if timeout is None, fall back
# to self.default_timeout.

# Key change 1: __init__ signature gains default_timeout=None
def __init__(
    self,
    pool_connections=DEFAULT_POOLSIZE,
    pool_maxsize=DEFAULT_POOLSIZE,
    max_retries=DEFAULT_RETRIES,
    pool_block=DEFAULT_POOLBLOCK,
    default_timeout=None,      # <-- added
):
    # ... existing body ...
    self.default_timeout = default_timeout   # <-- added

# Key change 2: send() falls back to self.default_timeout when timeout is None
def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
    if timeout is None:
        timeout = self.default_timeout   # <-- added fallback
    # ... rest of existing body unchanged ...
