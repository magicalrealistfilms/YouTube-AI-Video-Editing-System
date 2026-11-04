# Cutting and quality limits

The supplied assembler is experimental. It scores source readings and uses waveform heuristics; it can choose the wrong attempt, miss a filler, clip a consonant, or create redundant boundaries. It writes candidate outputs only. Do not treat its output, word coverage score, or ASR spelling as an approved cut.

## Ingestion commands

From `apps/eyeline-edit/`, replacing the project and source names:
```bash
uv run tools/ingest_words.py PROJECT "Take 01 · example"
uv run tools/ingest_sync.py PROJECT "Take 01 · example" C0001.MP4 CAMERA_AUDIO_48K.wav
uv run tools/ingest_proxy.py PROJECT "Take 01 · example" /path/to/C0001.MP4
uv run tools/assemble_cut.py PROJECT take01
```
Extract camera scratch audio with FFmpeg: `ffmpeg -i C0001.MP4 -vn -ar 48000 -ac 1 CAMERA_AUDIO_48K.wav`. Sync expects 48 kHz mic and camera audio; validate start, middle and end visually and audibly. Poor scratch audio or dropouts may require manual source maps. Proxies must cover the original take clock, including handles outside the selected cut. Register camera files in footage.json and relink them in the editor.

## Review requirements

- Read the original script alongside a transcript of the **actual exported audio**. Do not substitute clip labels for transcription.
- Audition the first/last sound of each changed interval and its join in context. A short silence can precede a final t/k/p/d; extending every clip by a fixed amount can instead duplicate a word.
- Compare neighboring source intervals. Exact contiguous intervals need no extra playback restart. Overlapping intervals may repeat syllables. Remove unwanted material intentionally; don't create arbitrary splits.
- Preserve words, emotional intent, full source handles, and room for manual adjustment. Ask for a pickup if no complete reading exists.
- Save per-cut transcript evidence, then read the combined transcript for continuity, repetitions, missing logic, and off-script commands. ASR alone cannot certify audible completeness.

`qa_cut.py PROJECT [REVIEW.wav]` and `qa_edges.py PROJECT REVIEW.wav` are additional diagnostics. They may produce false positives or miss errors; edge QA has limitations with padded clips and camera-audio fallback. Use the actual export as the authoritative review. Diagnostics write reports, never the active plan.

## Current technical limits

The editor/renderer uses a 25 fps timeline and 48 kHz audio (1920 samples per frame). Record camera footage at 25p: export conforms other rates to 25 fps by dropping or repeating frames. The rate is set once, as `FPS_RATE` in `apps/eyeline-edit/project.py`; it must give a whole number of 48 kHz samples per frame. Plans store frame counts and frame-aligned times, so after changing the rate, rebuild proxies and re-save existing plans in the editor before exporting. It is not a general arbitrary-frame-rate NLE. Export performs its existing loudness pass before cut approval; later design/animation stages must not reprocess the approved WAV. Browser preview is not frame-accurate export QA. Use one editor server per project; ETag checks prevent stale tabs in that server from blindly saving over newer plans, but external writers should still pause while a person edits.

A first public release needs testing on your camera, microphone, browser, and OS. Local synthetic tests do not establish real-world speech recognition accuracy or hardware compatibility.
