import json

import pytest

from babbla.metrics import ChunkMetrics, emit_metrics_json, summarise_metrics


def test_metrics_derivations():
    metric = ChunkMetrics(
        chunk_index=0,
        char_len=50,
        request_start=1.0,
        first_frame=1.2,
        playback_start=1.25,
        chunk_complete=1.6,
    )

    assert metric.synthesis_latency_ms == 200.0
    assert metric.startup_latency_ms == 250.0
    assert metric.buffer_fill_latency_ms == 50.0


def test_summary_calculations(tmp_path):
    metrics = [
        ChunkMetrics(0, 50, 0.0, 0.2, 0.25, 0.5),
        ChunkMetrics(1, 80, 0.5, 0.65, 0.7, 0.9),
        ChunkMetrics(2, 70, 0.9, 1.2, 1.25, 1.5),
    ]

    summary = summarise_metrics(metrics)
    assert summary["p95_first_frame_ms"] == pytest.approx(290.0, rel=1e-3)
    assert summary["p95_startup_ms"] == pytest.approx(340.0, rel=1e-3)
    assert summary["avg_inter_chunk_gap_ms"] == pytest.approx(275.0, rel=1e-3)

    output_path = tmp_path / "metrics.json"
    document = emit_metrics_json(metrics, path=output_path)
    assert output_path.exists()

    reloaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert document == reloaded
    assert len(document["chunks"]) == 3
