"""
Latency metrics utilities for Babbla.

The module tracks per-chunk timing information and produces summary statistics
that can be emitted as JSON for diagnostics.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Sequence


@dataclass
class ChunkMetrics:
    chunk_index: int
    char_len: int
    request_start: float
    first_frame: float
    playback_start: float
    chunk_complete: float

    @property
    def synthesis_latency_ms(self) -> float:
        # Round to avoid floating point representation artifacts (tests expect exact values).
        return round(max(0.0, (self.first_frame - self.request_start) * 1000.0), 6)

    @property
    def startup_latency_ms(self) -> float:
        return round(max(0.0, (self.playback_start - self.request_start) * 1000.0), 6)

    @property
    def buffer_fill_latency_ms(self) -> float:
        return round(max(0.0, (self.playback_start - self.first_frame) * 1000.0), 6)


def summarise_metrics(metrics: Sequence[ChunkMetrics]) -> dict[str, float]:
    if not metrics:
        return {
            "p95_first_frame_ms": 0.0,
            "p95_startup_ms": 0.0,
            "avg_inter_chunk_gap_ms": 0.0,
        }

    first_frame_latencies = [m.synthesis_latency_ms for m in metrics]
    startup_latencies = [m.startup_latency_ms for m in metrics]
    gaps = [
        max(0.0, (metrics[i].playback_start - metrics[i - 1].chunk_complete) * 1000.0)
        for i in range(1, len(metrics))
    ]

    return {
        "p95_first_frame_ms": _percentile(first_frame_latencies, 0.95),
        "p95_startup_ms": _percentile(startup_latencies, 0.95),
        "avg_inter_chunk_gap_ms": sum(gaps) / len(gaps) if gaps else 0.0,
    }


def emit_metrics_json(metrics: Sequence[ChunkMetrics], path: str | Path | None = None) -> dict:
    chunk_payload = []
    for metric in metrics:
        payload = asdict(metric)
        payload.update(
            {
                "synthesis_latency_ms": metric.synthesis_latency_ms,
                "startup_latency_ms": metric.startup_latency_ms,
                "buffer_fill_latency_ms": metric.buffer_fill_latency_ms,
            }
        )
        chunk_payload.append(payload)

    summary = summarise_metrics(metrics)
    document = {"chunks": chunk_payload, "summary": summary}

    if path is not None:
        output_path = Path(path)
        output_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    return document


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    rank = percentile * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]

    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight

