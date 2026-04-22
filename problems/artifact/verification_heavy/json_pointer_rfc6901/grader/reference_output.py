"""Reference resolve / set_at (RFC 6901 JSON Pointer) for verification_heavy__json_pointer_rfc6901."""


def _unescape(token: str) -> str:
    # Decode ~1 before ~0 (RFC 6901 §4).
    return token.replace("~1", "/").replace("~0", "~")


def _split(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer (must be empty or start with '/'): {pointer!r}")
    # Split on '/' after the leading one. Each piece is a reference token.
    return [_unescape(tok) for tok in pointer[1:].split("/")]


def _as_array_index(token: str, length: int, *, allow_dash: bool) -> int:
    if token == "-":
        if not allow_dash:
            raise KeyError(f"'-' index not valid here")
        return length
    if token == "":
        raise KeyError(f"empty array index")
    if token != "0" and (not token.isdigit() or token[0] == "0"):
        raise KeyError(f"invalid array index {token!r}")
    if not token.isdigit():
        raise KeyError(f"invalid array index {token!r}")
    idx = int(token)
    return idx


def resolve(doc, pointer: str):
    tokens = _split(pointer)
    cur = doc
    for tok in tokens:
        if isinstance(cur, dict):
            if tok not in cur:
                raise KeyError(f"key {tok!r} not in dict")
            cur = cur[tok]
        elif isinstance(cur, list):
            idx = _as_array_index(tok, len(cur), allow_dash=False)
            if idx < 0 or idx >= len(cur):
                raise KeyError(f"array index {idx} out of range (len={len(cur)})")
            cur = cur[idx]
        else:
            raise KeyError(f"cannot traverse into {type(cur).__name__} with token {tok!r}")
    return cur


def set_at(doc, pointer: str, value) -> None:
    tokens = _split(pointer)
    if not tokens:
        raise ValueError("cannot set at root pointer")

    *parents, last = tokens
    cur = doc
    for tok in parents:
        if isinstance(cur, dict):
            if tok not in cur:
                raise KeyError(f"parent key {tok!r} not in dict")
            cur = cur[tok]
        elif isinstance(cur, list):
            idx = _as_array_index(tok, len(cur), allow_dash=False)
            if idx < 0 or idx >= len(cur):
                raise KeyError(f"parent array index {idx} out of range (len={len(cur)})")
            cur = cur[idx]
        else:
            raise KeyError(f"cannot traverse into {type(cur).__name__}")

    if isinstance(cur, dict):
        cur[last] = value
    elif isinstance(cur, list):
        idx = _as_array_index(last, len(cur), allow_dash=True)
        if idx == len(cur):
            cur.append(value)
        elif 0 <= idx < len(cur):
            cur[idx] = value
        else:
            raise KeyError(f"array index {idx} out of range (len={len(cur)})")
    else:
        raise KeyError(f"target parent is not a container: {type(cur).__name__}")
