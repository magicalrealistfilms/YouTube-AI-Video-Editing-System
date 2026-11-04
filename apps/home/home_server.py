# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "imageio-ffmpeg"]
# ///
"""Eyeline Home: one page to record, prepare and edit, without typing commands.

    uv run apps/home/home_server.py [port] [--no-browser]      then open http://localhost:5300

Lists your projects, starts the teleprompter and the editor when you need them, prepares takes for
editing (camera match, transcript, sync, previews), makes a draft cut, and helps design, time and render
the boards. Local only (127.0.0.1). Closing it stops the teleprompter and editor it started.

Board previews and the board library are served read-only from a second port (5301 by default), so a
board's own scripts cannot reach this page's controls.
"""
import atexit, json, os, shutil, signal, socket, subprocess, sys, threading, time, urllib.request, webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import soundfile as sf

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EDIT = REPO / "apps" / "eyeline-edit"
sys.path.insert(0, str(EDIT))
import camera_match as M
import project as P
import design as D

PORT = next((int(a) for a in sys.argv[1:] if a.isdigit()), 5300)
TELEPROMPTER, EDITOR = 5317, 5320
PREVIEW = PORT + 1
DATA = Path(os.environ.get("EYELINE_DATA", Path.home() / "Eyeline")).expanduser()
LOGS = P.HOME / "logs"; LOGS.mkdir(parents=True, exist_ok=True)

children = {}            # "teleprompter" / "editor" -> Popen we started
job = {"kind": None, "project": None, "running": False, "log": "", "progress": None, "error": None, "finished": None}
job_lock = threading.Lock()


# ---------- projects ----------
def project_paths():
    """Teleprompter projects (EYELINE_DATA/Projects) plus folders recently opened in the editor."""
    seen, out = set(), []
    roots = sorted((DATA / "Projects").iterdir()) if (DATA / "Projects").is_dir() else []
    for p in roots + [Path(r) for r in P.config().get("recent", [])]:
        try:
            r = p.resolve()
        except OSError:
            continue
        if r not in seen and (r / "takes").is_dir() and not r.name.startswith("."):
            seen.add(r); out.append(r)
    return out


def known(path):
    """Only act on a folder that is in the project list: the page never names arbitrary paths."""
    try:
        r = Path(path).resolve()
    except (OSError, TypeError):
        return None
    return r if r in project_paths() else None


def mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return 0


def project_info(path):
    edit = path / "edit"
    meta = P.read_json(path / "project.json", {})
    match = P.read_json(edit / "camera-match.json", {}).get("takes", {})
    prep = P.read_json(edit / "prepare.json", {}).get("takes", {})
    takes = []
    for f in sorted((path / "takes").glob("Take *")):
        key = P.take_key(f.name)
        audio = f / "audio.wav"
        if not key or not audio.exists():
            continue
        try:
            duration = round(sf.info(str(audio)).duration, 1)
        except RuntimeError:
            duration = None
        m = match.get(key, {}); best = (m.get("candidates") or [None])[0]
        words, sync, proxy = edit / "words" / f"{key}.tsv", edit / "sync" / f"{key}.json", edit / "proxies" / f"{key}.mp4"
        takes.append({"key": key, "folder": f.name, "duration": duration,
                      "matched": key in match, "camera": m.get("cam"), "score": best["score"] if best and m.get("cam") else None,
                      "transcribed": mtime(words) >= mtime(audio) > 0,
                      "synced": sync.exists(), "coarseSync": bool(P.read_json(sync, {}).get("check", {}).get("coarseOnly")),
                      "preview": proxy.exists() and mtime(proxy) >= mtime(sync),
                      "errors": prep.get(key, {}).get("errors", [])})
    clips = M.camera_files(path)
    plan, draft = edit / "plan.json", edit / "plan.candidate.json"
    plan_clips = len(P.read_json(plan, []) or [])
    return {"name": meta.get("name") or path.name, "path": str(path), "modified": max([mtime(path)] + [mtime(path / "takes" / t["folder"]) for t in takes]),
            "takes": takes, "cameraFiles": [c.name for c in clips],
            "cameraDir": str(M.camera_dirs(path)[-1]),     # 01-camera/ next to a scaffolded project, else footage/
            "hasScriptMap": (path / "edit-plan.json").exists(),
            "planClips": plan_clips, "draft": draft.exists() and (not plan.exists() or mtime(draft) > mtime(plan)),
            "draftClips": len(P.read_json(draft, []) or []) if draft.exists() else 0}


# ---------- the teleprompter and the editor ----------
def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if port_open(port):
            return True
        time.sleep(0.25)
    return False


def start(name, cmd, cwd, port, seconds):
    if port_open(port):
        return True
    log = open(LOGS / f"{name}.log", "w")
    children[name] = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    return wait_port(port, seconds)


def open_browser(url, prefer_chrome=False):
    """The teleprompter's voice following works best in Chrome or Edge, so prefer them on a Mac."""
    if sys.platform == "darwin" and prefer_chrome:
        for app in ("Google Chrome", "Microsoft Edge"):
            if Path("/Applications", app + ".app").exists():
                subprocess.run(["open", "-a", app, url], check=False)
                return
    webbrowser.open(url)


def editor_open(path):
    """Show `path` in the editor, starting it if needed; an editor that is already running switches project."""
    if port_open(EDITOR):
        req = urllib.request.Request(f"http://127.0.0.1:{EDITOR}/api/open", data=json.dumps({"path": str(path)}).encode(), method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()
        return True
    return start("editor", [sys.executable, str(EDIT / "edit_server.py"), str(path)], EDIT, EDITOR, 180)


def reveal(target, text_editor=False):
    """Show a folder in Finder/Explorer, or open a text file in the default text editor."""
    target = str(target)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-t", target] if text_editor else ["open", target], check=False)
        elif os.name == "nt":
            os.startfile(target)                               # the Windows file association
        else:
            subprocess.run(["xdg-open", target], check=False)
        return True
    except OSError:
        return False


@atexit.register
def stop_children():
    for p in children.values():
        if p.poll() is None:
            p.terminate()


# ---------- background jobs: prepare, draft cut ----------
def uv_script(script, *argv):
    uv = shutil.which("uv")
    return ([uv, "run", "--script"] if uv else [sys.executable]) + [str(script), *map(str, argv)]


def run_job(kind, path, cmd, env=None):
    """Run one command, or a list of commands one after another, in the background."""
    cmds = cmd if isinstance(cmd[0], list) else [cmd]
    with job_lock:
        if job["running"]:
            return False
        job.update(kind=kind, project=str(path), running=True, log="", progress=None, error=None, finished=None)
    def work():
        try:
            for c in cmds:
                p = subprocess.Popen(c, cwd=EDIT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=dict(os.environ, **(env or {})))
                for line in p.stdout:
                    if "UV_NATIVE_TLS" in line:
                        continue
                    if line.startswith("@progress "):
                        try:
                            job["progress"] = json.loads(line[10:])
                        except ValueError:
                            pass
                        continue
                    job["log"] = (job["log"] + line)[-20000:]
                p.wait()
                if p.returncode != 0:
                    break
            job["error"] = None if p.returncode == 0 else "Finished, but something went wrong. The problems are listed above; Details has the full log."
        except OSError as e:
            job["error"] = str(e)
        job.update(running=False, finished=time.time())
    threading.Thread(target=work, daemon=True).start()
    return True


def draft_takes(path):
    """Takes the draft cut can use: transcribed, synced to a camera clip, with a preview."""
    return [t["key"] for t in project_info(path)["takes"] if t["transcribed"] and t["synced"] and t["preview"]]


# ---------- HTTP ----------
class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def js(self, obj, status=200):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def local_host(self):
        return urlparse("http://" + self.headers.get("Host", "")).hostname in ("localhost", "127.0.0.1", "::1")

    def do_GET(self):
        if not self.local_host():
            return self.send_error(403)
        u = urlparse(self.path)
        if u.path == "/api/state":
            return self.js({"projects": sorted((project_info(p) for p in project_paths()), key=lambda x: -x["modified"]),
                            "dataFolder": str(DATA / "Projects"),
                            "teleprompter": port_open(TELEPROMPTER), "editor": port_open(EDITOR)})
        if u.path == "/api/job":
            return self.js(job)
        if u.path in ("/api/design", "/api/prompt"):
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            path = known(q.get("project"))
            if not path:
                return self.js({"error": "Unknown project. Reload the page."}, 404)
            if u.path == "/api/prompt":
                return self.js({"text": D.prompt(path, q.get("kind", "design"))})
            return self.js(dict(D.info(path), preview=f"http://localhost:{PREVIEW}"))
        if u.path in ("/", "/index.html"):
            return super().do_GET()
        return self.send_error(404)

    def do_POST(self):
        # Writes start programs, so: this computer only, same page only, and a header other sites cannot send.
        origin = self.headers.get("Origin")
        if not self.local_host() or (origin and origin != "http://" + self.headers.get("Host", "")) or self.headers.get("X-Eyeline") != "1":
            return self.send_error(403)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.js({"error": "invalid JSON"}, 400)
        u = urlparse(self.path)
        if u.path == "/api/teleprompter":
            if not start("teleprompter", [sys.executable, str(REPO / "apps" / "teleprompter" / "server.py")], REPO / "apps" / "teleprompter", TELEPROMPTER, 20):
                return self.js({"error": f"The teleprompter did not start. See {LOGS / 'teleprompter.log'}"}, 500)
            open_browser(f"http://localhost:{TELEPROMPTER}/", prefer_chrome=True)
            return self.js({"ok": True})
        path = known(data.get("project"))
        if not path:
            return self.js({"error": "Unknown project. Reload the page."}, 404)
        if u.path == "/api/reveal":
            what = data.get("what")
            boards_dir, anim, _ = D.folders(path)
            target = {"camera": Path(project_info(path)["cameraDir"]), "boards": boards_dir, "animation": anim,
                      "exports": D.exports(path)[0]}.get(what, path)
            target.mkdir(parents=True, exist_ok=True)
            return self.js({"ok": True}) if reveal(target) else self.js({"error": f"Open this folder yourself: {target}"}, 500)
        if u.path == "/api/brief":
            f = D.brief(path)
            return self.js({"ok": True}) if reveal(f, text_editor=True) else self.js({"error": f"Open this file in a text editor: {f}"}, 500)
        if u.path == "/api/starter":
            try:
                return self.js({"ok": True, "board": D.add_starter(path, data.get("name"))})
            except ValueError as e:
                return self.js({"error": str(e)}, 400)
        if u.path == "/api/timeline":
            try:
                t = D.save_timeline(path, data.get("scenes") or [])
            except (ValueError, KeyError, TypeError) as e:
                return self.js({"error": str(e)}, 400)
            return self.js({"ok": True, "scenes": len(t["scenes"])})
        if u.path == "/api/render-boards":
            if not D.timeline_file(path).exists():
                return self.js({"error": "Save the timeline first."}, 409)
            out = D.exports(path)[2]["boards"]
            if out.exists():                       # the renderer never overwrites: keep one previous version
                out.replace(out.with_name(out.stem + " (previous).mp4"))
            uv = shutil.which("uv")
            install = [uv, "run", "--with", "playwright", "python", "-m", "playwright", "install", "chromium"] if uv else [sys.executable, "-m", "playwright", "install", "chromium"]
            cmd = [install, uv_script(REPO / "tools" / "render_boards.py", D.timeline_file(path), out)]
            return self.js({"ok": True, "out": str(out)}) if run_job("boards", path, cmd, env={"EYELINE_PROGRESS": "1"}) else self.js({"error": "Another job is running."}, 409)
        if u.path == "/api/prepare":
            cmd = uv_script(EDIT / "tools" / "prepare_project.py", path, *(["--redo"] if data.get("redo") else []))
            return self.js({"ok": True}) if run_job("prepare", path, cmd) else self.js({"error": "Another job is running."}, 409)
        if u.path == "/api/draft":
            if not (path / "edit-plan.json").exists():
                return self.js({"error": "No script map (edit-plan.json) in this project. Record with the teleprompter's script loaded first."}, 409)
            keys = draft_takes(path)
            if not keys:
                return self.js({"error": "No take is ready yet. Prepare the project for editing first."}, 409)
            cmd = uv_script(EDIT / "tools" / "assemble_cut.py", path, *keys)
            return self.js({"ok": True}) if run_job("draft", path, cmd) else self.js({"error": "Another job is running."}, 409)
        if u.path == "/api/use-draft":
            draft = P.read_json(path / "edit" / "plan.candidate.json")
            if not isinstance(draft, list) or not draft:
                return self.js({"error": "There is no draft cut to use."}, 409)
            if P.read_json(path / "edit" / "plan.json", []) and not data.get("replace"):
                return self.js({"error": "confirm", "message": "The editor already has a cut."}, 409)
            proj = P.Project(path)
            plan = proj.save_plan(draft)            # the previous cut is kept in edit/history/
            P.write_json(proj.edit / "plan.original.json", plan)
            if port_open(EDITOR):
                editor_open(path)
            return self.js({"ok": True, "clips": len(plan)})
        if u.path == "/api/editor":
            try:
                ok = editor_open(path)
            except OSError as e:
                return self.js({"error": f"The editor did not respond: {e}"}, 500)
            if not ok:
                return self.js({"error": f"The editor did not start. See {LOGS / 'editor.log'}"}, 500)
            open_browser(f"http://localhost:{EDITOR}/")
            return self.js({"ok": True})
        return self.send_error(404)


class Preview(SimpleHTTPRequestHandler):
    """Read-only: the board library (/library/), a project's boards (/p/<id>/), its timeline and narration
    for the timeline preview (/t/<id>/timeline.json, /a/<id>/narration.wav), and the preview page."""
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(HERE), **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)

    @staticmethod
    def project(project_id):
        return next((p for p in project_paths() if D.pid(p) == project_id), None)

    def translate_path(self, path):
        parts = unquote(urlparse(path).path).split("/")
        if parts[1:] == ["preview.html"]:
            return str(HERE / "preview.html")
        if len(parts) > 2 and parts[1] == "library":
            root, rest = D.TEMPLATES / "design", parts[2:]
        elif len(parts) > 3 and parts[1] == "p" and self.project(parts[2]):
            root, rest = D.folders(self.project(parts[2]))[0], parts[3:]
        else:
            return ""
        root = root.resolve()
        f = (root / "/".join(rest)).resolve()
        return str(f) if f == root or root in f.parents else ""

    def do_GET(self):
        if urlparse("http://" + self.headers.get("Host", "")).hostname not in ("localhost", "127.0.0.1", "::1"):
            return self.send_error(403)
        parts = urlparse(self.path).path.split("/")
        if len(parts) == 4 and parts[1] in ("t", "a"):
            path = self.project(parts[2])
            if not path:
                return self.send_error(404)
            if parts[1] == "t":
                t = D.timeline(path) or {"scenes": []}
                have = set(D.boards(path))
                wav = D.exports(path)[2]["wav"]
                body = json.dumps({"duration": D.cut_duration(path), "audio": f"/a/{parts[2]}/narration.wav" if wav.exists() else None,
                                   "scenes": [dict(s, url=f"/p/{parts[2]}/{s['board']}") for s in t["scenes"] if s["board"] in have]}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            return self.send_range(D.exports(path)[2]["wav"], "audio/wav")
        return super().do_GET()

    def send_range(self, f, ctype):
        """Serve a file with byte ranges, so the browser can seek in the narration."""
        if not f.exists():
            return self.send_error(404)
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            try:
                start, end = (int(a), min(int(b) if b else size - 1, size - 1)) if a else (max(0, size - int(b)), size - 1)
            except ValueError:
                return self.send_error(416)
            if start > end:
                return self.send_error(416)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start); left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == "__main__":
    url = f"http://localhost:{PORT}/"
    if port_open(PORT):                       # already running: just show it
        print("Eyeline Home is already running:", url)
        if "--no-browser" not in sys.argv:
            open_browser(url)
        sys.exit(0)
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):   # closing the window: stop what we started
        if sig:
            signal.signal(sig, lambda *_: sys.exit(0))
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    try:
        threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", PREVIEW), Preview).serve_forever, daemon=True).start()
    except OSError as e:
        print(f"Board previews are unavailable: port {PREVIEW} is in use ({e}).", flush=True)
    print(f"Eyeline Home: {url}\nProjects folder: {DATA / 'Projects'}\nKeep this window open while you work. Close it (or press Ctrl+C) to stop.", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, open_browser, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
