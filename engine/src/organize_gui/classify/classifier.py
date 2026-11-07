"""Assigning files to accepted categories, and the shared signal/embedding helpers.

Order used by the planner: extension rules -> metadata rules -> (analysis assignment or
cache) -> content rules by nearest centroid. A content match needs similarity >= the
category threshold and a gap >= 0.05 to the second-best centroid, otherwise the file is
'unknown' and goes to Other (or stays in place).
"""

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..presets import CATEGORIES
from ..profiles import valid_match  # noqa: F401  (re-exported for callers)
from . import EMBED_DIMS, SIGNAL_VERSION, pii, vectors
from .backend import BackendUnavailable, OllamaServer
from .extract import content_digest, extract_text
from .naming import tokens

UNKNOWN = "unknown"
MIN_GAP = 0.05
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}
SCAN_NAME = re.compile(r"^(scan|scanned|scansione|camscanner|img_scan)", re.IGNORECASE)

SessionFactory = Callable[[], Tuple[Any, Any]]


def family(extension: str) -> str:
    extension = extension.casefold().lstrip(".")
    for key, category in CATEGORIES.items():
        if extension in category["extensions"]:
            return key
    return "other"


def validated_category(value: Any, allowed: Iterable[str]) -> str:
    """Model or stored output must name a known category, otherwise it is 'unknown'."""
    return value if isinstance(value, str) and value in set(allowed) else UNKNOWN


def default_session() -> Tuple[Any, Any]:
    server = OllamaServer()
    return server.start(), server


class ModelSession:
    """Starts the loopback model server on first use and always stops it afterwards."""

    def __init__(self, factory: Optional[SessionFactory]) -> None:
        self.factory = factory or default_session
        self.backend: Any = None
        self.server: Any = None
        self.error: Optional[str] = None

    def get(self) -> Any:
        if self.backend is None and self.error is None:
            try:
                self.backend, self.server = self.factory()
            except (BackendUnavailable, OSError) as exc:
                self.error = str(exc) or "unavailable"
        if self.backend is None:
            raise BackendUnavailable(self.error or "unavailable")
        return self.backend

    def close(self) -> None:
        server, self.server = self.server, None
        self.backend = None
        if server is not None:
            server.stop()

    def __enter__(self) -> "ModelSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def meta_summary(meta: Optional[Dict[str, Any]]) -> str:
    if not meta:
        return ""
    parts = []
    if meta.get("isScreenshot"):
        parts.append("screenshot")
    if meta.get("camera"):
        parts.append("camera photo")
    if meta.get("width") and meta.get("height"):
        parts.append("%dx%d" % (meta["width"], meta["height"]))
    if meta.get("dateSource") == "taken" and meta.get("dateTaken"):
        parts.append("taken %s" % meta["dateTaken"][:7])
    return " ".join(parts)


def build_signal(path: Path, meta: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> str:
    """Name + extension + parent folder + metadata summary + extracted text, scrubbed. Memory only."""
    extension = path.suffix.lower().lstrip(".")
    words = " ".join(tokens(path.name))
    parent = " ".join(tokens(path.parent.name))
    body = extract_text(path) if text is None else text
    signal = "file: %s | type: %s %s | folder: %s" % (words, extension, family(extension), parent)
    summary = meta_summary(meta)
    if summary:
        signal += " | " + summary
    if body:
        signal += " | text: " + body
    return pii.scrub(signal)


def signal_key(path: Path) -> str:
    """Cache key: capped content digest plus the name inputs of the signal."""
    import hashlib

    digest = hashlib.sha256()
    digest.update(content_digest(path).encode())
    digest.update(("\x00%s\x00%s\x00%d" % (path.name, path.parent.name, SIGNAL_VERSION)).encode())
    return digest.hexdigest()


def embed_signals(store: Any, session: ModelSession, model: str, items: Sequence[Tuple[str, str]],
                  progress: Optional[Callable[[int, int], None]] = None,
                  cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, List[float]]:
    """{key: unit vector of EMBED_DIMS}. Cached vectors are reused; new ones are cached."""
    from ..errors import Cancelled

    keys = list(dict.fromkeys(key for key, _ in items))
    cached = store.cached_vectors(keys, model, SIGNAL_VERSION)
    result = {key: vectors.from_blob(blob) for key, blob in cached.items()}
    missing = [(key, text) for key, text in dict(items).items() if key not in result]
    if progress:
        progress(len(result), len(keys))
    if missing:
        backend = session.get()
        now = datetime.now(timezone.utc).isoformat()
        for start in range(0, len(missing), 32):
            if cancelled and cancelled():
                raise Cancelled()
            chunk = missing[start:start + 32]
            last = start + 32 >= len(missing)
            raw = backend.embed(model, ["clustering: " + text for _, text in chunk], unload=last)
            rows = []
            for (key, _), vector in zip(chunk, raw):
                truncated = vectors.matryoshka(vector, EMBED_DIMS)
                result[key] = truncated
                rows.append((key, vectors.to_blob(truncated)))
            store.cache_vectors(rows, model, SIGNAL_VERSION, now)
            if progress:
                progress(len(result), len(keys))
    return result


def membership_confidence(similarity: float) -> str:
    if similarity >= 0.80:
        return "high"
    if similarity >= 0.65:
        return "medium"
    return "low"


def match_confidence(similarity: float, gap: float, threshold: float) -> Optional[str]:
    if similarity < threshold or gap < MIN_GAP:
        return None
    return "high" if similarity >= threshold + 0.1 and gap >= 0.1 else "medium"


def _date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def metadata_matches(match: Dict[str, Any], meta: Dict[str, Any], name: str) -> bool:
    if "anyOf" in match:
        return any(metadata_matches(option, meta, name) for option in match.get("anyOf") or [] if isinstance(option, dict))
    if "isScreenshot" in match and bool(meta.get("isScreenshot")) != bool(match["isScreenshot"]):
        return False
    if "hasCamera" in match and bool(meta.get("camera")) != bool(match["hasCamera"]):
        return False
    if "isScan" in match and bool(SCAN_NAME.match(name)) != bool(match["isScan"]):
        return False
    if "minPixels" in match:
        pixels = (meta.get("width") or 0) * (meta.get("height") or 0)
        if pixels < int(match["minPixels"]):
            return False
    if "dateTakenRange" in match:
        start, end = (_date(value) for value in (match["dateTakenRange"] + [None, None])[:2])
        taken = _date(meta.get("dateTaken")) if meta.get("dateSource") == "taken" else None
        if taken is None or (start and taken < start) or (end and taken > end):
            return False
    return True


class ContentClassifier:
    """Nearest-centroid assignment for files no extension/metadata rule claimed."""

    def __init__(self, store: Any, rules: List[Dict[str, Any]], model: str, enabled: bool,
                 session_factory: Optional[SessionFactory] = None) -> None:
        self.store = store
        self.model = model
        self.enabled = enabled
        self.session_factory = session_factory
        models = store.category_models([rule["centroidRef"] for rule in rules if rule.get("centroidRef")])
        self.rules = []
        for rule in rules:
            stored = models.get(rule.get("centroidRef"))
            if stored and stored["embed_model"] == model and stored["signal_version"] == SIGNAL_VERSION:
                self.rules.append((rule, vectors.from_blob(stored["centroid"]), float(stored["threshold"])))

    def classify(self, paths: Sequence[Path], metas: Dict[Path, Dict[str, Any]],
                 cancelled: Optional[Callable[[], bool]] = None) -> Tuple[Dict[Path, Tuple[Dict[str, Any], str, float]], Optional[str]]:
        """({path: (rule, confidence, similarity)}, notice). Unmatched paths are absent."""
        if not paths or not self.rules:
            return {}, None
        if not self.enabled:
            return {}, "AI_DISABLED"
        keys = {path: signal_key(path) for path in paths}
        notice = None
        with ModelSession(self.session_factory) as session:
            items = [(keys[path], build_signal(path, metas.get(path))) for path in paths]
            try:
                found = embed_signals(self.store, session, self.model, items, cancelled=cancelled)
            except BackendUnavailable:
                cached = self.store.cached_vectors(list(keys.values()), self.model, SIGNAL_VERSION)
                found = {key: vectors.from_blob(blob) for key, blob in cached.items()}
                notice = "AI_UNAVAILABLE"
        centres = [centre for _, centre, _ in self.rules]
        result = {}
        for path in paths:
            vector = found.get(keys[path])
            if not vector:
                continue
            index, similarity, gap = vectors.nearest(vector, centres)
            rule, _, threshold = self.rules[index]
            confidence = match_confidence(similarity, gap, threshold)
            if confidence:
                result[path] = (rule, confidence, similarity)
        return result, notice
