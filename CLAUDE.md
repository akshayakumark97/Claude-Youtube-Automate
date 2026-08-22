# YouTube Automation

You are my YouTube video production assistant.

## Use the script — do not rebuild the pipeline by hand

`scripts/make_short.py` already does the whole job: analysis, silence
removal, framing, subtitles, audio mastering, encoding, upload. It runs in
**~8 seconds** on a cached source.

Do NOT hand-roll ffmpeg command chains, re-probe geometry, or render
comparison grids to inspect visually unless I explicitly ask. Doing that by
hand is what made earlier edits slow and expensive.

```bash
# 1. show me what's in the video and what the cut will be (cheap, no render)
.venv/bin/python3 scripts/make_short.py --input input/VIDEO.mp4 --analyze

# 2. let me pick size / duration / framing / upload from a menu
.venv/bin/python3 scripts/make_short.py --input input/VIDEO.mp4 --interactive

# 3. or go straight through
.venv/bin/python3 scripts/make_short.py --input input/VIDEO.mp4 \
    --duration 60 --size 480x720 --layout blur --upload
```

**Always run `--analyze` first and show me the line list.** I decide what to
keep; you don't guess. Then pass my choices as flags.

Useful flags: `--layout blur|crop|letterbox`, `--speech-from/--speech-to`
(exclude junk or trailing lines), `--fix WRONG=RIGHT` (correct a caption),
`--no-subs`, `--keep-subs`, `--encoder quality`, `--refresh`, `--analyze`.

## Ask me, don't assume

Ask before rendering when any of these is unclear: target duration, output
resolution, framing, and which lines to keep. Use one batched question, not
a series of them.

## Known environment — treat as settled, don't re-derive

- ffmpeg has **no libass, no drawtext, no subtitles filter**. Captions are
  rendered as PNGs with Pillow and composited via `overlay`. Don't try
  `-vf subtitles=` or `drawtext`; it will fail.
- `h264_videotoolbox -q:v 60` is the fast path (~10x libx264, similar size).
  `--encoder quality` switches to libx264 crf 20.
- Transcription is `mlx-whisper` + `whisper-large-v3-turbo`, cached in
  `.cache/` keyed by file fingerprint. Re-runs are free. Model is already
  downloaded.
- Sources are often **letterboxed** and carry **burned-in subtitles**. Both
  are detected and cropped away automatically.
- "Remove silence" means removing **dialogue-free stretches**.
  `silencedetect` finds nothing on music-backed footage.
- A Short must be **vertical or square**. 720x480 is landscape and will not
  be treated as a Short; 480x720 will.
- Whisper mishears names and coined words. Cross-check important lines
  against any burned-in subtitles in the source, then fix with `--fix`.

## Rules

1. Never delete or overwrite the original video in `input/`.
2. Edited videos go in `output/`.
3. Default YouTube privacy to **PRIVATE**.
4. Never publish publicly without my explicit confirmation.
5. Upload via `scripts/upload_youtube.py` (or `make_short.py --upload`).
6. Clean up with `--cleanup work` after a successful upload. `--cleanup
   input` is refused unless `--delete-original` is also passed, per rule 1.

## Directory structure

```
input/        original videos (never modified)
output/       edited videos + .srt/.title/.description/.tags sidecars
scripts/      make_short.py, upload_youtube.py
credentials/  Google OAuth
.cache/       transcript + geometry cache (safe to delete, costs time)
work/         scratch, deleted by --cleanup work
```

## Safety

Never expose or commit `client_secret.json`, `token.json`, OAuth
credentials, or API keys.

Note: `credentials/token.json` holds only the `youtube.upload` scope, so
reading a video's status back returns 403. Report what the upload request
set; don't claim to have verified it server-side.
