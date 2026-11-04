"""Eyeline Edit: the project model shared by the server and the renderer. Runs on macOS and Windows.

A project is an Eyeline project folder (Projects/<name>/). Eyeline owns the recording files; this app owns
everything under edit/. Machine-specific things (where the camera files are on this computer, caches,
renders) live outside the project in ~/.eyeline-edit, so the shared folder never holds a path from one
machine that is wrong on another.

    Projects/<name>/
      takes/Take NN · date/audio.wav, take.json      (Eyeline)
      edit/plan.json            the cut (one entry per clip)
      edit/plan.original.json   the agent's cut, for "reset"
      edit/footage.json         camera clips: name, size, duration
      edit/sync/<take>.json     camera clip, offset, and word-matched maps where the Mac audio dropped
      edit/words/<take>.tsv     word timings (start, end, word)
      edit/proxies/<take>.mp4   1080p previews on the take's own clock
      edit/sprites/<take>/NNN.jpg   timeline thumbnails, 1 per second, 10x10 tiles
      edit/flags.json           QA notes per clip
      edit/history/             every save
      messages/NNNN-*.md        notes between recording and edit
"""
import hashlib, json, os, platform, re, shutil, subprocess, sys, tempfile, time
from fractions import Fraction
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# The project frame rate: the cut, proxies, export and frame counts all use it. Change it here only.
# Plans store frame counts and frame-aligned times, so a plan made at another rate must be re-snapped.
FPS_RATE = "25"                     # as ffmpeg writes it, e.g. "25" or "24000/1001"
_rate = Fraction(FPS_RATE)
FPS = float(_rate)
SAMPLE_RATE = 48000
assert (SAMPLE_RATE / _rate).denominator == 1, f"{FPS_RATE} fps needs a whole number of {SAMPLE_RATE} Hz samples per frame"
SPF = int(SAMPLE_RATE / _rate)      # audio samples per video frame: 1920 at 25 fps
VIDEO_TIMESCALE = _rate.numerator * (1000 if _rate.denominator == 1 else 1)   # 25000 at 25 fps
GOP = round(2 * FPS)                # keyframe every two seconds
HOME = Path(os.environ.get("EYELINE_EDIT_HOME", Path.home() / ".eyeline-edit")).expanduser()
HOME.mkdir(parents=True, exist_ok=True)
CONFIG = HOME / "config.json"


# ---------- small helpers ----------
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_atomic(path, data):
    """Write to a temp file in the same folder, then rename: a synced folder never sees a half-written file."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    with os.fdopen(fd, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
    os.chmod(tmp, 0o644)        # temp files are private by default; these are shared project files
    os.replace(tmp, path)


def write_json(path, obj):
    write_atomic(path, json.dumps(obj, indent=1))


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def line_key(text):
    """Stable id for a script line, from its words (not its position), so script edits and pickup scripts
    still point at the same line."""
    norm = " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())
    return "s-" + hashlib.sha1(norm.encode()).hexdigest()[:6]


def take_key(folder_name):
    m = re.match(r"Take (\d+)", folder_name)
    return f"take{int(m.group(1)):02d}" if m else None


def reveal(path):
    path = str(path)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", path])
    elif os.name == "nt":
        subprocess.run(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.run(["xdg-open", str(Path(path).parent)])


# ---------- ffmpeg and the video encoder ----------
_ffmpeg = None
def ffmpeg():
    """ffmpeg from the imageio-ffmpeg package (installed with the app, works on Windows), else the system one."""
    global _ffmpeg
    if _ffmpeg is None:
        try:
            import imageio_ffmpeg
            _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            _ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    return _ffmpeg


_encoder = None
def video_encoder():
    """The best encoder this machine can actually use, tested with a one-second encode.
    Mac: Apple's hardware HEVC. Windows: NVIDIA, Intel or AMD hardware; else software H.264."""
    global _encoder
    if _encoder:
        return _encoder
    options = [
        ("hevc_videotoolbox", ["-c:v", "hevc_videotoolbox", "-b:v", "20M", "-tag:v", "hvc1"]),
        ("hevc_nvenc", ["-c:v", "hevc_nvenc", "-preset", "p5", "-b:v", "20M", "-tag:v", "hvc1"]),
        ("hevc_qsv", ["-c:v", "hevc_qsv", "-b:v", "20M", "-tag:v", "hvc1"]),
        ("hevc_amf", ["-c:v", "hevc_amf", "-b:v", "20M", "-tag:v", "hvc1"]),
        ("libx264", ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]),
    ]
    for name, args in options:
        r = subprocess.run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=1:r=24", "-pix_fmt", "yuv420p"]
                           + args + ["-f", "null", "-"], capture_output=True)
        if r.returncode == 0:
            _encoder = (name, args)
            return _encoder
    _encoder = ("libx264", ["-c:v", "libx264", "-preset", "fast", "-crf", "16"])
    return _encoder


# ---------- machine config (where things are on this computer) ----------
def config():
    return read_json(CONFIG, {"projects": {}, "recent": []})


def save_config(cfg):
    write_json(CONFIG, cfg)


# ---------- the project ----------
def identity(path):
    """A project's display name and its id on this computer (keys its cache and local settings)."""
    meta = read_json(Path(path) / "project.json", {})
    name = meta.get("name") or Path(path).name
    return name, hashlib.sha1(f"{name}|{meta.get('created', '')}".encode()).hexdigest()[:12]


def renders_dir_for(path):
    """Where exports of this project go on this computer. Reads only; Project.renders_dir creates it."""
    name, pid = identity(path)
    d = config()["projects"].get(pid, {}).get("rendersDir")
    return Path(d) if d else Path.home() / ("Videos" if os.name == "nt" else "Movies") / "Eyeline Edit" / name


class Project:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        if not (self.path / "takes").is_dir():
            raise ValueError(f"Not an Eyeline project (no takes folder): {self.path}")
        self.edit = self.path / "edit"
        self.edit.mkdir(exist_ok=True)
        (self.edit / "history").mkdir(exist_ok=True)
        (self.path / "messages").mkdir(exist_ok=True)
        self.name, self.id = identity(self.path)
        self.cache = HOME / "cache" / self.id
        self.cache.mkdir(parents=True, exist_ok=True)
        self.takes = {}                                   # take04 -> folder
        for f in sorted((self.path / "takes").glob("Take *")):
            k = take_key(f.name)
            if k and (f / "audio.wav").exists():
                self.takes[k] = f
        self.footage = read_json(self.edit / "footage.json", {"clips": []})["clips"]
        cfg = config()
        cfg["recent"] = [str(self.path)] + [p for p in cfg.get("recent", []) if p != str(self.path)][:9]
        save_config(cfg)

    # where this computer keeps things for this project
    def local(self):
        return config()["projects"].get(self.id, {"footage": {}, "footageDirs": []})

    def save_local(self, data):
        cfg = config(); cfg["projects"][self.id] = data; save_config(cfg)

    def renders_dir(self):
        d = renders_dir_for(self.path)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- camera files (relinking) ----
    def clip_path(self, name):
        """Where camera clip `name` (e.g. C0002.MP4) is on this computer, or None."""
        loc = self.local()
        want = next((c for c in self.footage if c["name"].lower() == name.lower()), None)
        p = loc["footage"].get(name)
        if p and Path(p).exists() and (not want or Path(p).stat().st_size == want["size"]):
            return Path(p)
        for d in loc.get("footageDirs", []):
            hit = self._find(Path(d), name, want)
            if hit:
                loc["footage"][name] = str(hit); self.save_local(loc)
                return hit
        return None

    @staticmethod
    def _find(root, name, want):
        if not root.is_dir():
            return None
        for p in root.rglob("*"):
            if p.name.lower() == name.lower() and p.is_file() and (not want or p.stat().st_size == want["size"]):
                return p
        return None

    def relink(self, folder):
        """Look for every camera clip under `folder`; remember the folder for next time."""
        loc = self.local()
        folder = str(Path(folder).expanduser())
        if folder not in loc["footageDirs"]:
            loc["footageDirs"].insert(0, folder)
        found = {}
        for c in self.footage:
            hit = self._find(Path(folder), c["name"], c)
            if hit:
                loc["footage"][c["name"]] = str(hit); found[c["name"]] = str(hit)
        self.save_local(loc)
        return found

    def missing_footage(self, plan=None):
        names = sorted({c["cam"] for c in plan}) if plan else [c["name"] for c in self.footage]
        return [n for n in names if not self.clip_path(n)]

    # ---- per-take data ----
    def take_audio(self, take):
        return self.takes[take] / "audio.wav"

    def take_json(self, take):
        return read_json(self.takes[take] / "take.json", {})

    def words(self, take):
        f = self.edit / "words" / f"{take}.tsv"
        if not f.exists():
            return []
        rows = [l.split("\t") for l in f.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
        return [(float(r[0]), float(r[1]), r[2]) for r in rows]

    def sync(self, take):
        s = read_json(self.edit / "sync" / f"{take}.json", {})
        for m in s.get("maps", []):
            if m.get("to") is None:
                m["to"] = 1e9
        return s

    def proxy(self, take):
        return self.edit / "proxies" / f"{take}.mp4"

    # ---- the cut ----
    def plan(self):
        return read_json(self.edit / "plan.json", [])

    def save_plan(self, plan):
        cur = self.edit / "plan.json"
        if cur.exists():
            shutil.copy(cur, self.edit / "history" / f"plan.{datetime.now():%Y%m%d-%H%M%S-%f}.json")
        plan = normalize(plan, self)
        write_json(cur, plan)
        return plan

    # ---- messages between recording and edit (one new file per message, never edited) ----
    def messages(self):
        out = []
        for f in sorted((self.path / "messages").glob("[0-9][0-9][0-9][0-9]-*.md")):
            text = f.read_text(encoding="utf-8")
            head = {}
            m = re.match(r"---\n(.*?)\n---\n", text, re.S)
            if m:
                for line in m.group(1).splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1); head[k.strip()] = v.strip()
            out.append({"file": f.name, "head": head, "body": text[m.end():] if m else text})
        return out

    def send_message(self, kind, to, title, body, **fields):
        n = max([int(m["file"][:4]) for m in self.messages()] + [0]) + 1
        head = {"id": f"{n:04d}", "from": "edit", "to": to, "type": kind, "status": "open", "created": now_iso(), **fields}
        text = "---\n" + "\n".join(f"{k}: {v}" for k, v in head.items()) + f"\n---\n# {title}\n\n{body.strip()}\n"
        write_atomic(self.path / "messages" / f"{n:04d}-edit-{kind}.md", text)
        return head["id"]


# ---------- keeping the cut consistent after edits ----------
def map_for(c, sync):
    return next((m for m in sync.get("maps", []) if c["cutOut"] > m["from"] and c["cutIn"] < m["to"]), None)


def map_off(m, t):
    return float(np.interp(t, m["t"], m["offset"]))


def normalize(plan, project):
    """Recompute frames, camera starts (exact camera frame) and positions after edits.
    Clips inside a word-matched map take picture and sound from the camera (the Mac audio dropped there)."""
    out, t = [], 0.0
    syncs = {}
    for i, c in enumerate(plan):
        c = dict(c)
        s = syncs.setdefault(c["take"], project.sync(c["take"]) if project else {})
        m = map_for(c, s)
        if m:
            c0, c1 = c["cutIn"] + map_off(m, c["cutIn"]), c["cutOut"] + map_off(m, c["cutOut"])
            k = round(c0 * FPS)
            c["camStart"] = round(k / FPS, 6); c["frames"] = max(1, round((c1 - k / FPS) * FPS)); c["audioSource"] = "camera"
        else:
            off = c.get("camOffset", c.get("camStart", c["cutIn"]) - c["cutIn"])
            cam = c["cutIn"] + off
            k = round(cam * FPS); d = k / FPS - cam
            c["cutIn"] = round(c["cutIn"] + d, 4); c["camStart"] = round(k / FPS, 6); c["camOffset"] = off
            c["frames"] = max(1, round((c["cutOut"] - c["cutIn"]) * FPS))
            c["cutOut"] = round(c["cutIn"] + c["frames"] / FPS, 4)
            c.pop("audioSource", None)
        pad = round(c.get("padBefore", 0) * FPS); c["padFrames"] = pad
        c["dur"] = round((c["frames"] + pad) / FPS, 4); c["outStart"] = round(t, 4); t += c["dur"]
        c["zoom"] = 0
        c["id"] = i + 1
        out.append(c)
    return out
