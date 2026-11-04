"""Find which camera clip belongs to which take, by sound. numpy only.

A take's microphone recording and its camera clip's scratch audio hear the same voice, so their loudness
envelopes line up at one offset. Clock times on cameras are often wrong; sound is not.

camera time = take time + offset (seconds).
"""
from pathlib import Path

import numpy as np

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mxf", ".mts", ".m2ts", ".avi", ".mkv"}
RATE = 100              # envelope samples per second: about 10 ms resolution, enough to pick a clip
MIN_SCORE = 0.5         # correlation of the two envelopes at the best offset (unrelated speech scores about 0.3)
MIN_OVERLAP = 0.5       # the clip must cover at least half the take


def camera_dirs(project):
    """Where a project's camera files go: footage/ inside the Eyeline project, and 01-camera/ next to it
    when the project sits in a folder made by tools/init_project.py."""
    project = Path(project)
    dirs = [project / "footage"]
    if (project.parent / "01-camera").is_dir():
        dirs.append(project.parent / "01-camera")
    return dirs


def camera_files(project):
    out = []
    for d in camera_dirs(project):
        if d.is_dir():
            out += sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT
                          and not p.name.startswith("."))
    return out


def envelope(x, sr, rate=RATE):
    """Log loudness, `rate` values per second."""
    x = np.asarray(x, dtype=np.float64)
    x = x if x.ndim == 1 else x.mean(1)
    hop = max(1, int(sr // rate))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    return np.log(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-5)


def match_envelopes(a, b, rate=RATE, min_overlap=MIN_OVERLAP):
    """Best alignment of take envelope `a` inside camera envelope `b`.
    Returns {"offset", "score", "overlap"} or None if nothing overlaps enough."""
    if len(a) < rate or len(b) < rate or a.std() < 1e-6 or b.std() < 1e-6:
        return None
    za = (a - a.mean()) / a.std()
    zb = (b - b.mean()) / b.std()
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(zb, size) * np.conj(np.fft.rfft(za, size)), size)
    lags = np.arange(-(len(a) - 1), len(b))
    c = np.concatenate([c[size - (len(a) - 1):], c[: len(b)]]) if len(a) > 1 else c[: len(b)]
    overlap = np.minimum(len(a), len(b) - lags) - np.maximum(0, -lags)
    ok = overlap >= min_overlap * len(a)
    if not ok.any():
        return None
    k = int(np.argmax(np.where(ok, c / np.maximum(overlap, 1), -np.inf)))
    lag = int(lags[k])
    t0, t1 = max(0, -lag), min(len(a), len(b) - lag)
    sa, sb = a[t0:t1], b[t0 + lag:t1 + lag]
    score = float(np.corrcoef(sa, sb)[0, 1]) if sa.std() > 1e-6 and sb.std() > 1e-6 else 0.0
    return {"offset": round(lag / rate, 3), "score": round(score, 3), "overlap": round((t1 - t0) / len(a), 3)}


def best_clip(take_env, clip_envs, rate=RATE):
    """Pick the camera clip for one take. clip_envs: {name: envelope}.
    Returns (name or None, candidates sorted best first)."""
    found = []
    for name, env in clip_envs.items():
        m = match_envelopes(take_env, env, rate)
        if m:
            found.append(dict(m, cam=name))
    found.sort(key=lambda m: m["score"], reverse=True)
    best = found[0] if found and found[0]["score"] >= MIN_SCORE else None
    return (best["cam"] if best else None), found
