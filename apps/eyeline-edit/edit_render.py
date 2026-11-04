# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "imageio-ffmpeg"]
# ///
"""Export the cut: camera picture per clip, sound sample-exact per frame (48 kHz: P.SPF samples per
frame, 1920 at 25 fps), one loudness pass, mux. Video pieces are cached on this machine, so a re-export after
small edits only renders what changed.

    edit_render.py PROJECT PLAN.json OUT.mp4 [--audio-only]
"""
import hashlib, json, os, re, subprocess, sys
from pathlib import Path

import numpy as np, soundfile as sf

import project as P

proj = P.Project(sys.argv[1])
plan = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
OUT = Path(sys.argv[3])
AUDIO_ONLY = "--audio-only" in sys.argv
FF = P.ffmpeg()
SEG = proj.cache / "segments"; SEG.mkdir(exist_ok=True)
COLOR = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
SR, SPF = P.SAMPLE_RATE, P.SPF

clip_paths = {}
def clip(name):
    if name not in clip_paths:
        p = proj.clip_path(name)
        if not p:
            sys.exit(f"Camera file {name} not found on this computer. Relink the footage first.")
        clip_paths[name] = p
    return clip_paths[name]


# 1) video pieces, cached by content
if not AUDIO_ONLY:
    enc_name, enc = P.video_encoder()
    print(f"encoder: {enc_name}", flush=True)
def seg_key(c):
    k = f"{c['cam']}|{c['camStart']:.4f}|{c['frames']}|{c.get('padFrames', 0)}|{'' if AUDIO_ONLY else enc_name}|{P.FPS_RATE}"
    return hashlib.sha1(k.encode()).hexdigest()[:14]
for c in ([] if AUDIO_ONLY else plan):
    f = SEG / f"{seg_key(c)}.mp4"
    if f.exists():
        continue
    cmd = [FF, "-v", "error", "-y", "-ss", f"{c['camStart'] - 0.001:.4f}", "-i", str(clip(c["cam"])),
           "-frames:v", str(c["frames"] + c.get("padFrames", 0)), "-an"]
    if c.get("padFrames"):
        cmd += ["-vf", f"tpad=start={c['padFrames']}:start_mode=clone"]
    cmd += enc + ["-pix_fmt", "yuv420p", "-r", P.FPS_RATE, "-video_track_timescale", str(P.VIDEO_TIMESCALE), "-g", str(P.GOP)] + COLOR + [str(f) + ".tmp.mp4"]
    subprocess.run(cmd, check=True)
    os.replace(str(f) + ".tmp.mp4", f)
    print(f"seg {c['id']}/{len(plan)}", flush=True)


# 2) sound: exactly frames*SPF samples per clip, short fades at the cuts
takes = {}
def take_audio(t):
    if t not in takes:
        x, sr = sf.read(proj.take_audio(t), dtype="float32")
        assert sr == SR, f"{t}: expected 48 kHz, got {sr}"
        takes[t] = x if x.ndim == 1 else x.mean(1)
    return takes[t]

def camera_audio(c, n):
    """The camera's own sound for a clip (used where the Mac recording dropped audio)."""
    r = subprocess.run([FF, "-v", "error", "-ss", f"{c['camStart']:.4f}", "-i", str(clip(c["cam"])), "-t", f"{n / SR + 0.1:.4f}",
                        "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32)[:n]

def roomtone(x):   # the quietest 1.5 s of the take: his real room, not digital silence
    w = int(1.5 * SR); hop = SR // 2
    best = min(range(0, max(1, len(x) - w), hop), key=lambda i: float(np.sqrt((x[i:i + w] ** 2).mean())))
    return x[best:best + w].copy()

fade = int(0.012 * SR)
ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade))
parts, rooms = [], {}
for c in plan:
    n = c["frames"] * SPF
    seg = np.zeros(n, np.float32)
    if c.get("audioSource") == "camera":
        chunk = camera_audio(c, n)
    else:
        x = take_audio(c["take"]); a0 = int(round(c["cutIn"] * SR)); chunk = x[a0:a0 + n]
    seg[:len(chunk)] = chunk
    # exact sound edges: outside [audioIn, audioOut] the clip's sound is the take's room tone, so a neighbouring
    # word never leaks in where the picture had to be cut on a frame (crossfaded over 12 ms)
    if c.get("audioSource") != "camera" and (c.get("audioIn") is not None or c.get("audioOut") is not None):
        if c["take"] not in rooms:
            rooms[c["take"]] = roomtone(take_audio(c["take"])[: 600 * SR])
        room = np.resize(rooms[c["take"]], n).astype(np.float32)
        keep = np.ones(n, np.float32)
        if c.get("audioIn") is not None and c["audioIn"] > c["cutIn"]:
            ai = min(n, int(round((c["audioIn"] - c["cutIn"]) * SR)))
            keep[:ai] = 0; e = min(fade, n - ai); keep[ai:ai + e] = ramp[:e]
        if c.get("audioOut") is not None and c["audioOut"] < c["cutIn"] + n / SR:
            ao = max(0, int(round((c["audioOut"] - c["cutIn"]) * SR)))
            keep[ao:] = 0; s0 = max(0, ao - fade); keep[s0:ao] = np.minimum(keep[s0:ao], ramp[::-1][fade - (ao - s0):])
        seg = seg * keep + room * (1 - keep)
    seg[:fade] *= ramp; seg[-fade:] *= ramp[::-1]
    if c.get("padFrames"):
        if c["take"] not in rooms:
            rooms[c["take"]] = roomtone(take_audio(c["take"])[: 600 * SR])
        m = c["padFrames"] * SPF
        seg = np.concatenate([np.resize(rooms[c["take"]], m) * np.r_[ramp, np.ones(max(0, m - 2 * fade)), ramp[::-1]][:m], seg])
    parts.append(seg)

# level: one gain per (take, source) so the two mics and the takes sit at the same speech level
def speech_db(x):
    k = len(x) // 480
    if k < 10:
        return None
    db = 20 * np.log10(np.sqrt((x[:k * 480].reshape(k, 480) ** 2).mean(1) + 1e-12))
    v = db[db > db.max() - 30]
    return float(np.percentile(v, 70)) if len(v) else None
groups = {}
for c, p in zip(plan, parts):
    lv = speech_db(p)
    if lv is not None and len(p) > SR:
        groups.setdefault((c["take"], c.get("audioSource", "mac")), []).append(lv)
med = {g: float(np.median(v)) for g, v in groups.items()}
target = float(np.median(list(med.values()))) if med else 0.0
for i, c in enumerate(plan):
    g = target - med.get((c["take"], c.get("audioSource", "mac")), target) + c.get("gainDb", 0.0)
    parts[i] = parts[i] * (10 ** (g / 20))
mix = np.concatenate(parts) if parts else np.zeros(SR, np.float32)

# loudness, aiming at -14 LUFS (YouTube) without squashing the voice (a hard limiter driven 8-10 dB made his
# louder lines buzz): bring speech to -20 LUFS, gentle voice compression (4:1 above -26 dB, slow enough
# to keep consonants natural), then a plain gain that lets a light limiter shave at most 3 dB off the
# rarest peaks (plosives). If the peaks don't allow it, the result is a little quieter; never squashed.
raw = proj.cache / "audio_raw.wav"
sf.write(raw, mix, SR, subtype="FLOAT")
def measure(af):
    err = subprocess.run([FF, "-hide_banner", "-i", str(raw), "-af", af + ",ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    x = np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(raw), "-af", af, "-ac", "1", "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1]), 20 * np.log10(float(np.percentile(np.abs(x), 99.998)) + 1e-9)
pre = -20.0 - measure("highpass=f=70")[0]
voice = f"highpass=f=70,volume={pre:.2f}dB,acompressor=threshold=-26dB:ratio=4:attack=12:release=150:knee=6"
L, pk = measure(voice)
gain = min(-17.0 - L, -1.0 - pk + 3.0)   # -17 measured in mono is -14 LUFS once copied to both stereo channels
af = f"{voice},volume={gain:.2f}dB,alimiter=limit=0.891:attack=2:release=40:level=false,pan=stereo|c0=c0|c1=c0"
got = measure(af)[0]
final = proj.cache / "audio_final.wav"
subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-af", af, "-ar", str(SR), "-c:a", "pcm_s24le", str(final)], check=True)
print(f"audio: speech {pre:+.1f} dB, compressed, gain {gain:+.1f} dB -> {got:.1f} LUFS", flush=True)

# 3) mux
OUT.parent.mkdir(parents=True, exist_ok=True)
if AUDIO_ONLY:
    out = OUT if OUT.suffix.lower() == ".wav" else OUT.with_suffix(".wav")
    os.replace(final, out)
    print("audio only ->", out)
    sys.exit(0)
lst = proj.cache / "concat.txt"
lst.write_text("".join("file '" + str(SEG / (seg_key(c) + ".mp4")).replace("\\", "/").replace("'", "'\\''") + "'\n" for c in plan), encoding="utf-8")
subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(final), "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-shortest", str(OUT)], check=True)
print("done", OUT, f"{len(mix) / SR / 60:.2f} min")
