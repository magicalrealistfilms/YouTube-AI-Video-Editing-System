# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy", "soundfile", "imageio-ffmpeg",
#   "mlx-whisper; sys_platform == 'darwin' and platform_machine == 'arm64'",
#   "faster-whisper; sys_platform != 'darwin' or platform_machine != 'arm64'",
# ]
# ///
"""Transcribe the final cut's audio, word by word, so every later step (board briefs, word-synced boards,
subtitles) works from what is actually heard in the cut, ad-libs included, never from the script.

    edit_transcribe.py PROJECT FINAL.wav

Writes next to the WAV:
    <name> script.txt       plain text of the cut, one paragraph per chapter (chapter headings as "## ...")
    <name> words.tsv        start, end, word, frame_in, frame_out, confidence (seconds on the final timeline)
    <name> subtitles.srt    YouTube-ready captions
    <name> transcript.json  words + chapters
where <name> is the WAV's name without ".wav" (e.g. "Example Video - final cut").
Mac (Apple silicon): mlx-whisper. Windows and others: faster-whisper (GPU if there is one, else CPU).
"""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

# Once the speech model is on this computer, never ask the internet again (a stalled update check hung the
# export); the first download gets short timeouts so a bad connection fails instead of hanging.
HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
MODELS = ["models--mlx-community--whisper-large-v3-turbo", "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
          "models--Systran--faster-whisper-large-v3-turbo", "models--deepdml--faster-whisper-large-v3-turbo-ct2"]
if any((HUB / m / "snapshots").is_dir() and any((HUB / m / "snapshots").iterdir()) for m in MODELS):
    os.environ["HF_HUB_OFFLINE"] = "1"
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "15")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

import project as P

proj = P.Project(sys.argv[1])
WAV = Path(sys.argv[2])
BASE = WAV.with_suffix("")
FPS = P.FPS

# 16 kHz mono copy for the recogniser
tmp = Path(tempfile.gettempdir()) / f"eyeline-{proj.id}-16k.wav"
subprocess.run([P.ffmpeg(), "-v", "error", "-y", "-i", str(WAV), "-ac", "1", "-ar", "16000", str(tmp)], check=True)
print("transcribing (the first run downloads the speech model, about 1.5 GB)...", flush=True)

segments = []   # [{text, no_speech, words: [(start, end, word, prob)]}]
try:
    import mlx_whisper
    r = mlx_whisper.transcribe(str(tmp), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en",
                               word_timestamps=True, condition_on_previous_text=False, temperature=0.0)
    for s in r["segments"]:
        segments.append({"text": s["text"], "no_speech": s.get("no_speech_prob", 0),
                         "words": [(w["start"], w["end"], w["word"], w.get("probability", 1)) for w in s.get("words", [])]})
except ImportError:
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(tmp), language="en", word_timestamps=True, condition_on_previous_text=False, temperature=0.0)
    for s in segs:
        segments.append({"text": s.text, "no_speech": s.no_speech_prob,
                         "words": [(w.start, w.end, w.word, w.probability) for w in (s.words or [])]})
        print(f"  {s.end / 60:5.1f} min", flush=True)

# words: drop the recogniser's stock hallucinations on silence, glue "$5" ",000" back together
words = []
for s in segments:
    if re.fullmatch(r"\s*(thank you\.?|thanks for watching\.?|you)\s*", s["text"].lower()) and s["no_speech"] > 0.3:
        continue
    for a, b, w, p in s["words"]:
        w = w.strip()
        if not w:
            continue
        if words and re.match(r"^[,.]\d", w) and re.search(r"\d$", words[-1][2]):
            words[-1] = (words[-1][0], b, words[-1][2] + w, min(words[-1][3], p))
        else:
            words.append((round(a, 2), round(b, 2), w, round(float(p), 2)))

# chapters on the final timeline, from the cut
plan = P.normalize(proj.plan(), proj)
chapters = []
for c in plan:
    t = (c.get("chapter") or "").strip()
    if t and (not chapters or chapters[-1][1] != t):
        chapters.append((c["outStart"], t))

ts = lambda t: f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(round(t % 1 * 1000)) % 1000:03d}"
with open(f"{BASE} words.tsv", "w", encoding="utf-8") as f:
    f.write("start\tend\tword\tframe_in\tframe_out\tconfidence\n")
    for a, b, w, p in words:
        f.write(f"{a:.2f}\t{b:.2f}\t{w}\t{round(a * FPS)}\t{round(b * FPS)}\t{p}\n")

# plain text, a paragraph per chapter
paras, ci = [], -1
for a, b, w, p in words:
    while ci + 1 < len(chapters) and a >= chapters[ci + 1][0] - 0.05:
        ci += 1; paras.append([f"## {chapters[ci][1]}", []])
    if not paras:
        paras.append(["", []])
    paras[-1][1].append(w)
text = "\n\n".join((h + "\n" if h else "") + " ".join(ws) for h, ws in paras if ws)
P.write_atomic(f"{BASE} script.txt", text + "\n")

# subtitles: up to two lines of ~42 characters, at most 6 s, break at sentence ends and pauses
cues, cur = [], []
for i, x in enumerate(words):
    if cur and (len(" ".join(y[2] for y in cur + [x])) > 84 or x[1] - cur[0][0] > 6.0 or x[0] - cur[-1][1] > 0.7):
        cues.append(cur); cur = []
    cur.append(x)
    if re.search(r"[.?!]$", x[2]) and len(" ".join(y[2] for y in cur)) > 20:
        cues.append(cur); cur = []
if cur:
    cues.append(cur)
def two_lines(t):
    if len(t) <= 42:
        return t
    ws = t.split(); k = min(range(1, len(ws)), key=lambda k: abs(len(" ".join(ws[:k])) - len(" ".join(ws[k:]))))
    return " ".join(ws[:k]) + "\n" + " ".join(ws[k:])
srt = []
for n, c in enumerate(cues, 1):
    end = c[-1][1] if n == len(cues) else min(c[-1][1] + 0.3, cues[n][0][0] - 0.02)
    srt.append(f"{n}\n{ts(c[0][0])} --> {ts(max(end, c[0][0] + 0.5))}\n{two_lines(' '.join(y[2] for y in c))}\n")
P.write_atomic(f"{BASE} subtitles.srt", "\n".join(srt))

P.write_json(f"{BASE} transcript.json", {
    "source": WAV.name, "fps": P.FPS_RATE, "timing": "seconds on the final cut",
    "words": [{"start": a, "end": b, "word": w, "confidence": p} for a, b, w, p in words],
    "chapters": [{"start": round(t, 3), "title": h} for t, h in chapters]})
tmp.unlink(missing_ok=True)
print(f"transcript: {len(words)} words, {len(chapters)} chapters, {len(cues)} subtitles -> {BASE} script.txt", flush=True)
