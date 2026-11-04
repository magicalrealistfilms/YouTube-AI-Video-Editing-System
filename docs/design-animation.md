# Design, Claude Design, animation and motion graphics

Design begins after the cut is approved. The transcript of the approved WAV determines what visuals explain and when they appear. An earlier recording script is only a reference.

## In Eyeline Home

Steps 6 to 9 of a project in Eyeline Home cover this stage without the terminal:

- **Export and approve** lists the final-cut files the editor exported (video, WAV, transcript and word timings, captions).
- **Design boards** copies two ready-to-paste prompts: one for Claude to draft the design brief from the final-cut transcript with its timings, one for Claude Design that includes the brief. It opens the project's design brief (created from `templates/design-brief.md`), the board library and the boards folder, and can add a starter board. Each board in the folder has a preview with a scrubber.
- **Animate** edits the board timeline: pick a board per scene and click words in the transcript to set start and end times. **Preview with narration** plays the boards in time with the exported WAV. **Render board track** renders the silent track with `tools/render_boards.py` (the first render installs a browser for rendering).
- **Finish** lists the files for Resolve or Premiere.

Inside a teleprompter project, boards go in `boards/`, the timeline in `animation/timeline.json` and the brief in `design-brief.md`. In a folder made by `tools/init_project.py`, Home uses `04-boards/`, `05-animation/` and `03-design-brief/` instead. The board track is written next to the final cut as `<project> - boards.mp4`; an earlier one is kept as `(previous)`. Board previews and the library are served read-only from a second local port (5301), so a board's scripts cannot use Home's controls.

## Style the templates yourself

The [design pack](../templates/design/README.md) now opens a **267-board library**: 246 animated examples and 21 static/reference layouts. Its player includes search, Play/Pause, Replay, and scrubbing. Original CSS motion mechanics remain; the personal branding and signature styling are replaced by a generic editorial theme. Customize fonts, colors, shapes, and layouts for your own visual identity before production.

Read the [animated library guide](../templates/design/animated/README.md) for styling and playback details. Boards share `theme.css` and `playback.js`; copy the entire `animated/` directory when using them. Some studies use vertical dimensions. Video-bearing boards need render verification because browser media seeks asynchronously.

The [eight simple static starters](../templates/design/static.html) remain optional extras. Their [sample timeline](../examples/design-starters-timeline.json) uses six-second demonstration scenes, not narration timing. The [filled briefs](../templates/design/briefs) and [prompts](../templates/design/prompts) work with either library. These are public templates, not private production skills.

## Design handoff

Fill `templates/design-brief.md`: audience, canvas, content per board, visual hierarchy, palette, fonts, camera safe area, source references and accessibility. Paste `templates/claude-design-prompt.md` with that brief and transcript into Claude Design, or use your preferred designer or agent. Claude Design is an optional external tool; this repository has no automatic Claude Design integration and bundles no proprietary styles or prompts.

Download HTML boards and assets into `04-boards/`. Use local assets and fonts you have permission to redistribute. Review boards in the target aspect ratio before animating.

## Motion contract

Each board exposes `window.seek(seconds)` where seconds are local to that board. The same time must always produce the same pixels, even when seeking backward. Avoid autonomous timers, random state, live external assets, and CSS animations that ignore the timeline. Keep camera space reserved. Use project preferences for motion; the starter board uses a simple opacity entrance, not a finished branded look.

The timeline has canvas, fps, duration and ordered scenes with `start`, `end`, and `file`. Scene paths are relative to the timeline JSON. Gaps render white. Overlaps are rejected. Word timings are measured on the approved final audio, not source-take time.

## Render a board track

```bash
uv run --with playwright --with imageio-ffmpeg python -m playwright install chromium
uv run tools/render_boards.py examples/board-timeline.json .local/board-track.mp4
```

The renderer seeks the HTML at every frame and writes a silent H.264 track. It never edits the approved WAV. HTML is code: render only boards you trust. Add the board track in your NLE alongside the approved cut and WAV. Use the safe area you specified in the brief to place the camera. Validate that narration and visual changes stay aligned throughout.

For another motion framework, retain the same deliverables: editable sources, timing manifest, silent graphics track and a review report. Private skill implementations are intentionally absent; customize the placeholder animation skill for your own production method.
