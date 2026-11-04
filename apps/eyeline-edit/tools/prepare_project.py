# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "imageio-ffmpeg"]
# ///
"""Prepare an Eyeline project for editing in one go, for every take:

  1. find its camera clip among the project's camera files (footage/ or ../01-camera/) by sound,
  2. transcribe it (ingest_words.py), 3. sync camera to mic (ingest_sync.py), 4. build the preview (ingest_proxy.py).

Camera clips are registered in edit/footage.json and linked on this computer. Steps already done are skipped
unless --redo is given. Takes with no matching camera clip are only transcribed (audio-only takes).
Writes edit/camera-match.json and edit/prepare.json. Never touches the cut (edit/plan.json).

    uv run tools/prepare_project.py <project> [--redo] [--no-transcribe]

Lines starting with "@progress " carry JSON progress for Eyeline Home.
"""
import json, shutil, subprocess, sys
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
import camera_match as M
import project as P

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 1:
    sys.exit(__doc__)
REDO = "--redo" in sys.argv
TRANSCRIBE = "--no-transcribe" not in sys.argv
proj = P.Project(args[0])
E = proj.edit
SR = P.SAMPLE_RATE


def progress(done, total, step):
    print("@progress " + json.dumps({"done": done, "total": total, "step": step}), flush=True)


def tool(name, *argv):
    """Run one ingest tool; uv installs what it needs. Returns an error message or None."""
    uv = shutil.which("uv")
    cmd = ([uv, "run", "--script"] if uv else [sys.executable]) + [str(HERE / name), str(proj.path), *map(str, argv)]
    p = subprocess.run(cmd, cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = [l for l in p.stdout.splitlines() if l.strip() and "UV_NATIVE_TLS" not in l]
    for l in lines[-6:]:
        print("   ", l, flush=True)
    if p.returncode == 0:
        return None
    out = p.stdout.lower()
    if any(k in out for k in ("huggingface", "snapshot", "connection", "urlopen", "max retries")):
        return "the speech model could not be downloaded; check the internet connection and try again"
    if "48 khz" in out or "48000" in out:
        return "the audio is not 48 kHz; set the microphone and camera to 48 kHz"
    return (lines[-1] if lines else f"{name} failed ({p.returncode})")[:200]


def newer(a, b):
    """a exists and is at least as new as b."""
    return a.exists() and (not b.exists() or a.stat().st_mtime >= b.stat().st_mtime)


# ---------- 1. camera files: extract their sound once, then match takes to clips ----------
clips = M.camera_files(proj.path)
print(f"{len(proj.takes)} takes, {len(clips)} camera files", flush=True)
audio_dir = proj.cache / "camera-audio"; audio_dir.mkdir(exist_ok=True)
clip_wav, clip_env, clip_info = {}, {}, {}
total = len(clips) + len(proj.takes) * 3
done = 0
for c in clips:
    progress(done, total, f"Reading sound from {c.name}")
    size = c.stat().st_size
    wav = audio_dir / f"{c.name}.{size}.48k.wav"
    if not wav.exists():
        r = subprocess.run([P.ffmpeg(), "-v", "error", "-y", "-i", str(c), "-vn", "-ac", "1", "-ar", str(SR), str(wav) + ".part.wav"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  {c.name}: no usable sound, skipped ({r.stderr.strip()[:200]})", flush=True)
            done += 1; continue
        Path(str(wav) + ".part.wav").replace(wav)
    x, sr = sf.read(wav, dtype="float32")
    if c.name in clip_wav:
        print(f"  {c.name}: two camera files share this name; using the first", flush=True)
        done += 1; continue
    clip_wav[c.name], clip_env[c.name] = wav, M.envelope(x, sr)
    clip_info[c.name] = {"path": c, "size": size, "duration": round(len(x) / sr, 3)}
    done += 1

matches = {}
for key, folder in proj.takes.items():
    x, sr = sf.read(folder / "audio.wav", dtype="float32")
    cam, candidates = M.best_clip(M.envelope(x, sr), clip_env)
    matches[key] = {"take": folder.name, "cam": cam, "candidates": candidates[:3]}
    best = candidates[0] if candidates else None
    print(f"{key}: " + (f"{cam} (match {best['score']:.2f}, offset {best['offset']:+.2f} s)" if cam else
                        "no camera clip found" + (f" (closest {best['cam']}, match {best['score']:.2f})" if best else "")), flush=True)
P.write_json(E / "camera-match.json", {"created": P.now_iso(), "minScore": M.MIN_SCORE, "takes": matches})

# register the matched clips and remember where they are on this computer
used = {m["cam"] for m in matches.values() if m["cam"]}
footage = {c["name"]: c for c in P.read_json(E / "footage.json", {"clips": []})["clips"]}
for name in used:
    footage[name] = {"name": name, "size": clip_info[name]["size"], "duration": clip_info[name]["duration"]}
P.write_json(E / "footage.json", {"clips": sorted(footage.values(), key=lambda c: c["name"])})
proj.footage = list(footage.values())
for d in M.camera_dirs(proj.path):
    if d.is_dir():
        proj.relink(d)

# ---------- 2-4. per take: transcribe, sync, preview ----------
report = {}
for key, folder in proj.takes.items():
    m = matches[key]; cam = m["cam"]
    row = report[key] = {"take": folder.name, "camera": cam, "transcribed": False, "synced": False, "proxy": False, "errors": []}
    audio = folder / "audio.wav"
    words = E / "words" / f"{key}.tsv"
    progress(done, total, f"{key}: transcribing")
    if not TRANSCRIBE:
        row["transcribed"] = words.exists()
    elif REDO or not newer(words, audio):
        err = tool("ingest_words.py", folder.name)
        row["errors"] += [f"transcribe: {err}"] if err else []
        row["transcribed"] = not err
    else:
        row["transcribed"] = True
    done += 1
    if not cam:
        done += 2; continue
    sync = E / "sync" / f"{key}.json"
    progress(done, total, f"{key}: syncing camera")
    current = P.read_json(sync, {})
    if REDO or current.get("cam") != cam or not newer(sync, audio):
        err = tool("ingest_sync.py", folder.name, cam, clip_wav[cam])
        row["errors"] += [f"sync: {err}"] if err else []
        row["synced"] = not err
    else:
        row["synced"] = True
    done += 1
    progress(done, total, f"{key}: building preview")
    proxy = proj.proxy(key)
    if not row["synced"]:
        pass
    elif REDO or not newer(proxy, sync):
        err = tool("ingest_proxy.py", folder.name, clip_info[cam]["path"])
        row["errors"] += [f"preview: {err}"] if err else []
        row["proxy"] = not err
    else:
        row["proxy"] = True
    done += 1

errors = sum(len(r["errors"]) for r in report.values())
progress(total, total, "Done" if not errors else f"Done with {errors} problem(s)")
P.write_json(E / "prepare.json", {"finished": P.now_iso(), "takes": report})
ready = [k for k, r in report.items() if r["proxy"] and r["transcribed"]]
print(f"ready to edit: {len(ready)} of {len(report)} takes" + (f"; {errors} problem(s), see above" if errors else ""), flush=True)
sys.exit(1 if errors else 0)
