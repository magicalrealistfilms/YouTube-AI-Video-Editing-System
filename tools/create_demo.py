# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "imageio-ffmpeg"]
# ///
"""Generate a six-second synthetic source and editable two-clip demonstration."""
import argparse, json, os, subprocess, sys
from pathlib import Path
from init_project import create

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/eyeline-edit"))
import project as P
import numpy as np, soundfile as sf

def build(destination):
    root = create(destination)
    recording = root / "01-recording"
    take_name = "Take 01 · synthetic"
    take = recording / "takes" / take_name
    take.mkdir()
    # Low-level tone with a smooth envelope: test media, not a speech-recognition sample.
    t = np.arange(6 * 48000) / 48000
    x = 0.04 * np.sin(2 * np.pi * 220 * t) * np.minimum(1, t / .05) * np.minimum(1, (6-t)/.05)
    sf.write(take / "audio.wav", x, 48000, subtype="PCM_16")
    P.write_json(take / "take.json", {"eyeline": 2, "take": {"number": 1, "duration": 6, "audio": "audio.wav", "sampleRate": 48000}, "attempts": [], "sentences": [], "roughCut": [{"start": .5, "end": 5.5}], "words": [], "health": {}})
    camera = root / "01-camera" / "demo-camera.mp4"
    subprocess.run([P.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=960x540:rate={P.FPS_RATE}:duration=6", "-i", str(take / "audio.wav"), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(camera)], check=True)
    import shutil
    shutil.copyfile(camera, recording / "edit/proxies/take01.mp4")
    P.write_json(recording / "edit/footage.json", {"clips": [{"name": camera.name, "size": camera.stat().st_size, "duration": 6}]})
    P.write_json(recording / "edit/sync/take01.json", {"cam": camera.name, "offset": {"a": 0, "b": 0}, "maps": []})
    plan = [{"take": "take01", "cam": camera.name, "cutIn": a, "cutOut": b, "camOffset": 0, "text": text, "chapter": "Synthetic demo"} for a,b,text in [(.5,2.5,"First source interval (test tone)."),(3.5,5.5,"Second source interval after an intentional gap.")]]
    proj = P.Project(recording)
    plan = proj.save_plan(plan)
    P.write_json(recording / "edit/plan.original.json", plan)
    proj.relink(root / "01-camera")
    print("Open with: uv run apps/eyeline-edit/edit_server.py", str(recording))
    return root

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", default=str(ROOT / ".local/demo"))
    args = parser.parse_args()
    build(args.destination)
