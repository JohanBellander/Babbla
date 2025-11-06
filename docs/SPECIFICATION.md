# ElevenLabs Low-Latency Streaming TTS CLI Specification

## 1. Overview
A cross-platform (initial focus: Windows) command-line tool that converts input text to spoken audio with minimal perceived latency using ElevenLabs streaming TTS. Audio begins playback as soon as the first PCM frames arrive. Design emphasizes modularity, extensibility, robust error handling, and observability.

## 2. Goals & Non-Goals
### Goals
- Sub-750 ms startup latency for typical (<200 chars) chunks (p95).
- High quality, natural speech leveraging ElevenLabs voice settings.
- Efficient streaming playback with adaptive buffering.
- Clean provider abstraction enabling future TTS backends.
- Detailed latency metrics and structured logging.
- Optional caching for repeated phrases.

### Non-Goals (Initial Release)
- GUI / desktop app.
- Local model inference optimization.
- Advanced SSML editing / phoneme-level control (basic pass-through later).

## 3. Functional Requirements
| Feature | Description |
|---------|-------------|
| Input Methods | CLI arg text, `--file` for UTF-8 file, STDIN pipe fallback |
| Chunking | Sentence segmentation with max length (`--max-chars`, default 200) |
| Playback | Real-time speaker output; optional WAV capture simultaneous |
| Provider | ElevenLabs streaming WebSocket (primary) |
| Voice Selection | `--voice <id|name>` (fuzzy match by name) |
| Model Selection | `--model <model_id>` default `eleven_monolingual_v1` |
| Voice Settings | Stability, similarity boost, style exaggeration, speaking rate flags |
| Listing Voices | `--list-voices` (cached 24h) |
| Logging | Human or JSON lines (`--json-log`) |
| Caching | Optional phrase-level PCM/WAV cache via `--cache-dir` |
| Dry Run | `--dry-run` shows chunk plan & provider settings without synthesis |
| WAV Output | `--save-wav <path>` stores full synthesized stream |
| Interrupt | Ctrl+C graceful cancellation, partial WAV finalize |
| Config Precedence | CLI > ENV > Config file > Defaults |
| Exit Codes | 0 success; specific codes for error classes (see §11) |

## 4. Non-Functional Requirements
- First-frame latency <600 ms p95 for standard chunks.
- Inter-chunk gap <200 ms p90.
- CPU usage <25% of one core typical.
- Memory footprint <150 MB for standard usage.
- Resilient to transient network failures (auto-retry up to 2 times).
- Secrets never logged; redacted when displayed.

## 5. Architecture
### Components
1. CLI Layer (argparse): argument parsing & command dispatch.
2. Config Manager: merges CLI flags, env vars, optional `babbla.toml`.
3. Text Normalizer & Chunker: sentence splitting, max length, whitespace cleanup.
4. Provider Abstraction: `TTSProvider` interface; `ElevenLabsProvider` implementation.
5. Streaming Controller: orchestrates chunk send & frame receive.
6. Playback Engine: ring buffer + audio device output + optional WAV sink.
7. Cache Layer: phrase-level PCM/WAV storage keyed by settings hash.
8. Metrics & Logger: timestamps, latency calculations, structured events.
9. Error & Retry Handler: categorized recovery strategies.
10. Voice Catalog Manager: local voice list cache.

### Data Flow
Text → Chunker → (for each chunk) Provider stream → frames → decode PCM → Playback ring buffer → Speakers (+ optional WAV) → Metrics collection.

## 6. Configuration
### Sources
- Environment: `ELEVENLABS_API_KEY`, others optional.
- Config file: `babbla.toml`.
- CLI flags override all.

### Example `babbla.toml`
```toml
voice_id = "Rachel"
model_id = "eleven_monolingual_v1"
chunk_max_chars = 200
prebuffer_ms = 80
stability = 0.5
similarity_boost = 0.8
cache_dir = "C:/Users/<user>/.babbla/cache"
log_format = "HUMAN"
retry_attempts = 2
```

## 7. CLI Usage
```
babbla [TEXT] [options]

Options:
  --file <path>            Read text from file.
  --voice <id|name>        Voice identifier or fuzzy name.
  --model <model_id>       Model (default eleven_monolingual_v1).
  --max-chars <n>          Max characters per chunk (default 200).
  --prebuffer-ms <ms>      Initial audio prebuffer (default 80).
  --list-voices            List voices and exit.
  --save-wav <path>        Save stream to WAV while playing.
  --cache-dir <path>       Enable caching directory.
  --cache-ttl <seconds>    TTL (default 604800).
  --json-log               JSON line logs.
  --dry-run                Show plan only (no API calls).
  --env-file <path>        Load environment variables file.
  --no-chunk               Disable chunking (single request).
  --stability <float>      Override stability.
  --similarity <float>     Override similarity boost.
  --style <float>          Style exaggeration.
  --rate <float>           Speaking rate.
  --timeout <ms>           Network timeout (default 10000).
  -q, --quiet              Minimal output.
  -v, --verbose            Debug logging.
  -h, --help               Help.
```

## 8. Interfaces
### Configuration Object (Python dataclass)
Fields: `api_key: str`, `voice_id: str`, `model_id: str`, `stability: float`, `similarity_boost: float`, `style_exaggeration: Optional[float]`, `speaking_rate: Optional[float]`, `chunk_max_chars: int`, `prebuffer_ms: int`, `retry_attempts: int`, `retry_backoff_base_ms: int`, `cache_dir: Optional[Path]`, `cache_ttl_seconds: int`, `log_format: Enum`, `save_wav_path: Optional[Path]`.

### Provider Abstraction `TTSProvider`
Methods:
- `connect() -> None`
- `stream(text_chunk: str, settings: ProviderSynthesisSettings) -> Iterable[AudioFrame]`
- `list_voices(force_refresh: bool=False) -> List[VoiceInfo]`
- `close() -> None`

Data Structures:
- `AudioFrame { pcm: bytes, sample_rate: int, timestamp_provider: float, is_final: bool }`
- `VoiceInfo { voice_id: str, name: str, labels: Dict[str,str], sample_rate: int? }`
- `ProviderSynthesisSettings { model_id, voice_id, stability, similarity_boost, style_exaggeration?, speaking_rate? }`

### Playback Engine
Methods: `start(sample_rate)`, `submit(frame)`, `flush_and_close()`.
Adaptive ring buffer sized to `prebuffer_ms` (initial) with underrun detection.

## 9. ElevenLabs Provider Details
WebSocket endpoint (conceptual):
`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream`

Initial message example:
```json
{
  "text": "<chunk>",
  "model_id": "eleven_monolingual_v1",
  "voice_settings": {
    "stability": 0.5,
    "similarity_boost": 0.8,
    "style_exaggeration": 0.0,
    "use_speaker_boost": true
  },
  "OptimizeStreamingLatency": 1
}
```
Incoming frame message example:
```json
{ "audio": "<base64 pcm16>", "is_final": false }
```
Final: `{ "is_final": true }`

## 10. Latency Strategy
Timestamps: `t_request_start`, `t_first_frame_received`, `t_playback_start`, `t_chunk_complete`.
Metrics:
- Synthesis latency = first_frame - request_start
- Startup latency = playback_start - request_start
- Buffer fill latency = playback_start - first_frame
Adaptive behaviors:
- Reduce chunk size 20% if p95 synthesis latency exceeds threshold.
- Increase `prebuffer_ms` by 20ms on underruns (cap 200ms).

Targets:
- First frame <600 ms p95.
- Playback start <750 ms p95.
- Inter-chunk gap <200 ms p90.

## 11. Error Handling & Exit Codes
Categories:
| Error | Strategy | Exit Code |
|-------|----------|-----------|
| Auth Missing/Invalid | Fail fast, instruct user | 2 |
| Rate Limit | Retry (2 attempts, exp backoff) | 3 if final fail |
| Network Transient | Reconnect & resend chunk | 3 |
| Provider Malformed | Fail fast | 3 |
| Audio Device | Report & suggest device check | 4 |
| Interrupt (Ctrl+C) | Graceful stop | 130 |
| Config Format | Fail fast | 2 |

## 12. Security & Secrets
- API key sources: env, `.env` file, config file.
- Redaction pattern: show last 4 chars only.
- Never in logs or cache filenames.
- Potential future integration: Windows Credential Manager.

## 13. Caching Design
Key: `SHA256(voice_id + model_id + stability + similarity + text_chunk)`.
Structure:
```
cache_dir/
  ab/abcdef123... .pcm
  ab/abcdef123... .json (metadata)
```
TTL enforcement at startup + periodic sweep.
Cache only complete chunks (final frame received).

## 14. Testing Strategy
Unit Tests:
- Chunking boundaries & punctuation.
- Config precedence.
- Cache key determinism.
- Provider frame parsing (mock messages).

Integration Tests:
- End-to-end with mocked WebSocket.
- Interrupt handling.
- WAV output correctness.

Latency Harness:
- Standard paragraph run ×5, produce JSON summary (avg, p95).

Audio Validation:
- Continuity (no gap >40ms).
- Optional RMS loudness check.

## 15. Extensibility
Add provider: implement `TTSProvider` and register factory mapping.
Local fallback (future): `LocalCoquiProvider` streaming PCM slices.

## 16. Milestones
| Phase | Deliverable | Success Metric |
|-------|-------------|----------------|
| 1 MVP | Single chunk streaming & playback | Sentence spoken <1s |
| 2 Chunking | Multi-chunk overlap | Paragraph smooth playback |
| 3 Caching & Voices | Voice list & phrase cache | Cache hit reduces latency |
| 4 Robustness | Retry & adaptive buffering | Underruns minimized |
| 5 Output & Tests | WAV + test suite + harness | CI green, latency report |
| 6 Polish | Config file, dry run, docs | Onboarding <5 min |

## 17. Observability
Events: `chunk_start`, `first_frame`, `playback_start`, `chunk_complete`, `retry`, `error`, `interrupt`.
Summary printed at completion:
- Total chunks
- Avg & p95 first-frame latency
- Avg & p95 startup latency
- Cache hits

Future: Prometheus endpoint or OpenTelemetry traces.

## 18. WAV Output
- Open file lazily at first frame to know sample rate.
- Stream PCM frames; finalize header on close.
- On interrupt: finalize header with bytes written so far.

## 19. Edge Cases
- Empty input / whitespace-only → usage error.
- Very long single token → forced split.
- Device unavailable → fallback attempt then error.
- Network drop mid-chunk → single retry; if partial frames exist continue playback.
- Rate limit repeated → exponential backoff then fail.
- High jitter → adaptive prebuffer increase.

## 20. Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| API schema changes | Isolate provider; versioned adapter tests |
| Rate limit escalation | Backoff & user guidance to upgrade plan |
| Audio underruns | Adaptive buffer & chunk size tuning |
| Memory growth via cache | TTL + size cap (future) |

## 21. Future Enhancements
- SSML support.
- Real-time incremental synthesis for live transcripts.
- Multi-voice mixing.
- GUI wrapper.
- Offline local model fallback.

## 22. Success Criteria
MVP success: `babbla "Hello low latency world."` produces audible speech with first audio frame <700 ms.
Phase success tracked by `latency_report.json` harness.

## 23. Glossary
- First-byte latency: Request start → first audio frame arrival.
- Startup latency: Request start → first audible playback.
- Jitter buffer: Small frame accumulation to smooth network variability.

---
End of specification.
