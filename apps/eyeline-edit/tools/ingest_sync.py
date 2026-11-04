# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "scipy"]
# ///
"""Sync an Eyeline take's mic audio to its camera clip. Writes edit/sync/<take>.json.

    uv run tools/ingest_sync.py <project> <take folder name> <camera clip name> <camera audio wav>

camera time = take time + a*t + b. The offset is measured by cross-correlating the two recordings in windows
along the whole take (to about 1 ms), checked against Eyeline's sync chirps, and fitted with a line (drift).
"""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt, fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project as P

proj, take_dir, cam_name, cam_wav = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
take_path = next(t for t in (proj / "takes").iterdir() if t.name == take_dir)
key = P.take_key(take_dir)
mic, r1 = sf.read(take_path / "audio.wav", dtype="float32")
cam, r2 = sf.read(cam_wav, dtype="float32")
mic = mic if mic.ndim == 1 else mic.mean(1)
cam = cam if cam.ndim == 1 else cam.mean(1)
assert r1 == r2 == 48000, (r1, r2)
R = 48000
sos = butter(4, [200, 4000], "bandpass", fs=R, output="sos")
mic_f, cam_f = sosfiltfilt(sos, mic), sosfiltfilt(sos, cam)

def env(x, hop):
    n = len(x) // hop
    return np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1))

def xcorr_lag(a, b):
    """Lag L (in samples) maximising sum a[t] * b[t + L]."""
    a = (a - a.mean()) / (a.std() + 1e-9); b = (b - b.mean()) / (b.std() + 1e-9)
    c = fftconvolve(b, a[::-1], mode="full")
    i = int(np.argmax(c)); return i - (len(a) - 1), float(c[i] / len(a))

# 1. coarse: envelope at 100 Hz over the whole take
lag, corr = xcorr_lag(env(mic_f, 480), env(cam_f, 480))
coarse = lag / 100.0
print(f"coarse offset {coarse:+.2f} s (corr {corr:.2f})")

# 2. fine: 1 kHz log envelopes (robust to the camera mic's room sound), 10 s windows every 20 s,
#    searched within +-0.4 s of the coarse offset, sub-millisecond peak refine, line fit with outliers dropped
lm = np.log(env(mic_f, 48) + 1e-5); lc = np.log(env(cam_f, 48) + 1e-5)
pts = []
for t in np.arange(5, len(mic) / R - 15, 20):
    i0, i1 = int(t * 1000), int((t + 10) * 1000); a = lm[i0:i1]
    if a.std() < 0.5:
        continue
    j0 = i0 + int((coarse - 0.4) * 1000); j1 = i1 + int((coarse + 0.4) * 1000)
    if j0 < 0 or j1 > len(lc):
        continue
    b = lc[j0:j1]; a2 = (a - a.mean()) / a.std()
    cc = fftconvolve(b, a2[::-1], "valid")
    loc = np.array([b[k:k + len(a)].std() for k in range(len(cc))])
    cc = cc / (loc * len(a) + 1e-9); k = int(np.argmax(cc))
    d = 0.5 * (cc[k - 1] - cc[k + 1]) / (cc[k - 1] - 2 * cc[k] + cc[k + 1]) if 0 < k < len(cc) - 1 else 0
    pts.append((t + 5, (j0 + k + d - i0) / 1000, float(cc[k])))
pts = np.array(pts).reshape(-1, 3)
good = pts[pts[:, 2] > 0.5]
for _ in range(4):
    if len(good) < 2:
        break
    a_, b_ = np.polyfit(good[:, 0], good[:, 1], 1)
    res = good[:, 1] - (a_ * good[:, 0] + b_)
    keep = good[np.abs(res) < max(0.004, 3 * np.std(res))]
    if len(keep) < 2:
        break
    good = keep
if len(good) >= 2:
    a_, b_ = np.polyfit(good[:, 0], good[:, 1], 1)
    res_ms = np.abs(good[:, 1] - (a_ * good[:, 0] + b_)) * 1000
    print(f"fine: {len(good)}/{len(pts)} windows, offset {b_:+.4f} s, drift {a_ * 3600 * 1000:+.1f} ms/hour, "
          f"residual max {res_ms.max():.1f} ms, median {np.median(res_ms):.2f} ms")
else:   # take too short (under about 25 s) or too quiet for the windowed fit: keep the coarse offset, no drift
    a_, b_ = 0.0, coarse
    res_ms = np.array([0.0])
    print(f"fine: not enough clear windows ({len(good)}/{len(pts)}); using the coarse offset {b_:+.2f} s (about 10 ms). "
          "Check lip sync in the editor.")

# 3. check against the chirps Eyeline logged (2 kHz tone through the Mac speaker)
tj = P.read_json(take_path / "take.json", {})
chirps = (tj.get("health") or {}).get("chirps") or []
sos2 = butter(4, [1900, 2100], "bandpass", fs=R, output="sos")
chk = []
for c in chirps:
    exp = c + b_ + a_ * c
    j0, j1 = int((exp - 0.5) * R), int((exp + 0.5) * R)
    if j0 < 0 or j1 > len(cam):
        continue
    e = env(sosfiltfilt(sos2, cam[j0:j1]), 48)   # 1 ms hops
    i = int(np.argmax(e)); k0 = max(0, i - 200)
    onset = (j0 + (k0 + int(np.argmax(e[k0:i + 1] > e[i] * 0.5))) * 48) / R
    em = env(sosfiltfilt(sos2, mic[max(0, int((c - 0.3) * R)):int((c + 0.5) * R)]), 48)
    im = int(np.argmax(em)); m0 = max(0, im - 200)
    exp = max(0, c - 0.3) + (m0 + int(np.argmax(em[m0:im + 1] > em[im] * 0.5))) / 1000
    exp = exp + b_ + a_ * exp
    chk.append({"mic": c, "camExpected": round(exp, 4), "camFound": round(onset, 4), "diffMs": round((onset - exp) * 1000, 1)})
print("chirps:", chk)

out = {"cam": cam_name,
       "offset": {"a": a_, "b": b_, "meaning": "camera time = take time + a*t + b"},
       "maps": [],
       "check": {"windows": len(good), "coarseOnly": len(good) < 2, "residualMaxMs": round(float(res_ms.max()), 2), "chirps": chk,
                 "method": "1 kHz log-envelope cross-correlation, 10 s windows every 20 s, linear fit; chirp onsets as a check"},
       "createdBy": "tools/ingest_sync.py", "created": P.now_iso()}
(proj / "edit" / "sync").mkdir(parents=True, exist_ok=True)
P.write_json(proj / "edit" / "sync" / f"{key}.json", out)
print("wrote", proj / "edit" / "sync" / f"{key}.json")
