# Setup

Use Python 3.10+ and uv. Download them from https://www.python.org/downloads/ and https://docs.astral.sh/uv/getting-started/installation/. No installer in this repository copies private agent skills. Apps can run independently of a coding assistant.

## Commands

From the repository root, start the prompter with `python3 apps/teleprompter/server.py` (Windows: `py apps/teleprompter/server.py`). Open http://localhost:5317 in Chrome or Edge and allow microphone access. Browser recognition support varies; test a short recording before a long take. The prompter records mic audio; a camera is recorded separately.

Start the editor with `uv run apps/eyeline-edit/edit_server.py [PROJECT_PATH] [PORT]`. Defaults to localhost:5320. `uv` reads each script's inline dependencies and installs them in its cache. ImageIO supplies FFmpeg. Sync tools add SciPy; transcription tools use MLX Whisper on Apple silicon or faster-whisper elsewhere. Model downloads may take several GB. Linux/Windows use a CPU fallback; real-device recording and hardware encoding should be tested on your machine.

## Storage

Set `EYELINE_DATA` to the folder that will contain `Projects/` and script files. Set `EYELINE_EDIT_HOME` to relocate local editor configuration, proxies' waveform caches, and render segment caches. Set `HF_HOME` and `UV_CACHE_DIR` to move model and package caches when needed. These paths are environment settings on your own machine, not repository configuration.

macOS/Linux:
```bash
export EYELINE_DATA="/path/on/your/disk/Eyeline"
export EYELINE_EDIT_HOME="/path/on/your/disk/EyelineCache"
python3 apps/teleprompter/server.py
```

Windows PowerShell:
```powershell
$env:EYELINE_DATA = 'D:\Eyeline'
$env:EYELINE_EDIT_HOME = 'D:\EyelineCache'
py apps/teleprompter/server.py
```

Keep source media mounted until export completes. Store working projects outside the repository or under ignored `.local/`. Back them up before editing.

## iPad / secondary display

Start the prompter with `--lan` to bind to the local network. The terminal prints the address for a second device. This is an unauthenticated trusted-LAN relay: never forward its port or expose it on the internet. Use localhost on the recording computer for microphone and file operations. Only the local computer can modify project files. Remote devices display/relay the session; browser microphone features on plain HTTP LAN addresses may be unavailable.

## Development

`uv run --with numpy --with soundfile --with imageio-ffmpeg --with jsonschema python -m unittest discover -s tests -v`

`python3 tools/check_release.py`

`uv run tools/validate_examples.py` checks every file in `examples/` against its schema in `schemas/` and exits non-zero on any mismatch.

Only the release copy is modified when preparing this repository. Existing installed applications and projects are independent.

## Optional GitHub Actions

The same source/data/API checks are provided in `templates/github-ci.yml`. To enable them in your fork, copy that file to `.github/workflows/ci.yml` using a GitHub login with permission to create Actions workflows. The initial public release leaves this optional; all listed initial checks were run locally.
