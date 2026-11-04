# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "imageio-ffmpeg"]
# ///
"""Preview video and timeline thumbnails for one take, on the take's own clock (proxy time = take time).
Picture from the camera clip through edit/sync/<take>.json, sound from the take's audio.wav (what exports).

    uv run tools/ingest_proxy.py <project> <take folder name> <camera clip path>
"""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project as P
import soundfile as sf

proj, take_dir, cam = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
key = P.take_key(take_dir)
wav = proj / "takes" / take_dir / "audio.wav"
dur = sf.info(str(wav)).duration
off = P.read_json(proj / "edit" / "sync" / f"{key}.json")["offset"]
a, b = off["a"], off["b"]          # camera time = take time*(1+a) + b
out = proj / "edit" / "proxies" / f"{key}.mp4"; out.parent.mkdir(parents=True, exist_ok=True)
tmp = out.with_suffix(".part.mp4")
enc = ["-c:v", "h264_videotoolbox", "-b:v", "2500k"] if sys.platform == "darwin" else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]
pre = ["-ss", f"{b:.4f}"] if b >= 0 else ["-itsoffset", f"{-b:.4f}"]
subprocess.run([P.ffmpeg(), "-v", "error", "-y", *pre, "-i", cam, "-i", str(wav),
                "-map", "0:v:0", "-map", "1:a:0", "-vf", f"setpts=(PTS-STARTPTS)/{1 + a:.9f},fps={P.FPS_RATE},scale=960:540",
                *enc, "-c:a", "aac", "-b:a", "128k", "-ac", "1", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(tmp)], check=True)
tmp.replace(out)
sp = proj / "edit" / "sprites" / key; sp.mkdir(parents=True, exist_ok=True)
subprocess.run([P.ffmpeg(), "-v", "error", "-y", "-i", str(out), "-vf", "fps=1,scale=160:90,tile=10x10", "-q:v", "4",
                str(sp / "%03d.jpg")], check=True)
print(key, "proxy", round(dur, 2), "s,", len(list(sp.glob("*.jpg"))), "sprite sheets")
