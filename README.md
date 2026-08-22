# YouTube Shorts Automation

Turn a long video into a finished, subtitled, upload-ready YouTube Short with
one command.

```bash
.venv/bin/python3 scripts/make_short.py --input input/my-video.mp4 --interactive
```

A 2:10 source becomes a 1:00 vertical Short in **~8 seconds**, captions burned
in, audio mastered to YouTube's loudness target, uploaded as private.

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Choosing a framing](#choosing-a-framing)
- [Flag reference](#flag-reference)
- [Uploading](#uploading)
- [Cleanup](#cleanup)
- [Caching and speed](#caching-and-speed)
- [Environment constraints](#environment-constraints)
- [Troubleshooting](#troubleshooting)

---

## Install

Requires **macOS on Apple Silicon** (the transcriber and the fast encoder are
both Apple-specific), **Python 3.12**, and **ffmpeg**.

```bash
brew install ffmpeg
python3 -m venv .venv
.venv/bin/pip install mlx-whisper Pillow numpy \
    google-api-python-client google-auth-oauthlib
```

Verified versions: ffmpeg 9.0.1, Python 3.12.13, mlx-whisper 0.4.3,
Pillow 12.3.0, numpy 2.5.2.

Put Google OAuth credentials in `credentials/client_secret.json`. The first
upload opens a browser to authorise and writes `credentials/token.json`.

### Directory layout

```
input/        source videos — never modified or deleted
output/       finished videos + .srt / .title / .description / .tags sidecars
scripts/      make_short.py, fetch_source.py, upload_youtube.py
credentials/  client_secret.json, token.json
.cache/       transcript + geometry cache, keyed by file fingerprint
work/         scratch (caption PNGs); safe to delete anytime
```

---

## Quick start

### 0. Get the source

Already have the file? Drop it in `input/` and skip to step 1. Otherwise pass a
link and the pipeline fetches it first:

```bash
make_short.py --url "https://youtu.be/XXXXXXXXXXX" --analyze
```

Or download on its own, which prints the resulting path:

```bash
scripts/fetch_source.py "https://youtu.be/XXXXXXXXXXX"
```

This wraps yt-dlp. It prefers H.264 + AAC in MP4 (VP9 and AV1 decode much
slower through the render filter graph), caps the download at 1080p by default
since a Short is at most 1080 wide, and reuses a file already sitting in
`input/` instead of pulling it again. Page links and plain direct file URLs
both work.

### 1. Pick a delivery mode

```bash
make_short.py --input input/VIDEO.mp4                 # Short:  1080x1920, blur
make_short.py --input input/VIDEO.mp4 --mode video    # Video:  1920x1080, crop
```

| | `--mode short` (default) | `--mode video` |
|---|---|---|
| Size | `1080x1920` (9:16) | `1920x1080` (16:9) |
| Layout | `blur` | `crop` |
| Duration | `60` | `auto` |
| Caption size | 84px, 5 words | 56px, 9 words |
| Output | `output/short_1080x1920.mp4` | `output/video_1920x1080.mp4` |

A preset only fills flags you left alone — any explicit `--size`, `--layout`,
`--duration`, `--font-size` or `--words-per-caption` overrides it.

`--duration auto` targets the natural length of the dialogue once the
dialogue-free stretches are gone: every line kept, nothing padded, nothing
dropped. It is the default for `--mode video` and works in either mode.

### 2. Look before you cut

`--analyze` renders nothing and takes about half a second on a cached source.
It prints the detected geometry, every line of dialogue with timestamps, and
the exact segment plan.

```bash
.venv/bin/python3 scripts/make_short.py --input input/my-video.mp4 --analyze
```

```
[1/7] Probing source...
      1280x720 @ 23.98fps, 2:10.2   picture 1280x536+0+92
[2/7] Transcribing (cached)...
      25 dialogue lines, 42.0s of speech (en)
[3/7] Detecting burned-in subtitles...
      band y=522-612 — will crop above it
[4/7] Planning cut to exactly 60s...
      13 segments, kept 60.000s, removed 70.2s of dialogue-free footage
      dialogue: 25 lines kept, none dropped

      segment    source range         length
       0           1.57 ->    4.96      3.39s
       1           8.05 ->   10.14      2.09s
       ...

      every line detected in the source:
        [  1.92 ->   4.56] Victor was always the smartest guy in every room.
        [  8.40 ->   9.74] He used to be different.
        ...
```

Lines marked `X` are not in the cut. Use the timestamps to decide what to
exclude.

### 3. Pick your options from a menu

```bash
.venv/bin/python3 scripts/make_short.py --input input/my-video.mp4 --interactive
```

Menus for resolution → duration → framing → encode speed → upload. Each has a
`*` marking the default, so pressing Enter through accepts all defaults.

### 4. Or go straight through

```bash
.venv/bin/python3 scripts/make_short.py \
    --input input/my-video.mp4 \
    --duration 60 --size 480x720 --layout blur \
    --speech-to 100 --fix "DOOMED.=DOOM." \
    --upload --privacy private --cleanup work
```

---

## How it works

Seven stages, each printed as it runs.

### 1. Probe

`ffprobe` reads dimensions, frame rate, duration, and confirms an audio track
exists.

### 2. Detect the real picture area

`cropdetect` votes across every frame to find the actual picture inside any
black letterbox bars. A 1280x720 file holding a 2.39:1 image reports something
like `picture 1280x536+0+92` — everything outside that is bars, and cropping
them off is free resolution.

### 3. Transcribe

`mlx-whisper` with `whisper-large-v3-turbo` produces word-level timestamps.
The result is cached, so this cost is paid once per source file.

Segments that look like hallucinations over music — `"thank you"`,
`"we'll be right back"`, `"subscribe"` in the final third, or anything with
`no_speech_prob > 0.6` — are dropped automatically.

### 4. Find and remove burned-in subtitles

Many sources already have captions baked into the picture. A vertical crop
slices them mid-word, and new captions collide with them, so they have to go.

Detection works on near-white pixel counts per row, sampled across frames at
known speech times. Subtitle rows spike hard against the surrounding image.
Two details matter:

- **The baseline is measured in the region being searched**, not the whole
  frame. The upper picture is full of bright image content (~1545 bright
  px/row in the test file) while the lower region floors around 700. Using the
  frame-wide baseline sets the bar ~2.5x too high and finds only the bottom
  caption line.
- **The band is walked outward across gaps** of up to 36px, so the faint upper
  lines of a two- or three-line caption are captured, not just the hardest
  spike.

The crop boundary then moves above the whole band. Set `--keep-subs` to skip
this if your source is clean.

### 5. Plan the cut

"Remove unnecessary silence" does **not** mean `silencedetect`. Music-backed
footage has no silence at all — the test file has continuous score end to end,
and `silencedetect` finds essentially nothing. What actually needs removing are
the **dialogue-free stretches**.

The planner:

1. Starts with one padded window per line (0.35s lead, 0.40s tail).
2. Merges windows that already touch.
3. Spends the remaining budget **re-opening the smallest gaps first**.

Step 3 is what makes it sound natural. Filling tight gaps restores the
dramatic beats between lines while leaving the long dead stretches on the
floor. Leftover time becomes a musical outro, then a longer cold open.

It lands on the target duration to within 50ms and **never sacrifices a line
to hit the target**. If it is forced to drop something it drops the quietest
window last, and names every drop in the output.

### 6. Render captions

Captions are grouped at sentence level (~5 words per card), each held a
minimum of 0.75s so nothing flashes past unreadably, and wrapped to at most
two lines.

They are drawn as transparent PNGs with Pillow — white Arial Bold, dark
stroke, soft drop shadow — then assembled into a single timed image stream via
ffmpeg's concat demuxer and composited in one `overlay` pass.

This is not the obvious approach, and the reason is in
[Environment constraints](#environment-constraints): this ffmpeg build has no
text rendering at all.

### 7. Encode

One ffmpeg invocation does everything: per-segment `trim`/`atrim`, `concat`,
crop, blur composite, caption overlay, fade out, and the full audio chain.

Audio is mastered as:

```
highpass 55Hz              remove rumble
-1.5dB @ 180Hz             tame boom
+2.2dB @ 3kHz              dialogue presence
compressor 2.4:1 @ -18dB   gentle glue
limiter 0.94               safety ceiling
loudnorm (two-pass linear) -14 LUFS / -1.5 dBTP, YouTube's target
50ms fades per cut         kills clicks on continuous music
```

The two-pass loudnorm matters: the first pass measures the *edited* audio,
because cutting changes the loudness statistics. Measured result on the test
file: **-14.02 LUFS, -1.32 dBTP, no clipping**.

---

## Choosing a framing

Going from a 2.39:1 cinematic source to a 2:3 vertical frame means losing
something. Pick which.

### `--layout blur` (default)

Widest crop that keeps faces intact, downscaled to the output width so there
is **no upscaling**, with a blurred and darkened copy filling the rest.

Best all-rounder. Fills the frame without dead black, keeps composition, stays
sharp. On dark footage the blur reads as a soft glow.

### `--layout crop`

Full-bleed centre crop, edge to edge.

Sounds ideal, usually isn't. On a 2.39:1 source only ~22% of the width
survives, subjects that sit off-centre get cut in half, and the upscale
(~1.7x) softens a low-bitrate source noticeably. Good when your subject is
reliably centred.

### `--layout letterbox`

Native 1:1 pixels, black bars above and below.

Sharpest possible — zero scaling — but shows less of the scene and leaves
large flat black areas.

---

## Flag reference

### Framing and timing

| Flag | Default | Notes |
|---|---|---|
| `--input` | — | Local source video. Required unless `--url` is given |
| `--url` | — | Fetch the source from a link into `input/` first |
| `--max-height` | `1080` | Cap the `--url` download resolution |
| `--force-download` | off | Refetch even if the file is already in `input/` |
| `--output` | `output/short_<W>x<H>.mp4` | Overwrites silently |
| `--mode` | `short` | `short` = 9:16 vertical, `video` = 16:9 landscape |
| `--duration` | per mode | Seconds (hit within 50ms), or `auto` |
| `--size` | per mode | `WxH`. Warns if landscape in `short` mode |
| `--layout` | per mode | `blur` / `crop` / `letterbox` |
| `--keep-subs` | off | Don't crop away burned-in subtitles |

### Choosing content

| Flag | Notes |
|---|---|
| `--analyze` | Print the report and cut plan, render nothing |
| `--interactive` | Menu-driven option picking |
| `--speech-from N` | Ignore dialogue before N seconds |
| `--speech-to N` | Ignore dialogue after N seconds |

### Captions

| Flag | Default | Notes |
|---|---|---|
| `--fix WRONG=RIGHT` | — | Correct a caption. Repeatable |
| `--font-size` | `38` | |
| `--words-per-caption` | `5` | |
| `--no-subs` | off | Skip captions entirely |

### Encoding

| Flag | Default | Notes |
|---|---|---|
| `--encoder` | `fast` | `fast` = `h264_videotoolbox`, `quality` = libx264 crf 20 |
| `--quality` | `60` | Hardware encoder quality 1-100 |
| `--refresh` | off | Ignore caches, redo analysis and transcription |

### Upload

| Flag | Default |
|---|---|
| `--upload` | off |
| `--privacy` | `private` |
| `--title` / `--description` / `--tags` | derived from transcript |
| `--category` | `24` (Entertainment) |
| `--cleanup` | — passed through to `upload_youtube.py` |

---

## Uploading

`make_short.py --upload` calls `scripts/upload_youtube.py`, which also runs
standalone:

```bash
.venv/bin/python3 scripts/upload_youtube.py \
    --file output/short_480x720.mp4 \
    --title "$(cat output/short_480x720.title.txt)" \
    --description "$(cat output/short_480x720.description.txt)" \
    --tags "$(cat output/short_480x720.tags.txt)" \
    --category 24 --privacy private
```

Privacy defaults to **private** everywhere. Nothing is ever published without
passing `--privacy public` explicitly.

> **Verification caveat.** `token.json` carries only the
> `youtube.upload` scope, so reading a video's status back returns HTTP 403.
> The tool reports what the upload request *set*; it cannot confirm the value
> server-side. Check YouTube Studio if you need certainty.

---

## Cleanup

Three tiers, gated by risk rather than a blind `rm`.

```bash
# safe: regenerable intermediates
--cleanup work

# removes the uploaded video + its own sidecars only
--cleanup output

# refused unless --delete-original is ALSO passed
--cleanup input --delete-original
```

Safety properties:

- Cleanup runs **only if YouTube returned a video id**. A failed upload never
  deletes your source.
- `output` deletes `<stem>.mp4` plus its `.srt` / `.title.txt` /
  `.description.txt` / `.tags.txt` — **never the whole directory**, so other
  renders survive.
- Every path is checked to be inside the project before deletion. Anything
  outside prints `REFUSED`.
- `input` is double-gated because deleting the original is irreversible.

Preview first, always available:

```bash
.venv/bin/python3 scripts/upload_youtube.py --skip-upload \
    --file output/short_480x720.mp4 --title x \
    --cleanup work,output,input --dry-run-cleanup
```

Keeping the four sidecar text files after deleting the `.mp4` is worth it —
they total ~2KB and are what you need to re-upload or fix metadata without
redoing transcription.

---

## Caching and speed

| Operation | Time |
|---|---|
| `--analyze`, cached | ~0.5s |
| Full render, cached transcript | **~8s** |
| First run on a new file | + transcription |
| Encode (60s @ 480x720) | 6.3s — **9.5x realtime** |

`.cache/` holds the transcript, letterbox geometry, and subtitle band, keyed
by a fingerprint of file size, mtime, and head/tail bytes. Deleting it costs
only time. `--refresh` bypasses it.

Two things carry the speed: `h264_videotoolbox` hardware encoding, and never
transcribing the same file twice.

Constant-quality (`-q:v 60`) rather than fixed bitrate keeps files small —
fixed 3 Mbps produced 21.7MB for a 60s clip, `-q:v 60` produces **3.7MB** at
equivalent quality.

---

## Environment constraints

Settled facts about this machine. Worth knowing before trying an alternative
approach that cannot work here.

**This ffmpeg has no text rendering.** No `libass`, no `libfreetype`, so no
`ass`, `subtitles`, or `drawtext` filter. Verify with:

```bash
# prints nothing on this build; note a plain grep for "ass" would
# false-positive on allpass/highpass/bandpass, so match the name column
ffmpeg -hide_banner -filters | awk '$2=="drawtext"||$2=="subtitles"||$2=="ass"'
```

Captions therefore go through Pillow → PNG → `overlay`. Rebuilding ffmpeg
with `--enable-libass` would allow the conventional route, but the PNG path
works and gives full styling control.

**Shorts must be vertical or square.** YouTube will not classify a landscape
video as a Short regardless of duration. `720x480` is landscape; `480x720` is
not. The tool warns when `--size` is landscape but still renders it.

**Whisper mishears names and coined words.** In the test file it produced
"For I am doomed" where the line is "For I am **Doom**" — a meaning-changing
error that reads plausibly. If the source has burned-in subtitles, they are
excellent ground truth; crop a frame and read them:

```bash
ffmpeg -ss 99.7 -i input/my-video.mp4 -frames:v 1 \
    -vf "crop=1280:100:0:522" /tmp/check.png
```

Then correct with `--fix "DOOMED.=DOOM."`.

---

## Troubleshooting

**Burned-in subtitles still visible.** Check the reported band against
reality by cropping a frame at the boundary. Force it manually with
`--keep-subs` off and a tighter source, or report the band and adjust
`detect_burned_subs` thresholds.

**"source has only N seconds of usable material".** `--duration` exceeds
available dialogue plus footage. Lower it.

**Captions flash by too fast.** Raise `--words-per-caption`, or lower
`--font-size` so fewer cards wrap to two lines.

**Faces cut in half.** You are on `--layout crop` with off-centre subjects.
Use `--layout blur`.

**Weak ending.** Whisper may pick up a throwaway line after your climax.
Find it in `--analyze` output and cut it with `--speech-to`.

**Output larger than expected.** Lower `--quality` (hardware encoder) or
switch to `--encoder quality` for libx264, which compresses better but is
~10x slower.

**403 reading video status.** Expected. `token.json` has upload-only scope.


---

## Working with Claude

`CLAUDE.md` tells Claude how to run this pipeline. You mostly don't have to.

### The minimum

```
Make a Short from https://youtu.be/XXXXXXXXXXX
```

Claude fetches it, analyses it, picks the strongest moment, and comes back with
candidates and a recommendation before rendering.

### Word choice picks the format

Say **"short"** (or reel / vertical) and you get 1080x1920 for Shorts. Say
**"make a youtube video"** (or landscape / 16:9) and you get 1920x1080 at the
natural length of the dialogue.

### What Claude decides for you

Which moment to cut, duration, layout, caption handling, title, description and
tags. Override any of it by saying so; otherwise let it choose.

### What only you know

- **Audience language.** The single most useful thing to say upfront. A
  foreign-audio source with burned-in English subs needs `--keep-subs --no-subs`,
  and Claude can only guess at your audience.
- **Whose footage it is.** Third-party clips draw Content ID claims.
- **A moment you already have in mind.** Faster than ranking candidates.
- **Whether to upload, and how public.** Nothing is uploaded unless you ask, and
  never public unless you say the word.

### Iterating

Transcription and geometry are cached, so re-cuts take seconds. Just say what to
change:

```
Start 3 seconds earlier and drop the last line.
Try candidate 2 instead.
Same cut as a youtube video so I can compare.
The caption says "Kargalgan", it should be "Karglgan".
Upload it private with that title.
```

Interrupt any time — the expensive work is already on disk.
