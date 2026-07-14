"""Mergeable latency histograms for API monitoring."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional


LATENCY_BUCKET_BOUNDS_MS = (
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    30000,
    60000,
)
OVERFLOW_BUCKET = "overflow"


def record_latency(histogram: Dict[str, int], latency_ms: int) -> None:
    """Record one request in the first bucket whose upper bound contains it."""
    value = max(0, int(latency_ms))
    bucket = OVERFLOW_BUCKET
    for upper_bound in LATENCY_BUCKET_BOUNDS_MS:
        if value <= upper_bound:
            bucket = str(upper_bound)
            break
    histogram[bucket] = int(histogram.get(bucket, 0)) + 1


def normalize_histogram(raw: Any) -> Dict[str, int]:
    """Return a validated sparse histogram from JSON-compatible input."""
    if not isinstance(raw, Mapping):
        return {}

    allowed = {str(bound) for bound in LATENCY_BUCKET_BOUNDS_MS}
    allowed.add(OVERFLOW_BUCKET)
    normalized: Dict[str, int] = {}
    for key, count in raw.items():
        normalized_key = str(key)
        if normalized_key not in allowed or isinstance(count, bool):
            continue
        try:
            normalized_count = int(count)
        except (TypeError, ValueError):
            continue
        if normalized_count > 0:
            normalized[normalized_key] = normalized_count
    return normalized


def merge_histograms(*histograms: Any) -> Dict[str, int]:
    """Merge persisted or in-memory histograms without losing bucket counts."""
    merged: Dict[str, int] = {}
    for histogram in histograms:
        for bucket, count in normalize_histogram(histogram).items():
            merged[bucket] = merged.get(bucket, 0) + count
    return merged


def histogram_count(histogram: Any) -> int:
    return sum(normalize_histogram(histogram).values())


def histogram_percentile(
    histogram: Any,
    percentile: float,
    *,
    overflow_value: Optional[int] = None,
) -> Optional[int]:
    """Estimate a percentile from mergeable fixed buckets."""
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be within (0, 1]")

    normalized = normalize_histogram(histogram)
    total = sum(normalized.values())
    if total == 0:
        return None

    target_rank = max(1, math.ceil(total * percentile))
    cumulative = 0
    for upper_bound in LATENCY_BUCKET_BOUNDS_MS:
        cumulative += normalized.get(str(upper_bound), 0)
        if cumulative >= target_rank:
            return upper_bound

    overflow_count = normalized.get(OVERFLOW_BUCKET, 0)
    if cumulative + overflow_count >= target_rank:
        minimum_overflow = LATENCY_BUCKET_BOUNDS_MS[-1] + 1
        return max(minimum_overflow, int(overflow_value or minimum_overflow))
    return None
