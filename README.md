<p align="center">
  <a href="https://tein.ai"><img src="docs/branding/tein-ai-banner.svg" alt="TEIN AI — Join the waitlist for open-source AI workflows" width="960"></a>
</p>

# YouTube AI Video Editing System

> **Style the boards yourself.** The included boards are starter templates, not a finished visual identity. Customize the colors, fonts, shapes, and layouts for your own videos. The animation examples are there to adapt.

**An open-source workflow for recording, AI-assisted editing, design, Claude Design, animation, motion graphics, and the final editor handoff.**

<p align="center"><strong>Want more open-source AI filmmaking workflows?</strong><br>Join the TEIN AI waitlist for updates on new workflows, tools, and releases.<br><a href="https://tein.ai"><strong>Join the TEIN AI waitlist →</strong></a></p>

Eyeline connects the script you read, the takes you record, the source clips you cut, and the visuals you design. The workflow keeps its decisions in readable Markdown and JSON so you can use your own AI agent, change the rules, and keep editing by hand.

![Eyeline Edit — preview, transcript and source-linked timeline](docs/media/editor-demo.gif)

[Quick start](#quick-start) · [Workflow](docs/workflow.md) · [Design & motion](docs/design-animation.md) · [JSON formats](docs/formats.md) · [Customize the skills](docs/customization.md) · [Architecture](docs/architecture.md)

## What is included

| Part | What it does |
| --- | --- |
| **Eyeline teleprompter** | Read a script, follow your voice, record microphone audio, mark flubs, track attempts, and optionally sync a display over your local network. |
| **Eyeline Edit** | Review source-linked clips, inspect waveforms and word timings, adjust cut edges, relink camera originals, and export video/audio. |
| **AI editing tools** | Transcribe takes, estimate camera sync and drift, build full-take proxies, propose a candidate cut, and report possible transcription or edge issues. |
| **Agent instructions** | Separate recording, cutting, review, design, animation, and editor handoff responsibilities. Use with a coding agent that can read files and run commands. |
| **Design / Claude Design workflow** | 267 restyled HTML reference boards (246 animated), eight simple static starters, three filled design briefs, and prompts for planning, building, and reviewing boards. Use your design tool of choice, including Claude Design. |
| **Animation / motion graphics** | An animated board library with play/pause/scrubbing, JSON timelines, and a local frame renderer for narration-aligned graphics. |
| **Editor handoff** | A predictable folder tree, approved audio, source mapping, rendered boards, captions, and a finishing checklist for Resolve, Premiere, or another editor. |
| **Placeholder skills** | Fresh, intentionally unconfigured templates you can fine-tune for your own voice, design, pacing, and motion. No private production skills are included. |

This is an early public release, not an unattended one-click editor. Cutting decisions need human review. Speech recognition can turn a mispronounced word into a correctly spelled transcript, and waveform silence is not proof that a word is finished. [Read the limits](docs/cutting.md).

## Quick start

Install **Python 3.10+** and **uv** from their official installers. Chrome or Edge is recommended for browser speech recognition. No API key is required to launch either app.

### Without the terminal (macOS)

Double-click **`Eyeline.command`** in the repository folder. It opens **Eyeline Home** in your browser: one page that lists your projects, opens the teleprompter, finds each take's camera clip by sound, prepares takes for editing (transcript, sync, previews), makes a draft cut and opens the editor. Keep the Terminal window it opens running; close it to stop Eyeline. `Teleprompter.command` and `Editor.command` start just one app.

Copy your camera clips into the project's `footage/` folder; Home shows the folder with **Open camera folder**. On another OS, run `uv run apps/home/home_server.py` and open http://localhost:5300.

### From the terminal

```bash
git clone https://github.com/sirioberati/YouTube-AI-Video-Editing-System.git
cd YouTube-AI-Video-Editing-System

# Teleprompter — open http://localhost:5317
python3 apps/teleprompter/server.py
```

On Windows, use `py` in place of `python3`. Projects are saved to `~/Eyeline/Projects` by default. Set `EYELINE_DATA` before starting to use another drive. Keep the terminal running.

In a second terminal:

```bash
# Editor — open http://localhost:5320
uv run apps/eyeline-edit/edit_server.py
```

The editor needs an Eyeline project with a cut plan and full-take playback proxies. For a first look without recording anything:

```bash
uv run tools/create_demo.py
uv run apps/eyeline-edit/edit_server.py .local/demo/01-recording
```

The demo creates synthetic camera/audio media locally; it contains no real recordings. See [setup](docs/setup.md) for Windows, external drives, dependencies, and LAN display mode.

## Record → cut → design → animate → finish

```mermaid
flowchart LR
  A[Script + Eyeline teleprompter] --> B[Takes + audio + JSON]
  B --> C[AI candidate cut]
  C --> D[Eyeline Edit + human review]
  D --> E[Approved WAV + transcript]
  E --> F[Design brief + Claude Design / HTML boards]
  F --> G[Animation + motion graphics]
  G --> H[Editor handoff + final video]
```

### 1. Record with the teleprompter

![Voice-following teleprompter demo](docs/media/teleprompter-demo.gif)

The recording folder keeps microphone audio, script snapshots, take metadata, captions, and a readable take report together.

![Example take files](docs/media/take-files.png)

### 2. Review the AI-assisted cut

![Adjusting clip edges against the waveform](docs/media/edge-trimming.gif)

Edit the original source intervals. Keep complete source handles available. A playback proxy covers a whole take; an assembled export never replaces the source clips. The experimental assembler writes `plan.candidate.json`, leaving your active `plan.json` alone.

### 3. Design in Claude Design or your own tool

Work from the **approved final-cut transcript**. The [unbranded design pack](templates/design/README.md) includes:

- **267 restyled HTML reference boards:** 246 animated examples and 21 static/reference layouts, preserving the original motion mechanics. Includes typography, charts, diagrams, reveals, masks, transitions, and motion studies.
- **Eight additional simple static starters:** process, comparison, chart, timeline, layers, code, evidence, and recap.
- **Three filled example briefs:** a review process, a comparison, and a measurement explanation.
- **Three reusable prompts:** transcript to brief, brief to HTML, and board review.
- **A searchable player with Play/Pause, Replay, and scrubbing**, plus [rendering examples](examples/design-starters-timeline.json).

![Animated board library and playback controls](docs/media/design-starters.png)

Download or clone the repo, then run `python3 -m http.server 5331 --directory templates/design` from its root and open `http://localhost:5331/` to browse and play the boards. GitHub displays HTML source rather than running it. The library uses a generic editorial theme and system fonts. Its animation timing and effects are preserved, while personal media is replaced with neutral placeholders. **Style the boards yourself before production.** Example copy, quotes, and numbers require verification or replacement. See the [library guide](templates/design/animated/README.md) for dimensions, media/rendering limits, and asset credits.

Start with the [design brief](templates/design-brief.md) and [Claude Design prompt](templates/claude-design-prompt.md), or adapt one of the [filled briefs](templates/design/briefs). The reference HTML is included with personal branding and signature styling removed. Private skills and identifiable source media are not bundled.

### 4. Add animation and motion graphics

Align graphic changes to the approved narration. Each HTML board exposes `window.seek(seconds)` so preview and export use the same deterministic state. Start with [the generic board](templates/board/index.html), customize your visual system, and render from a [timeline JSON](examples/board-timeline.json). See [design and animation](docs/design-animation.md).

### 5. Hand off to your editor

Deliver the approved cut, its WAV and transcript, source-linked plan, design assets, board renders, and timing manifest. The final editor assembles them in Resolve, Premiere, or another NLE. This release provides the files and handoff contract; it does not automate those commercial editors.

## How the system works

The following diagrams show the example workflow behind the project. Their take counts and thresholds are illustrative, not quality guarantees. The public cut generator proposes a candidate for review.

![From microphone audio and script to a take report](docs/media/take-report-architecture.png)

![From multiple takes to a draft recording plan](docs/media/edit-plan-architecture.png)

<details>
<summary>See the teleprompter layers, editing layers, and example take-selection breakdown</summary>

![Teleprompter processing layers](docs/media/teleprompter-layers.png)

![AI editing and review layers](docs/media/agent-cut-layers.png)

Editable source mapping is preserved. Redundant splits between continuous source intervals are not required. QA remains a combination of diagnostics and human listening.

![Attempts selected into one example cut](docs/media/tries-to-cut.png)

</details>

## Folder structure

```text
*.command              Double-click launchers (macOS): Eyeline Home, teleprompter, editor
apps/                  Eyeline Home, teleprompter and Eyeline Edit source
agents/                Generic role instructions and handoffs
skills/                Placeholder SKILL.md files only
config/                Workflow stages and example preferences
schemas/               Core JSON contracts
examples/              Synthetic JSON examples (no production projects)
templates/             Project tree, design pack, briefs, prompts, HTML boards
tools/                 Project scaffolding, demo, render, release checks
docs/                  Setup, architecture, data formats, media and guides
```

![Example production project folder](docs/media/project-files.png)

The screenshot illustrates a real project's organization. Its project contents and backups are not bundled. Generate your own complete working folder:

```bash
python3 tools/init_project.py "/path/to/My Video"
```

## Bring your own skills

Everything in `skills/` is a **placeholder**, written for this public repository. Fill in your audience, voice, editorial rules, design tokens, animation rules, and examples. Customizing these Markdown files is prompt configuration; it does not train a model. Private channel instructions, voice fingerprints, research libraries, and proprietary skill implementations are excluded.

## Privacy and dependencies

The apps run locally. Browser speech recognition may use your browser vendor's service; QR code and font resources load from public CDNs. Whisper models and Python dependencies download on first use. Sending a transcript to an AI agent or Claude Design follows that tool's data policy. LAN display mode is opt-in and intended only for a trusted private network. See [privacy](docs/privacy.md).

**License:** code and newly authored templates are MIT. TEIN branding is excluded from the MIT grant; its owner retains all rights. Supplied demonstration images and GIFs are documented separately in [media credits](docs/media/README.md). Third-party software and model weights retain their own licenses.

## More open-source workflows from TEIN AI

Get updates on new AI filmmaking workflows, tools, and releases.

**[Join the TEIN AI waitlist →](https://tein.ai)**
