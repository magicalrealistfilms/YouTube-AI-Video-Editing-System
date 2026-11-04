import importlib.util, json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.request, urllib.error, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from init_project import create
from check_release import check
from render_boards import validate
from validate_examples import validate_examples

class Contracts(unittest.TestCase):
    def test_public_tree(self):
        self.assertEqual(check(), [])

    def test_examples(self):
        checked, errors = validate_examples()
        self.assertEqual(errors, [])
        self.assertTrue(checked)

    def test_scaffold_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = create(Path(d) / "Sample")
            self.assertTrue((p / "01-recording/takes").is_dir())
            self.assertTrue((p / "04-boards/assets").is_dir())
            self.assertEqual(json.loads((p / "01-recording/project.json").read_text())["name"], "Sample")
            with self.assertRaises(ValueError): create(p)

    def test_board_rejects_overlap(self):
        timeline = json.loads((ROOT / "examples/board-timeline.json").read_text())
        validate(timeline, ROOT / "examples")
        timeline["scenes"].append(dict(timeline["scenes"][0]))
        with self.assertRaises(ValueError): validate(timeline, ROOT / "examples")

class AppHTTP(unittest.TestCase):
    def request(self, route, data=None, headers=None):
        req = urllib.request.Request(self.url + route, data=json.dumps(data).encode() if data is not None else None, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r: return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e: return e.code, dict(e.headers), e.read()

    def start(self, app, project=None):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        env = dict(os.environ, EYELINE_EDIT_HOME=str(self.folder / "config"), EYELINE_DATA=str(self.folder / "data"))
        if project:
            project = create(self.folder / "Video") / "01-recording"
            take = project / "takes/Take 01 · synthetic"; take.mkdir()
            with wave.open(str(take / "audio.wav"), "wb") as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(48000); f.writeframes(b"\0" * 96000 * 3)
            self.plan = [{"id":1,"take":"take01","cam":"demo.mp4","cutIn":0.5,"cutOut":1.5,"camOffset":0,"text":"Example."}]
            self.plan_file = project / "edit/plan.json"
            self.plan_file.write_text(json.dumps(self.plan))
            (project / "edit/proxies/take01.mp4").write_bytes(b"0123456789")
        args = [sys.executable, str(ROOT / app)] + ([str(project)] if project else []) + [str(port)]
        self.proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if self.request("/")[0] == 200: return
            except OSError: pass
            time.sleep(.05)
        self.fail("Server failed to start")

    def tearDown(self):
        if hasattr(self, "proc"):
            self.proc.terminate(); self.proc.wait(timeout=5)
            self.temp.cleanup()

    def test_editor_conflict_and_validation(self):
        self.start("apps/eyeline-edit/edit_server.py", True)
        status, headers, body = self.request("/api/plan")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), self.plan)  # opening must not rewrite the plan
        rev = headers["ETag"]
        status, newheaders, body = self.request("/api/plan", self.plan, {"If-Match":rev})
        self.assertEqual(status, 200)
        saved = self.plan_file.read_bytes()
        self.assertEqual(self.request("/api/plan", self.plan, {"If-Match":rev})[0], 409)
        self.assertEqual(saved, self.plan_file.read_bytes())
        bad = [dict(self.plan[0], cutOut=20)]
        self.assertEqual(self.request("/api/plan", bad, {"If-Match":newheaders["ETag"]})[0], 400)
        self.assertEqual(self.request("/api/plan", self.plan, {"Origin":"https://example.invalid"})[0], 403)
        self.assertEqual(self.request("/api/plan", headers={"Host":"example.invalid"})[0], 403)
        status, _, body = self.request("/media/take01.mp4", headers={"Range":"bytes=-3"})
        self.assertEqual((status,body),(206,b"789"))
        self.assertEqual(self.request("/media/take01.mp4", headers={"Range":"bytes=99-"})[0], 416)

    def test_teleprompter_project_and_static_boundary(self):
        self.start("apps/teleprompter/server.py")
        self.assertEqual(self.request("/server.py")[0], 404)
        self.assertEqual(self.request("/AGENTS-project.md")[0], 404)
        status, _, body = self.request("/projects", {"name":"Sample","script":"Hello world."})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["name"], "Sample")
        self.assertEqual(self.request("/projects/Sample/script")[2], b"Hello world.")
        self.assertEqual(self.request("/projects", {}, {"Origin":"https://example.invalid"})[0], 403)
        self.assertEqual(self.request("/projects", headers={"Host":"example.invalid"})[0], 403)

if __name__ == "__main__": unittest.main()
