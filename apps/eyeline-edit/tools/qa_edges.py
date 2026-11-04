# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "mlx-whisper; sys_platform == 'darwin' and platform_machine == 'arm64'", "faster-whisper; sys_platform != 'darwin' or platform_machine != 'arm64'"]
# ///
"""Per-clip edge check: every clip of the QA audio transcribed on its own (padded with silence), and its
first and last words compared with what the clip should say. Writes edit/qa-edges.json.

    uv run tools/qa_edges.py <project> <qa.wav from qa_cut.py>
"""
import json, os, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from textnorm import norm
import project as P
import asr as mlx_whisper

proj = Path(sys.argv[1]); E = proj / "edit"
plan = json.loads((E / "plan.json").read_text())
x, sr = sf.read(sys.argv[2], dtype="float32")
pad = np.zeros(int(0.35 * sr), np.float32)
pos, out = 0, {}
tmp = Path(tempfile.gettempdir()) / "eyeline-edge.wav"
for c in plan:
    n = c["frames"] * P.SPF
    seg = x[pos:pos + n]; pos += n
    sf.write(tmp, np.concatenate([pad, seg, pad]), sr, subtype="PCM_16")
    r = mlx_whisper.transcribe(str(tmp), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en",
                               condition_on_previous_text=False, temperature=0.0,
                               initial_prompt="Um, so, uh, basically you guys, I mean, like, um, okay.")
    heard = norm(r["text"]); want = norm(c["text"])
    if not want:
        continue
    first_ok = bool(heard) and (heard[0] == want[0] or (len(heard) > 1 and heard[1] == want[0]))
    last_ok = bool(heard) and (heard[-1] == want[-1] or (len(heard) > 1 and heard[-2] == want[-1]))
    if not (first_ok and last_ok):
        out[str(c["id"])] = {"want": c["text"], "heard": r["text"].strip(), "first": first_ok, "last": last_ok}
tmp.unlink(missing_ok=True)
P.write_json(E / "qa-edges.json", out)
print(f"{len(plan)} clips checked one by one; {len(out)} with a first or last word that does not match")
