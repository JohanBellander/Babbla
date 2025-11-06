from __future__ import annotations

from pathlib import Path

from tools import latency_harness
from babbla.metrics import ChunkMetrics


def _metric(offset: float) -> ChunkMetrics:
    return ChunkMetrics(
        chunk_index=0,
        char_len=10,
        request_start=offset,
        first_frame=offset + 0.1,
        playback_start=offset + 0.12,
        chunk_complete=offset + 0.3,
    )


def test_report_schema(tmp_path):
    metrics = [[_metric(0.0), _metric(0.4)]]
    output = tmp_path / "report.json"
    report = latency_harness.build_report(metrics, output)

    assert output.exists()
    assert report["summary"]["p95_first_frame_ms"] >= 0
    assert "avg_first_frame_ms" in report["summary"]
    assert len(report["iterations_detail"]) == 1
    assert report["iterations_detail"][0]["summary"]["avg_inter_chunk_gap_ms"] >= 0
