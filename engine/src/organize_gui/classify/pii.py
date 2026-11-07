"""Deterministic, best-effort PII and secret scrubber.

Runs on every text before it reaches a model, and again on every model-returned
name or description before it is stored. It is pattern based and cannot catch
everything; the UI says so.
"""

import re
from typing import Callable, List, Optional, Tuple

PLACEHOLDER = "[redacted]"


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def luhn_ok(text: str) -> bool:
    digits = _digits(text)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def iban_ok(text: str) -> bool:
    compact = re.sub(r"\s", "", text).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", compact):
        return False
    rearranged = compact[4:] + compact[:4]
    number = "".join(str(int(char, 36)) for char in rearranged)
    return int(number) % 97 == 1


_CF_ODD = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23]


def codice_fiscale_ok(text: str) -> bool:
    code = text.upper()
    if not re.fullmatch(r"[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]", code):
        return False
    total = 0
    for index, char in enumerate(code[:15]):
        value = int(char) if char.isdigit() else ord(char) - 65
        if char.isdigit() and index % 2 == 0:
            value = _CF_ODD[int(char)]
        elif index % 2 == 0:
            value = _CF_ODD[value]
        total += value
    return chr(65 + total % 26) == code[15]


# (kind, pattern, validator)
PATTERNS: List[Tuple[str, "re.Pattern[str]", Optional[Callable[[str], bool]]]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), None),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"), None),
    ("api-key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}\b"), None),
    ("url-token", re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|key|sig|signature|auth|password|secret)=)[^&\s#]+"), None),
    ("url-credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@"), None),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), None),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), iban_ok),
    ("card", re.compile(r"\b(?:\d[ \-]?){12,18}\d\b"), luhn_ok),
    ("codice-fiscale", re.compile(r"\b[A-Za-z]{6}[0-9LMNPQRSTUVlmnpqrstuv]{2}[A-Za-z][0-9LMNPQRSTUVlmnpqrstuv]{2}[A-Za-z][0-9LMNPQRSTUVlmnpqrstuv]{3}[A-Za-z]\b"), codice_fiscale_ok),
    ("ssn", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), None),
    ("ip", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), None),
    ("ipv6", re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){4,7}[0-9A-Fa-f]{1,4}\b"), None),
    ("coordinates", re.compile(r"[-+]?\d{1,3}\.\d{4,}\s*[,;/ ]\s*[-+]?\d{1,3}\.\d{4,}"), None),
    ("phone", re.compile(r"(?<![\w.])(?:\+|00)\d{1,3}[\s.\-/]?(?:\(?\d{1,4}\)?[\s.\-/]?){2,5}\d{2,4}(?![\w.])"), None),
    ("phone", re.compile(r"(?<![\w.])\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?![\w.])"), None),
    ("phone", re.compile(r"(?<![\w.\-/])3\d{2}[\s.]?\d{3}[\s.]?\d{3,4}(?![\w.\-/])"), None),
]


def find(text: str) -> List[str]:
    """Kinds of PII/secrets found in text (validated where a checksum exists)."""
    kinds = []
    for kind, pattern, validator in PATTERNS:
        for match in pattern.finditer(text or ""):
            if validator is None or validator(match.group(0)):
                kinds.append(kind)
                break
    return kinds


def scrub(text: str) -> str:
    """Replace every detected item with a neutral placeholder."""
    if not text:
        return ""
    result = text
    for kind, pattern, validator in PATTERNS:
        def replace(match: "re.Match[str]") -> str:
            value = match.group(0)
            if validator is not None and not validator(value):
                return value
            if kind == "url-token":
                return match.group(1) + PLACEHOLDER
            if kind == "url-credentials":
                return value.split("://", 1)[0] + "://" + PLACEHOLDER + "@"
            return PLACEHOLDER
        result = pattern.sub(replace, result)
    return result


def contains_pii(text: str) -> bool:
    return bool(find(text))
