# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright", "imageio-ffmpeg"]
# ///
"""Render trusted seekable HTML boards to a silent video. No production skills required."""
import argparse, json, math, os, subprocess
from fractions import Fraction
from pathlib import Path

def validate(timeline, base):
    fps = float(Fraction(str(timeline["fps"])))
    width, height, duration = timeline["width"], timeline["height"], timeline["duration"]
    if not (isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0 and width % 2 == height % 2 == 0 and 0 < fps <= 120 and math.isfinite(duration) and duration > 0):
        raise ValueError("Invalid canvas, fps, or duration")
    scenes = sorted(timeline["scenes"], key=lambda s: s["start"])
    previous = 0
    for s in scenes:
        if not (previous <= s["start"] < s["end"] <= duration):
            raise ValueError("Scene overlap or invalid scene range")
        if not (base / s["file"]).is_file():
            raise ValueError(f"Missing board: {s['file']}")
        previous = s["end"]
    return fps, scenes

def render(source, output):
    from playwright.sync_api import sync_playwright
    import imageio_ffmpeg
    source, output = Path(source).resolve(), Path(output).resolve()
    timeline = json.loads(source.read_text(encoding="utf-8"))
    fps, scenes = validate(timeline, source.parent)
    if output.exists(): raise ValueError("Output exists; choose a new filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".partial.mp4")
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "image2pipe", "-vcodec", "png", "-framerate", str(timeline["fps"]), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chromium", args=["--disable-gpu"])
            page = browser.new_page(viewport={"width":timeline["width"],"height":timeline["height"]}, device_scale_factor=1)
            current = object()
            frames = math.ceil(timeline["duration"] * fps)
            report = os.environ.get("EYELINE_PROGRESS") == "1"      # set by Eyeline Home
            for frame in range(frames):
                if report and frame % 25 == 0:
                    print("@progress " + json.dumps({"done": frame, "total": frames, "step": f"Rendering frame {frame} of {frames}"}), flush=True)
                at = frame / fps
                scene = next((s for s in scenes if s["start"] <= at < s["end"]), None)
                if scene is not current:
                    current = scene
                    if scene:
                        page.goto((source.parent / scene["file"]).resolve().as_uri())
                        page.evaluate("document.fonts.ready")
                        if not page.evaluate("typeof window.seek === 'function'"):
                            raise ValueError("Board must expose window.seek(seconds)")
                    else:
                        page.goto("about:blank")
                        page.set_content('<body style="margin:0;background:white"></body>')
                if scene: page.evaluate("t => window.seek(t)", at - scene["start"])
                proc.stdin.write(page.screenshot(type="png"))
            browser.close()
        proc.stdin.close()
        if proc.wait() != 0: raise RuntimeError("FFmpeg render failed")
        partial.replace(output)
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait()
        partial.unlink(missing_ok=True)
    print(output)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline"); parser.add_argument("output")
    args = parser.parse_args(); render(args.timeline, args.output)
