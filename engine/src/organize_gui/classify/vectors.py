"""Small, numpy-free vector math for unit-length embeddings.

Similarity matrices use Apple's Accelerate ``cblas_sgemm`` through ctypes when it is
available (macOS ships it; nothing is bundled), else a pure-Python fallback
(``math.sumprod`` on Python 3.12+). Clustering is deterministic k-means++ written here.
"""

import array
import ctypes
import math
import os
import random
import sys
from typing import List, Optional, Sequence, Tuple

Vector = List[float]
ACCELERATE = "/System/Library/Frameworks/Accelerate.framework/Accelerate"

_sgemm = None
if sys.platform == "darwin" and not os.environ.get("ORGANIZE_GUI_PURE_VECTORS"):
    try:
        _sgemm = ctypes.CDLL(ACCELERATE).cblas_sgemm
        _sgemm.restype = None
    except (OSError, AttributeError):
        _sgemm = None

_FP = ctypes.POINTER(ctypes.c_float)
_sumprod = getattr(math, "sumprod", None)


def backend_name() -> str:
    return "accelerate" if _sgemm is not None else "python"


def dot(left: Sequence[float], right: Sequence[float]) -> float:
    if _sumprod is not None:
        return _sumprod(left, right)
    return sum(x * y for x, y in zip(left, right))


def normalize(vector: Sequence[float]) -> Vector:
    norm = math.sqrt(dot(vector, vector))
    if not norm:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def matryoshka(vector: Sequence[float], dims: int) -> Vector:
    """nomic-embed-text v1.5 truncation: layer-norm the full vector, keep the first dims, re-normalize."""
    count = len(vector)
    if not count:
        return []
    mean = sum(vector) / count
    variance = sum((value - mean) ** 2 for value in vector) / count
    scale = 1.0 / math.sqrt(variance + 1e-5)
    return normalize([(value - mean) * scale for value in vector[:dims]])


def mean(vectors: Sequence[Sequence[float]]) -> Vector:
    if not vectors:
        return []
    total = [0.0] * len(vectors[0])
    for vector in vectors:
        for index, value in enumerate(vector):
            total[index] += value
    return normalize(total)


def to_blob(vector: Sequence[float]) -> bytes:
    return array.array("f", vector).tobytes()


def from_blob(blob: bytes) -> Vector:
    values = array.array("f")
    values.frombytes(blob)
    return values.tolist()


class Matrix:
    """Row-major float32 matrix of unit vectors, with a similarity product against other rows."""

    def __init__(self, rows: Sequence[Sequence[float]]) -> None:
        self.rows = [list(row) for row in rows]
        self.count = len(self.rows)
        self.dims = len(self.rows[0]) if self.rows else 0
        self._flat = array.array("f", [value for row in self.rows for value in row]) if _sgemm else None

    def similarities(self, others: Sequence[Sequence[float]]) -> List[List[float]]:
        """count x len(others) cosine similarities (rows are unit vectors)."""
        k = len(others)
        if not self.count or not k:
            return [[] for _ in range(self.count)]
        if _sgemm is None or self._flat is None:
            return [[dot(row, other) for other in others] for row in self.rows]
        centres = array.array("f", [value for row in others for value in row])
        output = array.array("f", bytes(4 * self.count * k))
        _sgemm(
            101, 111, 112, self.count, k, self.dims, ctypes.c_float(1.0),
            ctypes.cast((ctypes.c_float * len(self._flat)).from_buffer(self._flat), _FP), self.dims,
            ctypes.cast((ctypes.c_float * len(centres)).from_buffer(centres), _FP), self.dims,
            ctypes.c_float(0.0),
            ctypes.cast((ctypes.c_float * len(output)).from_buffer(output), _FP), k,
        )
        view = memoryview(output)
        return [view[index * k:(index + 1) * k].tolist() for index in range(self.count)]

    def centroids(self, assignment: Sequence[int], k: int) -> List[Vector]:
        if _sgemm is None or self._flat is None:
            totals = [[0.0] * self.dims for _ in range(k)]
            for row, cluster in zip(self.rows, assignment):
                target = totals[cluster]
                for index, value in enumerate(row):
                    target[index] += value
            return [normalize(total) for total in totals]
        onehot = array.array("f", bytes(4 * self.count * k))
        for index, cluster in enumerate(assignment):
            onehot[index * k + cluster] = 1.0
        output = array.array("f", bytes(4 * k * self.dims))
        _sgemm(
            101, 112, 111, k, self.dims, self.count, ctypes.c_float(1.0),
            ctypes.cast((ctypes.c_float * len(onehot)).from_buffer(onehot), _FP), k,
            ctypes.cast((ctypes.c_float * len(self._flat)).from_buffer(self._flat), _FP), self.dims,
            ctypes.c_float(0.0),
            ctypes.cast((ctypes.c_float * len(output)).from_buffer(output), _FP), self.dims,
        )
        view = memoryview(output)
        return [normalize(view[index * self.dims:(index + 1) * self.dims].tolist()) for index in range(k)]


def kmeans(matrix: Matrix, k: int, seed: int = 42, iterations: int = 25) -> Tuple[List[int], List[Vector], List[List[float]]]:
    """Deterministic spherical k-means with k-means++ seeding. Returns (assignment, centres, similarities)."""
    count = matrix.count
    k = max(1, min(k, count))
    rng = random.Random(seed)
    centres = [matrix.rows[rng.randrange(count)]]
    distance = [max(0.0, 1.0 - row[0]) for row in matrix.similarities(centres)]
    while len(centres) < k:
        total = sum(value * value for value in distance)
        if total <= 0:
            break
        pick = rng.random() * total
        running = 0.0
        chosen = count - 1
        for index, value in enumerate(distance):
            running += value * value
            if running >= pick:
                chosen = index
                break
        centres.append(matrix.rows[chosen])
        latest = matrix.similarities([matrix.rows[chosen]])
        distance = [min(old, max(0.0, 1.0 - row[0])) for old, row in zip(distance, latest)]
    k = len(centres)
    assignment: Optional[List[int]] = None
    sims = matrix.similarities(centres)
    for _ in range(iterations):
        new = [max(range(k), key=row.__getitem__) for row in sims]
        if new == assignment:
            break
        assignment = new
        updated = matrix.centroids(assignment, k)
        centres = [centre if any(centre) else centres[index] for index, centre in enumerate(updated)]
        sims = matrix.similarities(centres)
    if assignment is None:
        assignment = [max(range(k), key=row.__getitem__) for row in sims]
    return assignment, centres, sims


def simplified_silhouette(assignment: Sequence[int], sims: Sequence[Sequence[float]]) -> float:
    """Mean of (b - a) / max(a, b) with a/b = cosine distance to own / nearest other centre."""
    if not assignment or len(sims[0]) < 2:
        return -1.0
    total = 0.0
    for cluster, row in zip(assignment, sims):
        own = 1.0 - row[cluster]
        other = min(1.0 - value for index, value in enumerate(row) if index != cluster)
        total += (other - own) / max(own, other, 1e-9)
    return total / len(assignment)


def nearest(vector: Sequence[float], centres: Sequence[Sequence[float]]) -> Tuple[int, float, float]:
    """(index, best similarity, gap to second best)."""
    scores = [dot(vector, centre) for centre in centres]
    if not scores:
        return -1, 0.0, 0.0
    order = sorted(range(len(scores)), key=lambda index: -scores[index])
    best = scores[order[0]]
    second = scores[order[1]] if len(order) > 1 else -1.0
    return order[0], best, best - second
