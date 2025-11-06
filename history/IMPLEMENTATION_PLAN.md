# Implementation Plan: ElevenLabs Low-Latency Streaming TTS CLI

Reference: `docs/SPECIFICATION.md`

## Phase Summary
1. MVP Scaffold
2. Chunking & Overlap
3. Voices & Phrase Cache
4. Robustness & Observability
5. Output & Testing
6. Polish & Adaptive Optimization

## Phase Details
### Phase 1: MVP Scaffold
Goal: Single sentence spoken end-to-end (manual chunk).
Deliverables:
- Project structure (`src/babbla/`)
- `config.py` (load env + defaults)
- `provider_base.py` (TTSProvider interface)
- `elevenlabs_provider.py` (connect + dummy stream stub returning simulated frames)
- `playback.py` (basic PCM16 playback using sounddevice)
- `cli.py` minimal parsing (text arg, voice id, model)
- `requirements.txt` (argparse, sounddevice, websockets, requests)
Acceptance: `python -m babbla "Hello world"` speaks audio (stub or real if key present).

### Phase 2: Chunking & Overlap
Goal: Paragraph plays smoothly.
Deliverables:
- `chunker.py` with sentence split + max length.
- Streaming controller orchestrating sequential chunk requests with early playback.
- Metrics timestamps for each chunk.
Acceptance: Multi-chunk playback with inter-chunk gap <200ms (simulated or real).

### Phase 3: Voices & Phrase Cache
Goal: Reduce repeated phrase latency & voice enumeration.
Deliverables:
- `voice_catalog.py` fetch + 24h cache.
- `cache.py` phrase-level cache (PCM + metadata).
- Integrate cache lookup before provider call.
Acceptance: Repeat invocation of same phrase uses cache (log event `cache_hit`).

### Phase 4: Robustness & Observability
Goal: Resilient streaming.
Deliverables:
- Retry logic (exponential backoff on network / rate limit).
- Structured JSON logging option.
- Error classes + mapping.
- Adaptive prebuffer adjustments on underrun.
Acceptance: Forced simulated network drop recovers; JSON logs show events.

### Phase 5: Output & Testing
Goal: Confidence in correctness & performance.
Deliverables:
- WAV saving implementation.
- pytest suite: chunker, config, cache, playback (mock).
- Mock WebSocket server fixture.
- Latency harness script `tools/latency_harness.py`.
Acceptance: `pytest` passes; harness produces `latency_report.json` for standard sample.

### Phase 6: Polish & Adaptive Optimization
Goal: Final user experience and maintainability.
Deliverables:
- Dry-run mode.
- Adaptive chunk size + buffer tuning based on metrics.
- README enhancements & final docs link.
Acceptance: Dry-run lists plan; adaptive system logs adjustments.

## Cross-Cutting Concerns
- Security: Redact API key in logs.
- Configuration precedence: CLI > ENV > config file.
- Performance metrics: Collect per chunk and summary.

## File Layout (Initial)
```
src/babbla/__init__.py
src/babbla/cli.py
src/babbla/config.py
src/babbla/provider_base.py
src/babbla/elevenlabs_provider.py
src/babbla/playback.py
src/babbla/chunker.py (Phase 2)
src/babbla/cache.py (Phase 3)
src/babbla/voice_catalog.py (Phase 3)
src/babbla/logging_utils.py (Phase 4)
src/babbla/metrics.py (Phase 2+)
src/babbla/errors.py (Phase 4)
```

## Testing Strategy Summary
- Unit tests target deterministic logic (chunking, caching, config precedence).
- Provider tests use mocked WebSocket messages.
- Playback tests mock sounddevice to avoid hardware dependency.

## Acceptance Matrix (Phases vs Metrics)
| Phase | Latency Startup p95 | Inter-chunk gap p90 | Cache Hit Impact |
|-------|---------------------|---------------------|------------------|
| 1     | <1500 ms            | N/A                 | N/A              |
| 2     | <900 ms             | <200 ms             | N/A              |
| 3     | <900 ms             | <200 ms             | Repeat phrase <150 ms |
| 4     | <900 ms             | <200 ms             | Maintained       |
| 5     | <850 ms             | <180 ms             | Maintained       |
| 6     | <800 ms             | <170 ms             | Maintained       |

## Risk Mitigation Quick List
- API changes: Isolate provider adapter.
- Network instability: Retry + adaptive buffer.
- Audio underruns: Increase prebuffer_ms & reduce chunk length.
- Large memory use: TTL-based cache eviction.

## Implementation Order (Beads)
1. Scaffold project.
2. Config loader.
3. Playback engine minimal.
4. Provider base + stub.
5. CLI MVP (single chunk).
6. Chunker + metrics timestamps.
7. Streaming controller multi-chunk.
8. Voice catalog.
9. Phrase cache.
10. Error classes + retry logic.
11. JSON logging option.
12. WAV saving.
13. Test suite foundation.
14. Latency harness.
15. Dry-run mode.
16. Adaptive buffer & chunk sizing.
17. Documentation polish.

## Completion Definition
All acceptance criteria satisfied; `pytest` green; latency harness within Phase 6 targets; README instructs quick start under 5 mins.
