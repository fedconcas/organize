"""Sanitize every category name, folder name and description before it is shown or stored."""

import re
import unicodedata
from typing import Iterable, List, Optional, Set

from ..profiles import valid_folder_name
from . import pii

MAX_NAME = 24
MAX_FOLDER = 32
MAX_DESCRIPTION_WORDS = 5
RESERVED = {
    "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9", "unknown",
}
_ALLOWED = re.compile(r"[^\w \-&]", re.UNICODE)


def _clean(value: object, limit: int) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    if pii.contains_pii(text):
        # Check the raw value: cleaning would strip the characters that make PII recognizable.
        return ""
    text = _ALLOWED.sub(" ", text).replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" -&")
    if not text:
        return ""
    words = [word if word.isupper() and len(word) <= 4 else word[:1].upper() + word[1:].lower() for word in text.split(" ")]
    text = " ".join(words)
    return text[:limit].rstrip(" -&")


def copies_sample(value: str, samples: Iterable[str], words: int = 3) -> bool:
    """True when value repeats more than `words` consecutive words of one sample verbatim."""
    tokens = re.findall(r"\w+", value.casefold())
    if len(tokens) <= words:
        return False
    for sample in samples:
        haystack = " " + " ".join(re.findall(r"\w+", (sample or "").casefold())) + " "
        for start in range(len(tokens) - words):
            if " " + " ".join(tokens[start:start + words + 1]) + " " in haystack:
                return True
    return False


def acceptable(value: str, samples: Iterable[str] = ()) -> bool:
    return bool(value) and not pii.contains_pii(value) and not copies_sample(value, list(samples))


def unique(value: str, taken: Set[str]) -> str:
    base = value
    index = 2
    while value.casefold() in taken or value.casefold() in RESERVED:
        suffix = " %d" % index
        value = base[: MAX_FOLDER - len(suffix)].rstrip() + suffix
        index += 1
    taken.add(value.casefold())
    return value


def category_name(value: object, fallback: str, samples: Iterable[str] = ()) -> str:
    samples = list(samples)
    full = _clean(value, 200)
    name = full[:MAX_NAME].rstrip(" -&")
    if not acceptable(name, samples) or not acceptable(full, samples):
        name = _clean(fallback, MAX_NAME)
    return name or "Group"


def folder_name(value: object, fallback: str, taken: Set[str], samples: Iterable[str] = (), index: int = 1) -> str:
    samples = list(samples)
    full = _clean(value, 200)
    folder = full[:MAX_FOLDER].rstrip(" -&")
    if not acceptable(folder, samples) or not acceptable(full, samples) or not valid_folder_name(folder):
        folder = _clean(fallback, MAX_FOLDER)
    if not folder or not valid_folder_name(folder):
        folder = "Group %d" % index
    return unique(folder, taken)


def description(value: object, samples: Iterable[str] = ()) -> Optional[str]:
    text = _clean(value, 60)
    words = text.split(" ")[:MAX_DESCRIPTION_WORDS]
    text = " ".join(words).strip()
    if not text or not acceptable(text, samples):
        return None
    return text[:1].upper() + text[1:].lower()


def tokens(name: str) -> List[str]:
    """Split a file name into lower-case words (camelCase, separators, digits)."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", name)
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)
    return [part.lower() for part in re.split(r"[\W_]+|(?<=\D)(?=\d)|(?<=\d)(?=\D)", stem) if part]
