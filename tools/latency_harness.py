from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import fmean
from typing import List

from voicecli.elevenlabs_provider import ElevenLabsProvider
from voicecli.metrics import ChunkMetrics, emit_metrics_json, summarise_metrics
from voicecli.streaming_controller import StreamingController

HARNESS_TEXT = (
    "VoiceCLI harness paragraph. "
    "This text is used to exercise the streaming pipeline and produce metrics. "
    "It should be long enough to span multiple chunks and simulate a realistic "
    "synthesis workload for latency tracking."
)


class DummyPlayback:
    def __init__(self):
        self.started = False
        self.sample_rate = None

    def start(self, sample_rate: int) -> None:
        self.started = True
        self.sample_rate = sample_rate

    def submit(self, frame):
        if not self.started:
            raise RuntimeError("Playback not started")

    def flush_and_close(self) -> None:
        self.started = False


def run_iteration(text: str) -> List[ChunkMetrics]:
    provider = ElevenLabsProvider()
    playback = DummyPlayback()
    controller = StreamingController(
        provider,
        playback,
        metrics=[],
    )
    return controller.run(
        text,
        sample_rate=provider.sample_rate,
        provider_settings={
            "voice_id": "HarnessVoice",
            "model_id": "eleven_monolingual_v1",
            "stability": 0.5,
            "similarity": 0.8,
        },
    )


def build_report(all_metrics: List[List[ChunkMetrics]], output: Path) -> dict:
    flat_metrics = [metric for metrics in all_metrics for metric in metrics]
    summary = summarise_metrics(flat_metrics)
    first_frames = [m.synthesis_latency_ms for m in flat_metrics]
    startup = [m.startup_latency_ms for m in flat_metrics]
    summary["avg_first_frame_ms"] = fmean(first_frames) if first_frames else 0.0
    summary["avg_startup_ms"] = fmean(startup) if startup else 0.0

    per_iteration = []
    for idx, metrics in enumerate(all_metrics, start=1):
        per_iteration.append({
            "iteration": idx,
            "summary": summarise_metrics(metrics),
        })

    report = {
        "iterations": len(all_metrics),
        "summary": summary,
        "iterations_detail": per_iteration,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VoiceCLI latency harness")
    parser.add_argument("--iterations", type=int, default=5, help="Number of runs to average")
    parser.add_argument("--output", type=Path, default=Path("latency_report.json"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    all_metrics: List[List[ChunkMetrics]] = []
    for _ in range(max(1, args.iterations)):
        all_metrics.append(run_iteration(HARNESS_TEXT))
    build_report(all_metrics, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
