# Data formats

Times are seconds unless marked otherwise. Recording times and final-cut times are different clocks. JSON schemas validate core shapes; tools and human review must additionally check interval order, source bounds, and references.

| File | Clock and purpose |
| --- | --- |
| project.json | Name, creation time and Eyeline version. |
| takes/Take NN…/take.json | Original mic-audio clock. Attempts, sentences, rough ranges, utterances, flubs, live word matches and health data. |
| edit-plan.json | Teleprompter cross-take draft against script lines. A `missing` line requires review. |
| edit/words/takeNN.tsv | Whisper word start/end on mic clock. Columns start, end, word, prob. Approximate; do not cut blindly. |
| edit/footage.json | Camera clips by filename, size in bytes and duration. Real paths stay in local config. Replace example size 0 with actual bytes. |
| edit/sync/takeNN.json | Camera clock = take clock × (1+a) + b, using offset.a and offset.b. Optional maps handle local alignment exceptions. |
| edit/plan.candidate.json | Proposed source-linked intervals, pending review. |
| edit/plan.json | Active editor array: take, cam, cutIn, cutOut, camOffset, text, chapter; normalization adds camStart, frames, padFrames, dur, outStart, id. |
| edit/plan.original.json | Explicit initial reviewed snapshot for reset, not automatically replaced by candidate tools. |
| edit/proxies/takeNN.mp4 | Full source take timeline; proxy second t corresponds to mic second t. Never the assembled edit. |
| final cut words.tsv | Final timeline: start, end, word, frame_in, frame_out, confidence. |
| final cut transcript.json | Words and chapter timing from transcribing exported audio. |
| timeline.json | Board scenes in approved final-cut seconds. `file` is relative to this JSON. |

`cutIn < cutOut`; intervals must stay within their source take. Keep complete original source files for handles. Adjacent intervals with matching source ends are continuous; overlapping source intervals require investigation. The editor normalizes to 25 fps (`FPS_RATE` in `apps/eyeline-edit/project.py`). No fields promise exact phonetic boundaries.

Examples are synthetic and deliberately small. See schemas/ for contracts and examples/ for data. The prompter's `words` are browser script matches; they are not the same as the Whisper TSV or final-cut word export.
