# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "soundfile", "scipy"]
# ///
"""EXPERIMENTAL candidate generator. Never publishes a cut or overwrites the active plan.
    uv run tools/assemble_cut.py PROJECT TAKE_KEY... [--keep-offscript keep.json]
Outputs candidate JSON and diagnostic picks. Acoustic boundaries and reading selection require
human audition; ASR can normalize mispronunciations and silence can precede final consonants.
This heuristic is NOT a safe unattended editor. See docs/cutting.md.
"""
import json, re, sys
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
import project as P

FPS = P.FPS
SR = P.SAMPLE_RATE
BREATH = 20         # dB over room tone below which it is a breath or silence, not speech
PAUSE = 0.18        # silence longer than this inside a reading is removed
PAD = 0.014         # room left after the last sound (the export fades 12 ms)
PAD_IN = 0.030      # room left before the first sound: onsets are detected a few ms late, plosives start soft
FILLERS = {"um", "uh", "er", "erm", "ah", "hmm", "mm", "uhm", "umm", "uhh"}
REDO = re.compile(r"\b(let me (re ?do|redo|start|try|say)|one more time|start (that|this) again|scratch that|"
                  r"hold on|sorry|again|redo|take two|from the top|wait)\b", re.I)

args = sys.argv[1:]
keep_file = None
if "--list-offscript" in args:
    args.remove("--list-offscript")
if "--keep-offscript" in args:
    i = args.index("--keep-offscript"); keep_file = Path(args[i + 1]); del args[i:i + 2]
proj = Path(args[0]); take_keys = args[1:]


from textnorm import norm


# ---------- per take: audio envelopes, words, attempts ----------
class Take:
    def __init__(self, key):
        self.key = key
        self.dir = next(t for t in (proj / "takes").iterdir() if P.take_key(t.name) == key)
        self.tj = json.loads((self.dir / "take.json").read_text())
        x, sr = sf.read(self.dir / "audio.wav", dtype="float32"); assert sr == SR
        self.x = x if x.ndim == 1 else x.mean(1)
        self.sync = P.read_json(proj / "edit" / "sync" / f"{key}.json")
        # 1 ms envelopes, 8 ms window: broadband and high band (s, f, t tails)
        def env(sig):
            win = 384; hop = 48
            p = np.convolve(sig.astype(np.float64) ** 2, np.ones(win) / win, "same")[::hop]
            return 10 * np.log10(p + 1e-12)
        self.eb = env(sosfiltfilt(butter(4, [80, 8000], "bandpass", fs=SR, output="sos"), self.x))
        self.eh = env(sosfiltfilt(butter(4, [3500, 11000], "bandpass", fs=SR, output="sos"), self.x))
        self.fb = np.percentile(self.eb, 12); self.fh = np.percentile(self.eh, 12)
        # Eyeline's sync beeps are not speech
        for ch in ((self.tj.get("health") or {}).get("chirps") or []):
            i0, i1 = max(0, int((ch - 0.1) * 1000)), int((ch + 0.4) * 1000)
            self.eb[i0:i1] = self.fb; self.eh[i0:i1] = self.fh
        self.words = []
        for r, line in enumerate((proj / "edit" / "words" / f"{key}.tsv").read_text().splitlines()[1:]):
            a, b, w, p = line.split("\t")
            for t in norm(w) or [w.lower()]:
                self.words.append({"s": float(a), "e": float(b), "w": w, "n": t, "p": float(p), "r": r})
        self.sent = {s["id"]: s["text"] for s in self.tj.get("sentences", [])}

    def loud(self, i):          # sound at 1 ms index i?
        return self.eb[i] > self.fb + 9 or self.eh[i] > self.fh + 9

    def sound_mask(self, t0, t1):
        """Speech, not breath: breaths sit 10 to 20 dB over room tone, words 30 dB and more."""
        i0, i1 = max(0, int(t0 * 1000)), min(len(self.eb), int(t1 * 1000))
        return i0, (self.eb[i0:i1] > self.fb + BREATH) | (self.eh[i0:i1] > self.fh + BREATH + 4)

    def tail(self, t, limit):
        """Follow a word's soft decay (above breath level is not needed, above room tone is) for up to 40 ms."""
        i = int(t * 1000); j = i
        while j < min(len(self.eb) - 1, i + 40, int(limit * 1000)) and self.eb[j] > self.fb + 10 and self.eb[j + 1] <= self.eb[j] + 1:
            j += 1
        return j / 1000

    def offset(self, t):
        o = self.sync["offset"]; return o["a"] * t + o["b"]


takes = {k: Take(k) for k in take_keys}
plan_lines = json.loads((proj / "edit-plan.json").read_text())["lines"]


# ---------- candidates and scores ----------
def align(tk, script_toks, a0, a1):
    """Best place in the take's words for this script sentence near Eyeline's attempt [a0, a1]."""
    W = tk.words
    idx = [i for i, w in enumerate(W) if a0 - 2.5 <= w["s"] <= a1 + 2.0]
    if not idx:
        return None
    best = None
    for j in idx:
        if W[j]["s"] > a0 + 2.0:
            break
        seg = [k for k in range(j, min(len(W), j + int(len(script_toks) * 2.2) + 15)) if W[k]["n"] not in FILLERS
               and W[k]["s"] <= max(a1 + 2.0, a0 + (a1 - a0) * 1.6 + 2.0)]
        sm = SequenceMatcher(None, script_toks, [W[k]["n"] for k in seg], autojunk=False)
        pairs = [(b.a + q, seg[b.b + q]) for b in sm.get_matching_blocks() for q in range(b.size)]
        if not pairs:
            continue
        m = len(pairs); first, last = pairs[0][1], pairs[-1][1]
        sc = m - 0.4 * abs(W[first]["s"] - a0) - 0.12 * (last - first + 1 - m)
        if best is None or sc > best[0]:
            best = (sc, m, first, last, pairs)
    return best


def search(tk, toks):
    """Every reading of this sentence anywhere in the take's transcript, best first and not overlapping.
    Used when the teleprompter logged no attempt for the line in this take (voice following lost the place,
    or the script was edited after recording)."""
    W, n, heads = tk.words, len(toks), set(toks[:3])
    found = []
    for j, w in enumerate(W):
        if w["n"] not in heads:
            continue
        seg = [k for k in range(j, min(len(W), j + int(n * 2.2) + 15)) if W[k]["n"] not in FILLERS]
        sm = SequenceMatcher(None, toks, [W[k]["n"] for k in seg], autojunk=False)
        pairs = [(b.a + q, seg[b.b + q]) for b in sm.get_matching_blocks() for q in range(b.size)]
        if len(pairs) < max(2, 0.3 * n):
            continue
        m = len(pairs); first, last = pairs[0][1], pairs[-1][1]
        found.append((m - 0.12 * (last - first + 1 - m), m, first, last, pairs))
    out = []
    for r in sorted(found, key=lambda r: -r[0]):
        if all(r[3] < o[2] or r[2] > o[3] for o in out):
            out.append(r)
    return out


cands = {}
for L in plan_lines:
    toks = norm(L["text"])
    out = []
    for tk in takes.values():
        found = []
        for n, a in enumerate(tk.tj.get("attempts", [])):
            if norm(tk.sent.get(a["sentence"], "")) != toks:
                continue
            r = align(tk, toks, a["start"], a["end"])
            if r:
                found.append((n, a, r))
        if not any(r[1] >= 0.6 * len(toks) for _, _, r in found):     # no good logged reading: look in the transcript
            found += [(None, {"start": tk.words[r[2]]["s"], "end": tk.words[r[3]]["e"], "flags": ["transcript search"]}, r)
                      for r in search(tk, toks)]
        for n, a, r in found:
            _, m, first, last, pairs = r
            matched = {k for _, k in pairs}
            span = list(range(first, last + 1))
            fill = [k for k in span if tk.words[k]["n"] in FILLERS]
            extra = [k for k in span if k not in matched and k not in fill]
            recall = m / len(toks)
            flags = a.get("flags") or []
            d = a.get("delivery") or {}
            score = (100 * recall - 2.5 * len(extra) - 2 * len(fill)
                     - (35 if "marked" in flags else 0) - (4 if "clipped" in flags else 0)
                     - (60 if "dropout" in flags else 0)
                     + {"good": 15, "G": 15, "bad": -50, "B": -50}.get(str(a.get("rating")), 0)
                     + 0.4 * np.clip((d.get("loudness") or -26) + 26, -8, 8)
                     - 1.5 * max(0, (d.get("endDrop") or 0) - 5)
                     + 4 * float(np.mean([tk.words[k]["p"] for k in span])))
            out.append({"take": tk.key, "attempt": n, "start": a["start"], "end": a["end"], "recall": round(recall, 3),
                        "extra": [tk.words[k]["w"] for k in extra], "fillers": len(fill), "flags": flags,
                        "rating": a.get("rating"), "delivery": d, "score": round(float(score), 2),
                        "first": first, "last": last, "matched": sorted(matched)})
    # the same reading can be found from two attempts; keep one per (take, first word)
    uniq = {}
    for c in out:
        k = (c["take"], c["first"])
        if k not in uniq or c["score"] > uniq[k]["score"]:
            uniq[k] = c
    cands[L["line"]] = sorted(uniq.values(), key=lambda c: -c["score"])


# ---------- edges from the waveform ----------
def sound_start(tk, w_start, w_end, t_floor):
    """Where the word's sound begins: the first sustained sound (20 ms) after at least 40 ms of silence, searched
    from just before Whisper's start up to the word's end (Whisper often starts a word early, across a pause).
    A plosive's burst just before it (within 60 ms, after silence) is part of the word. If the word is glued to
    the one before (no silence at all), the quietest point between the two."""
    i0, m = tk.sound_mask(max(t_floor, w_start - 0.25), max(w_end, w_start + 0.1))
    for q in range(len(m) - 20):
        if m[q:q + 20].all() and (q < 40 and i0 / 1000 <= t_floor + 0.001 or q >= 40 and (~m[q - 40:q]).sum() >= 36 or q == 0):
            j = q
            for r in range(q - 1, max(-1, q - 61), -1):          # walk back over a burst + closure
                if m[r]:
                    j = r
                elif r < j - 50:
                    break
            if j < q and (j < 30 or (~m[max(0, j - 30):j]).sum() >= 27):
                q = j
            return (i0 + q) / 1000
    a, b = max(0, int((max(t_floor, w_start - 0.08)) * 1000)), int((w_start + 0.06) * 1000)
    return (a + int(np.argmin(tk.eb[a:b]))) / 1000 if b > a else w_start


def sound_end(tk, w_start, w_end, t_ceil):
    """Where the word's sound stops: the start of the first >= 70 ms silence after the word has begun
    (Whisper often ends a word late, across a pause), never after t_ceil."""
    for need, extra in ((70, 0.0), (30, 0.25)):
        i0, m = tk.sound_mask(w_start + 0.06, min(t_ceil + extra, max(w_end, w_start + 0.1) + 0.6))
        run = 0; started = False
        for q in range(len(m)):
            if m[q]:
                started = True; run = 0
            else:
                run += 1
                if started and run >= need:
                    return (i0 + q - run + 1) / 1000
    i0, m = tk.sound_mask(max(w_end - 0.05, w_start + 0.06), t_ceil + 0.25)
    q = int(np.argmin(tk.eb[i0:i0 + len(m)])) if len(m) else 0
    return (i0 + q) / 1000


def snap(tk, c_in, c_out, lo, hi):
    """Frame-align a clip without ever cutting into its own words: cutIn on the camera frame at or before c_in,
    cutOut on the first frame boundary at or after c_out. (lo/hi are kept for the QA notes.)"""
    cam = c_in + tk.offset(c_in)
    cin = c_in - (cam - np.floor(cam * FPS + 1e-9) / FPS)
    n = max(1, int(np.ceil((c_out - cin) * FPS - 1e-9)))
    return round(cin, 4), round(cin + n / FPS, 4), n


def clips_for(tk, c, line):
    """Split one pick into clips: drop ums and false-start repeats, cut pauses > PAUSE, edges on the sound."""
    W = tk.words
    span = list(range(c["first"], c["last"] + 1))
    matched = set(c["matched"])
    def removable(k):
        w = W[k]
        if w["n"] in FILLERS:
            return True
        if k not in matched:
            nxt = next((q for q in span if q > k and q in matched), None)
            return nxt is not None and (W[nxt]["n"] == w["n"] or W[nxt]["n"].startswith(w["n"]))   # "the the"
        return False

    # a run of removable words is cut only where there is real silence on both sides of it; glued to the
    # words around it, cutting would clip a sound, so it stays (and is noted for review)
    keep, kept_note = [], []
    k = span[0]
    while k <= span[-1]:
        if not removable(k):
            keep.append(k); k += 1; continue
        r0 = k
        while k + 1 <= span[-1] and removable(k + 1):
            k += 1
        r1 = k; k += 1
        before = keep[-1] if keep else None
        after = next((q for q in range(r1 + 1, span[-1] + 1) if not removable(q)), None)
        r_on = sound_start(tk, W[r0]["s"], W[r0]["e"], sound_end(tk, W[before]["s"], W[before]["e"], W[r0]["s"] + 0.03) if before is not None else 0)
        r_off = sound_end(tk, W[r1]["s"], W[r1]["e"], (W[after]["s"] + 0.03) if after is not None else W[r1]["e"] + 0.5)
        gap_l = r_on - (sound_end(tk, W[before]["s"], W[before]["e"], W[r0]["s"] + 0.03) if before is not None else -1)
        gap_r = (sound_start(tk, W[after]["s"], W[after]["e"], r_off) if after is not None else 99) - r_off
        if gap_l >= 0.04 and gap_r >= 0.04:
            continue                                   # clean: cut it out
        keep.extend(range(r0, r1 + 1))
        kept_note.append(" ".join(W[q]["w"] for q in range(r0, r1 + 1)))
    groups = [[keep[0]]] if keep else []
    for a, b in zip(keep, keep[1:]):
        dropped_between = b != a + 1
        gap_s = sound_end(tk, W[a]["s"], W[a]["e"], W[b]["s"] + 0.03)
        gap_e = sound_start(tk, W[b]["s"], W[b]["e"], gap_s)
        if dropped_between or gap_e - gap_s > PAUSE:
            groups.append([b])
        else:
            groups[-1].append(b)
    out = []
    groups = [g for g in groups if g]
    for g in groups:
        k0, k1 = g[0], g[-1]
        prev_end = W[k0 - 1]["e"] if k0 > 0 else 0.0
        next_start = W[k1 + 1]["s"] if k1 + 1 < len(W) else len(tk.x) / SR
        prev_sound = sound_end(tk, W[k0 - 1]["s"], W[k0 - 1]["e"], W[k0]["s"] + 0.03) if k0 > 0 else 0.0
        s0 = sound_start(tk, W[k0]["s"], W[k0]["e"], prev_sound)
        s1 = sound_end(tk, W[k1]["s"], W[k1]["e"], (W[k1 + 1]["s"] + 0.03) if k1 + 1 < len(W) else len(tk.x) / SR)
        s1 = tk.tail(s1, (W[k1 + 1]["s"]) if k1 + 1 < len(W) else s1 + 0.04)
        next_sound = sound_start(tk, W[k1 + 1]["s"], W[k1 + 1]["e"], s1) if k1 + 1 < len(W) else len(tk.x) / SR
        prev_end, next_start = prev_sound, next_sound
        lo = max(prev_end + 0.01, s0 - 0.09); hi = min(next_start - 0.01, s1 + 0.09)
        if s1 - s0 < 0.06:
            continue                                   # a scrap, not a word
        cin, cout, frames = snap(tk, s0 - PAD_IN, s1 + PAD, lo, hi)
        out.append({"take": tk.key, "cutIn": cin, "cutOut": cout, "frames": frames,
                    "camOffset": round(tk.offset(cin), 6), "cam": tk.sync["cam"],
                    "text": " ".join(W[k]["w"] for n_, k in enumerate(g) if n_ == 0 or W[k]["r"] != W[g[n_ - 1]]["r"]),
                    "words": [k0, k1],
                    "soundIn": round(s0, 4), "soundOut": round(s1, 4),
                    "audioIn": round(max(s0 - PAD_IN, prev_end + 0.004, cin), 4),
                    "audioOut": round(min(s1 + PAD, next_start - 0.004, cout), 4),
                    "lines": [line["line"]], "chapter": line["chapter"]})
    if kept_note and out:
        out[0]["reviewNote"] = "left in because it is glued to the words around it: " + "; ".join(kept_note)
    return out


# ---------- off-script speech: words no reading of any script line covers ----------
off_runs = []
for tk in takes.values():
    covered = np.zeros(len(tk.words), bool)
    for L in plan_lines:
        for c in cands.get(L["line"], []):
            if c["take"] == tk.key:
                covered[c["first"]:c["last"] + 1] = True
    run = []
    for k, w in enumerate(tk.words):
        if not covered[k] and (not run or w["s"] - tk.words[run[-1]]["e"] < 1.2):
            run.append(k)
        else:
            if len(run) >= 3:
                off_runs.append((tk.key, run[0], run[-1]))
            run = [k] if not covered[k] else []
    if len(run) >= 3:
        off_runs.append((tk.key, run[0], run[-1]))
offlist = []
for key, k0, k1 in off_runs:
    tk = takes[key]; text = " ".join(w["w"] for w in tk.words[k0:k1 + 1])
    # the script line read just before it in this take
    before = None
    for L in plan_lines:
        for c in cands.get(L["line"], []):
            if c["take"] == key and c["last"] < k0 and (before is None or c["last"] > before[1]):
                before = (L["line"], c["last"])
    offlist.append({"take": key, "first": k0, "last": k1, "start": tk.words[k0]["s"], "end": tk.words[k1]["e"],
                    "afterLine": before[0] if before else -1, "redo": bool(REDO.search(text)), "text": text})
P.write_json(proj / "edit" / "offscript-candidates.json", offlist)
if "--list-offscript" in sys.argv:
    for o in offlist:
        print(f"{o['take']} {o['start']:7.2f}-{o['end']:7.2f} after L{o['afterLine']:<3} {'REDO ' if o['redo'] else ''}{o['text']}")
    sys.exit(0)

# ---------- the cut ----------
def phrase_at(tk, k0, k1, phrase, last=False, end=False):
    """Word index inside [k0, k1] where the phrase starts (or ends, with end=True)."""
    want = norm(phrase); ws = [tk.words[k]["n"] for k in range(k0, k1 + 1)]
    hits = [q for q in range(len(ws) - len(want) + 1) if ws[q:q + len(want)] == want]
    if not hits:
        raise SystemExit(f"phrase not found: {phrase!r} in {' '.join(ws)}")
    q = hits[-1] if last else hits[0]
    return k0 + q + (len(want) - 1 if end else 0)


keep_off = []
for d in (json.loads(keep_file.read_text()) if keep_file and keep_file.exists() else []):
    tk = takes[d["take"]]
    # the decision names a stretch by where it starts; the word list is the same, the stretch may have grown or shrunk
    k0 = min(range(len(tk.words)), key=lambda k: abs(tk.words[k]["s"] - d["start"]))
    end_t = d.get("untilStart", d["start"])
    run = next((o for o in offlist if o["take"] == d["take"] and o["first"] <= k0 <= o["last"]), None)
    if run is None:
        print(f"  note: off-script stretch at {d['take']} {d['start']} is now part of a script reading, skipped")
        continue
    o = dict(run); o["first"] = max(o["first"], k0)
    if "untilStart" in d:
        o["last"] = max(x["last"] for x in offlist if x["take"] == d["take"] and x["first"] <= min(range(len(tk.words)), key=lambda k: abs(tk.words[k]["s"] - end_t)) <= x["last"])
    k0, k1 = o["first"], o["last"]
    if "from" in d: k0 = phrase_at(tk, k0, k1, d["from"])
    if "fromLast" in d: k0 = phrase_at(tk, k0, k1, d["fromLast"], last=True)
    if "to" in d: k1 = phrase_at(tk, k0, k1, d["to"], end=True)
    o.update(first=k0, last=k1, mode=d["mode"], note=d.get("flag"),
             afterLine=d.get("afterLine", o["afterLine"]))
    keep_off.append(o)

# linking words between two lines read one after the other in the same take ("and", "so", "it changes")
# stay with the first line, so the speech flows the way it was said
chosen = {}
for L in plan_lines:
    ok = [c for c in cands.get(L["line"], []) if c["recall"] >= 0.6] or [c for c in cands.get(L["line"], []) if c["recall"] >= 0.3][:1]
    if ok:
        chosen[L["line"]] = ok[0]
for L in plan_lines:
    a, b = chosen.get(L["line"]), chosen.get(L["line"] + 1)
    if a and b and a["take"] == b["take"] and 0 < b["first"] - a["last"] - 1 <= 4:
        W = takes[a["take"]].words
        between = range(a["last"] + 1, b["first"])
        if W[b["first"]]["s"] - W[a["last"]]["e"] < 2.0:
            a["last"] = b["first"] - 1
            a["matched"] = sorted(set(a["matched"]) | {k for k in between if W[k]["n"] not in FILLERS})

plan, picks, flags = [], [], []
for L in plan_lines:
    cs = cands.get(L["line"], [])
    ok = [c for c in cs if c["recall"] >= 0.6] or [c for c in cs if c["recall"] >= 0.3][:1]
    if not ok:
        picks.append({"line": L["line"], "text": L["text"], "missing": True, "candidates": len(cs),
                      "best": [{k: c[k] for k in ("take", "start", "score", "recall", "extra")} for c in cs[:2]]})
        continue
    best = chosen.get(L["line"], ok[0])
    picks.append({"line": L["line"], "chapter": L["chapter"], "text": L["text"], "pick": best,
                  "others": [{k: c[k] for k in ("take", "start", "score", "recall", "extra", "fillers", "flags")} for c in ok[1:]]})
    for cl in clips_for(takes[best["take"]], best, L):
        cl["picks"] = [L["line"]]
        if best["recall"] < 0.6:
            cl["reviewNote"] = f"loose reading of the script line ({best['recall']:.0%} of its words), the only usable one"
        if "transcript search" in best["flags"]:
            cl["reviewNote"] = "; ".join(filter(None, [cl.get("reviewNote"), "found in the transcript (the teleprompter logged no attempt here); check it is the reading you want"]))
        cl["reason"] = (f"best of {len(ok)} readings (score {best['score']:.0f}"
                        + (f", next {ok[1]['score']:.0f} in {ok[1]['take']}" if len(ok) > 1 else "") + ")")
        plan.append(cl)
    for o in keep_off:
        if o["afterLine"] != L["line"]:
            continue
        tk = takes[o["take"]]
        if o["mode"] == "ext" and not (best["take"] == o["take"] and best["last"] < o["first"]
                                       and tk.words[o["first"]]["s"] - tk.words[best["last"]]["e"] < 1.5):
            continue                          # an extension only follows its own reading
        for cl in clips_for(tk, {"first": o["first"], "last": o["last"], "matched": list(range(o["first"], o["last"] + 1))},
                            {"line": L["line"], "chapter": L["chapter"]}):
            cl["offScript"] = True; cl["picks"] = [L["line"]]
            cl["reason"] = "off-script " + ("continuation of this reading" if o["mode"] == "ext" else "remark") + ", kept"
            if o.get("note"):
                cl["reviewNote"] = o["note"]
            plan.append(cl)

plan = [c for c in plan if c["soundOut"] - c["soundIn"] >= 0.06]
# never play the same moment twice: trim or drop a clip that overlaps one already in the cut
used = {}; deduped = []
for c in plan:
    iv = used.setdefault(c["take"], [])
    for a, b in iv:
        if c["cutIn"] < b and c["cutOut"] > a:
            if c["soundIn"] >= a and c["soundOut"] <= b:
                c = None; break
            if c["soundIn"] < a:                      # overlap at the end: keep the part before
                c["soundOut"] = min(c["soundOut"], a - PAD)
            else:
                c["soundIn"] = max(c["soundIn"], b + PAD)
            if c["soundOut"] - c["soundIn"] < 0.25:
                c = None; break
            tk = takes[c["take"]]
            c["cutIn"], c["cutOut"], c["frames"] = snap(tk, c["soundIn"] - PAD, c["soundOut"] + PAD, 0, 1e9)
            c["audioIn"] = round(max(c["audioIn"], c["soundIn"] - PAD), 4); c["audioOut"] = round(min(c["audioOut"], c["soundOut"] + PAD), 4)
            c["reviewNote"] = (c.get("reviewNote", "") + " trimmed so it does not repeat the previous clip").strip()
    if c:
        iv.append((c["cutIn"], c["cutOut"])); deduped.append(c)
plan = deduped

# where two clips are one continuous stretch of the same take (nothing removed between, no pause),
# they meet at one shared point, so the sound plays straight through
for p, q in zip(plan, plan[1:]):
    if p["take"] == q["take"] and 0 <= q["soundIn"] - p["soundOut"] < PAUSE + 0.05 and q["soundIn"] > p["soundIn"]:
        tk = takes[p["take"]]
        i0, i1 = int(p["soundOut"] * 1000) - 20, int(q["soundIn"] * 1000) + 20
        mid = (i0 + int(np.argmin(tk.eb[i0:i1]))) / 1000 if i1 > i0 else (p["soundOut"] + q["soundIn"]) / 2
        cam = mid + tk.offset(mid); b = mid - (cam - round(cam * FPS) / FPS)
        if b > p["cutIn"] + 0.1 and b < q["cutOut"] - 0.1:
            p["cutOut"] = round(b, 4); p["frames"] = max(1, round((b - p["cutIn"]) * FPS))
            p["cutOut"] = round(p["cutIn"] + p["frames"] / FPS, 4)
            q["cutIn"] = p["cutOut"]; q["frames"] = max(1, int(np.ceil((q["cutOut"] - q["cutIn"]) * FPS - 1e-9)))
            q["cutOut"] = round(q["cutIn"] + q["frames"] / FPS, 4); q["camOffset"] = round(tk.offset(q["cutIn"]), 6)
            p["joinNext"] = "continuous"; p.pop("audioOut", None); q.pop("audioIn", None)

for c in plan:
    c["camStart"] = round(c["cutIn"] + c["camOffset"], 6)
    c["origIn"], c["origOut"] = c["cutIn"], c["cutOut"]
    c.setdefault("flag", None); c["zoom"] = 0; c["stretch"] = 1
plan = P.normalize(plan, None)
E = proj / "edit"
for d in ("history",):
    (E / d).mkdir(parents=True, exist_ok=True)
P.write_json(E / "picks.candidate.json", picks)
P.write_json(E / "plan.candidate.json", plan)

miss = [p for p in picks if p.get("missing")]
print(f"{len(plan)} clips from {len(picks) - len(miss)} lines; missing {len(miss)}; "
      f"length {sum(c['dur'] for c in plan) / 60:.2f} min")
for p in miss:
    print("  missing:", p["line"], p["text"][:80])
    for c in p["best"]:
        print(f"    closest: {c['take']} at {c['start']:.1f} s, {c['recall']:.0%} of the line's words")
if miss:
    for tk in takes.values():
        said = list({w["r"]: w["w"] for w in tk.words}.values())          # one entry per transcript word
        print(f"  {tk.key} transcript ({len(said)} words): {' '.join(said[:60]) or '(empty)'}" + (" ..." if len(said) > 60 else ""))
