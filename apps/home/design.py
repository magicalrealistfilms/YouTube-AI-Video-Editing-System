"""Design & animate, for Eyeline Home: where a project's boards, brief and timeline live, what the final cut
exported, ready-to-paste prompts, and the board timeline. Rendering itself is tools/render_boards.py."""
import hashlib, os, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "apps" / "eyeline-edit"))
sys.path.insert(0, str(REPO / "tools"))
import project as P
from render_boards import validate

TEMPLATES = REPO / "templates"
STARTERS = {"Blank board": TEMPLATES / "board" / "index.html",
            **{f.stem.split("-", 1)[1].capitalize(): f for f in sorted((TEMPLATES / "design" / "boards").glob("*.html"))}}
CANVAS = (1920, 1080)


def pid(path):
    """Short id naming a project in preview URLs."""
    return hashlib.sha1(str(path).encode()).hexdigest()[:10]


def folders(path):
    """Boards, animation and brief: inside a teleprompter project, or the numbered folders next to a project
    made by tools/init_project.py (04-boards/, 05-animation/, 03-design-brief/)."""
    up = path.parent
    boards = up / "04-boards" if (up / "04-boards").is_dir() else path / "boards"
    animation = up / "05-animation" if (up / "05-animation").is_dir() else path / "animation"
    brief = (up / "03-design-brief" if (up / "03-design-brief").is_dir() else path) / "design-brief.md"
    return boards, animation, brief


def exports(path):
    """Files the editor exported for the final cut: video, WAV, transcript, word timings, captions."""
    name, _ = P.identity(path)
    d = P.renders_dir_for(path)
    base = d / f"{name} - final cut"
    if not Path(f"{base} words.tsv").exists() and d.is_dir():
        newest = sorted(d.glob("* words.tsv"), key=lambda f: f.stat().st_mtime, reverse=True)
        if newest:
            base = d / newest[0].name[: -len(" words.tsv")]
    files = {"video": Path(f"{base}.mp4"), "wav": Path(f"{base}.wav"), "script": Path(f"{base} script.txt"),
             "words": Path(f"{base} words.tsv"), "captions": Path(f"{base} subtitles.srt"),
             "boards": d / f"{name} - boards.mp4"}
    return d, {k: (str(v) if v.exists() else None) for k, v in files.items()}, files


def words(path):
    """Final-cut word timings [[start, end, word], ...] from the exported transcript."""
    f = exports(path)[2]["words"]
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines()[1:]:
        r = line.split("\t")
        if len(r) >= 3:
            try:
                out.append([float(r[0]), float(r[1]), r[2]])
            except ValueError:
                pass
    return out


def cut_duration(path):
    plan = P.read_json(path / "edit" / "plan.json", []) or []
    total = sum(c.get("dur", 0) for c in plan)
    ws = words(path)
    return round(max(total, ws[-1][1] if ws else 0), 3)


def boards(path):
    d = folders(path)[0]
    return sorted(f.name for f in d.glob("*.html")) if d.is_dir() else []


def timeline_file(path):
    return folders(path)[1] / "timeline.json"


def timeline(path):
    """The saved timeline, scenes naming boards by file name in the boards folder."""
    boards_dir, anim, _ = folders(path)
    t = P.read_json(timeline_file(path))
    if not isinstance(t, dict):
        return None
    scenes = []
    for s in t.get("scenes", []):
        f = (anim / s.get("file", "")).resolve()
        scenes.append({"board": f.name if f.parent == boards_dir.resolve() else s.get("file", ""),
                       "start": s.get("start"), "end": s.get("end")})
    return {"scenes": scenes, "duration": t.get("duration")}


def save_timeline(path, scenes):
    """Validate and write the timeline; raises ValueError with a readable reason."""
    boards_dir, anim, _ = folders(path)
    have = set(boards(path))
    duration = cut_duration(path)
    if duration <= 0:
        raise ValueError("The cut has no length yet. Export the final cut and its transcript first.")
    out = []
    for i, s in enumerate(scenes, 1):
        name = str(s.get("board", ""))
        if name not in have:
            raise ValueError(f"Scene {i}: choose a board from the boards folder.")
        try:
            a, b = round(float(s["start"]), 3), round(float(s["end"]), 3)
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Scene {i}: start and end must be numbers of seconds.")
        if not 0 <= a < b:
            raise ValueError(f"Scene {i}: the end must come after the start.")
        if b > duration + 0.001:
            raise ValueError(f"Scene {i}: ends at {b:.2f} s, after the cut ends ({duration:.2f} s).")
        out.append({"start": a, "end": min(b, duration), "file": os.path.relpath(boards_dir / name, anim).replace(os.sep, "/")})
    out.sort(key=lambda s: s["start"])
    for x, y in zip(out, out[1:]):
        if y["start"] < x["end"]:
            raise ValueError(f"Two scenes overlap at {y['start']:.2f} s. A board must end before the next starts.")
    t = {"version": 1, "width": CANVAS[0], "height": CANVAS[1], "fps": P.FPS_RATE, "duration": duration, "scenes": out}
    anim.mkdir(parents=True, exist_ok=True)              # before validating: board paths go through this folder
    validate(t, anim)
    P.write_json(timeline_file(path), t)
    return t


def add_starter(path, label):
    src = STARTERS.get(label)
    if not src:
        raise ValueError("Unknown starter board.")
    d = folders(path)[0]; d.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    n = 1
    while (d / f"{n:02d}-{stem}.html").exists() or any(f.name.startswith(f"{n:02d}-") for f in d.glob("*.html")):
        n += 1
    target = d / f"{n:02d}-{stem}.html"
    shutil.copyfile(src, target)
    return target.name


def brief(path):
    """The project's design brief, created from the template with the export paths filled in."""
    f = folders(path)[2]
    if not f.exists():
        _, have, _ = exports(path)
        text = (TEMPLATES / "design-brief.md").read_text(encoding="utf-8")
        text = text.replace("Approved final WAV, transcript, and word-timing paths: TODO.",
                            f"Approved final WAV, transcript, and word-timing paths: {have['wav'] or 'TODO'}; "
                            f"{have['script'] or 'TODO'}; {have['words'] or 'TODO'}.")
        text = re.sub(r"\]\((design/[^)]*)\)", lambda m: f"]({(TEMPLATES / m.group(1)).as_posix()})", text)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return f


def transcript_with_times(path):
    """The final cut's words as timed lines (about one line per 12 words or pause), for prompts."""
    ws = words(path)
    lines, cur = [], []
    for i, (a, b, w) in enumerate(ws):
        cur.append((a, b, w))
        pause = i + 1 < len(ws) and ws[i + 1][0] - b > 0.6
        if len(cur) >= 12 or pause or w.endswith((".", "?", "!")) or i + 1 == len(ws):
            lines.append(f"[{cur[0][0]:7.2f} – {cur[-1][1]:7.2f}] " + " ".join(x[2] for x in cur)); cur = []
    return "\n".join(lines)


def prompt(path, kind):
    """Ready-to-paste text for Claude: 'brief' plans the boards; 'design' makes them."""
    name, _ = P.identity(path)
    timed = transcript_with_times(path) or "(no final-cut transcript yet: export it from the editor first)"
    if kind == "brief":
        head = (TEMPLATES / "design" / "prompts" / "transcript-to-brief.md").read_text(encoding="utf-8")
        form = (TEMPLATES / "design-brief.md").read_text(encoding="utf-8")
        return (f"{head}\n\n---\nVideo: {name}\nCanvas: {CANVAS[0]} × {CANVAS[1]}, {P.FPS_RATE} fps. "
                f"Final-cut length: {cut_duration(path):.2f} s. Timestamps below are seconds on the final cut.\n\n"
                f"## Approved final-cut transcript\n\n{timed}\n\n## Brief form to fill in\n\n{form}")
    head = (TEMPLATES / "claude-design-prompt.md").read_text(encoding="utf-8")
    b = folders(path)[2]
    brief_text = b.read_text(encoding="utf-8") if b.exists() else "(no design brief yet)"
    return (f"{head}\n\n---\nVideo: {name}\nCanvas: {CANVAS[0]} × {CANVAS[1]}. Each board is one self-contained HTML file "
            f"exposing window.seek(seconds).\n\n## Design brief\n\n{brief_text}\n\n## Approved final-cut transcript\n\n{timed}")


def info(path):
    d, have, _ = exports(path)
    boards_dir, anim, brief_file = folders(path)
    return {"exportsDir": str(d), "exports": have, "duration": cut_duration(path), "words": words(path),
            "boardsDir": str(boards_dir), "boards": boards(path), "starters": list(STARTERS),
            "brief": brief_file.exists(), "timeline": timeline(path), "fps": P.FPS_RATE, "pid": pid(path)}
