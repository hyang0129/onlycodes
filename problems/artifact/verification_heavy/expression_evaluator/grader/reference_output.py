"""Reference evaluate() — recursive descent arithmetic parser.

Grammar:
    expr   := term (('+'|'-') term)*
    term   := factor (('*'|'/') factor)*
    factor := ('-' factor) | '(' expr ')' | NUMBER
"""

import re


_TOK = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([+\-*/()]))")


def _tokenize(s: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m or m.end() == pos:
            # Check if the remainder is only whitespace
            if s[pos:].strip() == "":
                break
            raise ValueError(f"unexpected character at position {pos}: {s[pos]!r}")
        if m.group(1) is not None:
            tokens.append(("NUM", m.group(1)))
        else:
            tokens.append(("OP", m.group(2)))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _eat(self) -> tuple[str, str]:
        if self.i >= len(self.tokens):
            raise ValueError("unexpected end of expression")
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse_expr(self) -> float:
        left = self.parse_term()
        while True:
            tok = self._peek()
            if tok is None or tok[0] != "OP" or tok[1] not in "+-":
                break
            self._eat()
            right = self.parse_term()
            left = left + right if tok[1] == "+" else left - right
        return left

    def parse_term(self) -> float:
        left = self.parse_factor()
        while True:
            tok = self._peek()
            if tok is None or tok[0] != "OP" or tok[1] not in "*/":
                break
            self._eat()
            right = self.parse_factor()
            if tok[1] == "*":
                left = left * right
            else:
                if right == 0:
                    raise ZeroDivisionError("division by zero")
                left = left / right
        return left

    def parse_factor(self) -> float:
        tok = self._peek()
        if tok is None:
            raise ValueError("unexpected end of expression")
        if tok[0] == "OP" and tok[1] == "-":
            self._eat()
            return -self.parse_factor()
        if tok[0] == "OP" and tok[1] == "(":
            self._eat()
            val = self.parse_expr()
            close = self._peek()
            if close is None or close != ("OP", ")"):
                raise ValueError("missing ')'")
            self._eat()
            return val
        if tok[0] == "NUM":
            self._eat()
            return float(tok[1])
        raise ValueError(f"unexpected token {tok!r}")


def evaluate(expr: str) -> float:
    tokens = _tokenize(expr)
    if not tokens:
        raise ValueError("empty expression")
    p = _Parser(tokens)
    result = p.parse_expr()
    if p.i != len(tokens):
        raise ValueError(f"trailing tokens at position {p.i}")
    return float(result)
