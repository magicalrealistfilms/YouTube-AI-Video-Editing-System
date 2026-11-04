# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy", "soundfile", "scipy", "imageio-ffmpeg",
#   "mlx-whisper; sys_platform == 'darwin' and platform_machine == 'arm64'",
#   "faster-whisper; sys_platform != 'darwin' or platform_machine != 'arm64'",
# ]
# ///
"""QA for an Eyeline Edit cut. Rebuilds the cut's sound exactly as the export does (frames x P.SPF samples per
clip, 12 ms fades), re-transcribes every word of it, matches each heard word to the clip it should come from,
and checks every join and edge on the waveform. Writes edit/qa-report.md and edit/qa.json; writes diagnostic flags to plan.qa-flags.json without editing the active cut.

    uv run tools/qa_cut.py <project> [qa.wav]
"""
import json, os, re, sys, tempfile, subprocess
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
HUB = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / "models--mlx-community--whisper-large-v3-turbo" / "snapshots"
if HUB.is_dir() and any(HUB.iterdir()):
    os.environ["HF_HUB_OFFLINE"] = "1"
import project as P

SR = P.SAMPLE_RATE; SPF = P.SPF
FILLERS = {"um", "uh", "er", "erm", "ah", "hmm", "mm", "uhm", "umm", "uhh"}
proj = Path(sys.argv[1]); E = proj / "edit"
qa_wav = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.gettempdir()) / "eyeline-qa.wav"
plan = json.loads((E / "plan.json").read_text())


from textnorm import norm


takes, envs = {}, {}
for t in (proj / "takes").iterdir():
    k = P.take_key(t.name)
    if k and any(c["take"] == k for c in plan):
        x, _ = sf.read(t / "audio.wav", dtype="float32"); takes[k] = x if x.ndim == 1 else x.mean(1)
        def env(sig):
            p = np.convolve(sig.astype(np.float64) ** 2, np.ones(384) / 384, "same")[::48]
            return 10 * np.log10(p + 1e-12)
        eb = env(sosfiltfilt(butter(4, [80, 8000], "bandpass", fs=SR, output="sos"), takes[k]))
        eh = env(sosfiltfilt(butter(4, [3500, 11000], "bandpass", fs=SR, output="sos"), takes[k]))
        fb_, fh_ = np.percentile(eb, 12), np.percentile(eh, 12)
        tj = json.loads((t / "take.json").read_text())
        for ch in ((tj.get("health") or {}).get("chirps") or []):
            a_, b_ = max(0, int((ch - 0.1) * 1000)), int((ch + 0.4) * 1000); eb[a_:b_] = fb_; eh[a_:b_] = fh_
        envs[k] = (eb, eh, fb_, fh_)
words = {k: [(float(a), float(b), w) for a, b, w, *_ in (l.split("\t") for l in (E / "words" / f"{k}.tsv").read_text().splitlines()[1:])]
         for k in takes}

# 1. the cut's sound, exactly as the export builds it
fade = int(0.012 * SR); ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade))
parts, starts, t, rooms = [], [], 0.0, {}
for c in plan:
    n = c["frames"] * SPF; a0 = int(round(c["cutIn"] * SR))
    seg = takes[c["take"]][a0:a0 + n].copy()
    if len(seg) < n:
        seg = np.pad(seg, (0, n - len(seg)))
    if c.get("audioIn") is not None or c.get("audioOut") is not None:
        x = takes[c["take"]]
        if c["take"] not in rooms:
            w = int(1.5 * SR); hop = SR // 2; xx = x[:600 * SR]
            b0 = min(range(0, max(1, len(xx) - w), hop), key=lambda i: float(np.sqrt((xx[i:i + w] ** 2).mean())))
            rooms[c["take"]] = xx[b0:b0 + w].copy()
        room = np.resize(rooms[c["take"]], n).astype(np.float32); keep = np.ones(n, np.float32)
        if c.get("audioIn") is not None and c["audioIn"] > c["cutIn"]:
            ai = min(n, int(round((c["audioIn"] - c["cutIn"]) * SR))); keep[:ai] = 0; e = min(fade, n - ai); keep[ai:ai + e] = ramp[:e]
        if c.get("audioOut") is not None and c["audioOut"] < c["cutIn"] + n / SR:
            ao = max(0, int(round((c["audioOut"] - c["cutIn"]) * SR))); keep[ao:] = 0
            s0 = max(0, ao - fade); keep[s0:ao] = np.minimum(keep[s0:ao], ramp[::-1][fade - (ao - s0):])
        seg = seg * keep + room * (1 - keep)
    seg[:fade] *= ramp; seg[-fade:] *= ramp[::-1]
    parts.append(seg); starts.append(t); t += n / SR
sf.write(qa_wav, np.concatenate(parts), SR, subtype="PCM_16")
total = t
print(f"QA audio {total / 60:.2f} min, {len(plan)} clips -> {qa_wav}", flush=True)

# 2. re-transcribe every word
tmp = qa_wav.with_suffix(".16k.wav")
subprocess.run([P.ffmpeg(), "-v", "error", "-y", "-i", str(qa_wav), "-ac", "1", "-ar", "16000", str(tmp)], check=True)
import asr as mlx_whisper
r = mlx_whisper.transcribe(str(tmp), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en",
                           word_timestamps=True, condition_on_previous_text=False, temperature=0.0,
                           initial_prompt="Um, so, uh, basically you guys, I mean, like, um, okay. Uh, so the, the thing is, um, right.")
heard = []
for s in r["segments"]:
    for w in s.get("words", []):
        for tok in norm(w["word"]):
            heard.append({"s": w["start"], "e": w["end"], "n": tok, "w": w["word"].strip()})
tmp.unlink(missing_ok=True)

# 3. match heard words to expected words, clip by clip
exp = []
for i, c in enumerate(plan):
    for tok in norm(c["text"]):
        exp.append((i, tok))
sm = SequenceMatcher(None, [e[1] for e in exp], [h["n"] for h in heard], autojunk=False)
exp_hit = {}; heard_hit = set()
for b in sm.get_matching_blocks():
    for q in range(b.size):
        exp_hit[b.a + q] = b.b + q; heard_hit.add(b.b + q)
clip_of_time = lambda tt: int(np.searchsorted(starts, tt, side="right") - 1)

issues = {i: [] for i in range(len(plan))}
for j, (i, tok) in enumerate(exp):
    if j not in exp_hit:
        issues[i].append(f"word not heard: '{tok}'")
for q, h in enumerate(heard):
    i = clip_of_time((h["s"] + h["e"]) / 2)
    if h["n"] in FILLERS:
        issues[i].append(f"filler heard: '{h['w']}' at {h['s']:.2f}s")
    elif q not in heard_hit:
        issues[i].append(f"extra word heard: '{h['w']}' at {h['s']:.2f}s")

# repeated phrases in what is heard (a restart left inside a reading, or a line said twice across a join)
toks = [h["n"] for h in heard]
q = 0
while q < len(toks):
    hit = None
    for n in range(8, 1, -1):
        if q + 2 * n <= len(toks) and toks[q:q + n] == toks[q + n:q + 2 * n] and len(set(toks[q:q + n])) > 1:
            hit = n; break
    if hit:
        i = clip_of_time(heard[q + hit]["s"])
        issues[i].append(f"repeated phrase heard: '{' '.join(toks[q:q + hit])}' at {heard[q]['s']:.2f}s")
        q += 2 * hit
    else:
        q += 1

# 4. waveform checks per clip: edges inside sound, leftover silence, unrecognised sound, level steps
lvl = []; notes = {}
for i, c in enumerate(plan):
    eb, eh, fb, fh = envs[c["take"]]
    a_in = max(c["cutIn"], c.get("audioIn") or c["cutIn"]); a_out = min(c["cutOut"], c.get("audioOut") or c["cutOut"])
    i0, i1 = int(round(a_in * 1000)), int(round(a_out * 1000))
    snd = (eb[i0:i1] > fb + 20) | (eh[i0:i1] > fh + 24)            # speech, not breath
    cont_in = i > 0 and plan[i - 1].get("joinNext") == "continuous"
    cont_out = c.get("joinNext") == "continuous"
    glued_in = eb[i0:i0 + 6].max() <= eb[max(0, i0 - 40):i0 + 40].min() + 4      # already the quietest point around
    glued_out = eb[i1 - 6:i1].max() <= eb[max(0, i1 - 40):i1 + 40].min() + 4
    connected_in = eb[max(0, i0 - 40):i0].min() > fb + 15        # the word before runs straight into this one
    if eb[i0:i0 + 6].max() > fb + 20 and not cont_in:
        if connected_in or glued_in:
            notes.setdefault(i, []).append("starts in connected speech (the word before is muted to room tone)")
        else:
            issues[i].append(f"starts inside a sound ({eb[i0:i0 + 6].max() - fb:.0f} dB over room tone)")
    connected_out = eb[i1:i1 + 40].min() > fb + 15 if i1 + 40 <= len(eb) else False
    if eb[i1 - 6:i1].max() > fb + 20 and not cont_out:
        if connected_out or glued_out:
            notes.setdefault(i, []).append("ends in connected speech (the word after is muted to room tone)")
        else:
            issues[i].append(f"ends inside a sound ({eb[i1 - 6:i1].max() - fb:.0f} dB over room tone)")
    lead = int(np.argmax(snd)) if snd.any() else len(snd)
    trail = int(np.argmax(snd[::-1])) if snd.any() else len(snd)
    if lead > 90 and not cont_in:
        issues[i].append(f"{lead} ms of silence at the start")
    if trail > 110 and not cont_out:
        issues[i].append(f"{trail} ms of silence at the end")
    # silence inside the clip longer than the pause limit
    run = 0; longest = 0
    for v in snd[lead:len(snd) - trail]:
        run = 0 if v else run + 1; longest = max(longest, run)
    if longest > 220:
        issues[i].append(f"{longest} ms pause inside the clip")
    # sound not covered by any recognised word (an um or noise Whisper skipped)
    ws = [(a, b) for a, b, _ in words[c["take"]] if b > c["cutIn"] and a < c["cutOut"]]
    cov = np.zeros(len(snd), bool)
    for a, b in ws:
        cov[max(0, int(a * 1000) - i0 - 40):max(0, int(b * 1000) - i0 + 60)] = True
    unc = snd & ~cov; run = 0; worst = 0
    for v in unc:
        run = run + 1 if v else 0; worst = max(worst, run)
    if worst > 160:
        issues[i].append(f"{worst} ms of sound that is not a recognised word (possible um or noise)")
    voiced = eb[i0:i1][snd]
    lvl.append((np.median(voiced[:400]) if len(voiced) else None, np.median(voiced[-400:]) if len(voiced) else None))
for i in range(len(plan) - 1):
    a, b = lvl[i][1], lvl[i + 1][0]
    if a is not None and b is not None and abs(a - b) > 7 and plan[i]["take"] != plan[i + 1]["take"]:
        issues[i + 1].append(f"level jump of {b - a:+.0f} dB from the previous clip")

# 5. report, and the QA note on each failing clip
bad = {i: v for i, v in issues.items() if v}
for i, c in enumerate(plan):
    c["flag"] = ("; ".join(issues[i])) if issues[i] else None
P.write_json(E / "plan.qa-flags.json", plan)
P.write_json(E / "qa.json", {"clips": len(plan), "failing": len(bad), "length": round(total, 3),
                             "heardWords": len(heard), "expectedWords": len(exp), "matchedWords": len(exp_hit),
                             "issues": {str(plan[i]["id"]): v for i, v in bad.items()},
                             "notes": {str(plan[i]["id"]): v for i, v in notes.items()}})
lines = [f"# QA · {proj.name}", "", f"{len(plan)} clips · {total / 60:.2f} min · {len(exp_hit)}/{len(exp)} expected words heard"
         f" · {len(heard) - len(heard_hit)} extra words heard · {len(bad)} clips with issues", ""]
for i, v in bad.items():
    m, s = divmod(starts[i], 60)
    lines.append(f"- clip {plan[i]['id']} at {int(m)}:{s:04.1f} ({plan[i]['take']} {plan[i]['cutIn']:.2f}s): " + "; ".join(v))
P.write_atomic(E / "qa-report.md", "\n".join(lines) + "\n")
print("\n".join(lines[:3]))
print(f"{len(bad)} clips with issues; report in {E / 'qa-report.md'}")
