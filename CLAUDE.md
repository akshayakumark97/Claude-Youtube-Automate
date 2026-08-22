# YouTube Shorts factory

Turns a long source video in `input/` into a vertical Short in `output/` — cut to
dialogue, captioned, loudness-normalized, with metadata sidecars and an optional
private upload.

Three scripts do all the work: `scripts/fetch_source.py`, `scripts/make_short.py` and `scripts/upload_youtube.py`.
`README.md` is the full human-facing reference for flags and internals. This file is
only what must never be re-derived or re-litigated.

## Golden rules

1. Never hand-roll ffmpeg, re-probe geometry, or rebuild transcription. The pipeline
   already does it, and faster.
2. Always run `--analyze` before rendering. Never render blind.
3. Claude makes the first editorial call, not the user. Load the `short-editor` skill.
4. Never read, print, or parse anything in `credentials/`.
5. Never delete or overwrite anything in `input/`.
6. Upload is private, and only when the user explicitly asks.

## Environment — settled facts

- This ffmpeg has **no `libass`, no `drawtext`, no `subtitles` filter**. Captions are
  Pillow PNGs fed in as a concat-demuxed second input and composited with `overlay`.
- `h264_videotoolbox` (`--encoder fast`, the default) is ~10x faster than libx264 here.
  `--encoder quality` is libx264 `-preset slow -crf 20`.
- Transcription is `mlx-whisper` with `mlx-community/whisper-large-v3-turbo`, word
  timestamps on.
- Three caches in `.cache/`, keyed by a content fingerprint of the input:
  `<key>.transcript.json`, `<key>.geometry.json`, `<key>.subs.json`. Re-runs are nearly
  free. `--refresh` rebuilds all three; use it only when the input file changed.
- Sources are often letterboxed **and** often carry burned-in subtitles. Both are
  detected and cropped away automatically. Burned-in detection needs numpy — without it
  it silently reports "none found".
- "Silence removal" here means removing dialogue-free stretches. `silencedetect` is
  useless on this material because trailers carry continuous music.
- The source must have an audio track or the script exits.
- Whisper misreads names, brands, coined words and numbers. Verify anything load-bearing
  against the source and correct it with `--fix`.
- `work/` is created on demand. `thumbnails/` is not touched by any script.
- Default layout for `--mode short` is `letterbox` — native pixels, plain black fill, **no
  blur pass** — because that's faster to render. `--layout blur` is opt-in: use it only when
  a blurred/filled background is explicitly wanted, or the output is much narrower than the
  source picture width (where letterbox becomes the harshest crop instead).
- Default caption size for `--mode short` is `64px` (down from an earlier `84px` — it read as
  too large on 1080x1920).
- These Shorts are made for Indian audiences across Telugu, Kannada, Hindi, Tamil and other
  regional languages, not just English. Editorial judgement (emotion, humour, hook strength)
  must be read natively in the source language, and titles/descriptions/tags should match the
  audience's language and idiom rather than a literal English translation. See the
  `short-editor` skill's "Regional language and emotion" section.
- Sources arrive either already in `input/` or via `--url`, which wraps yt-dlp
  (`scripts/fetch_source.py`). It prefers H.264+AAC MP4, caps at 1080p, and reuses a
  file already in `input/`. Dependencies are pinned in `requirements.txt`.

## Two delivery modes

The user's wording picks the mode. Take it literally.

| They say | Mode | Output |
|---|---|---|
| "short", "shorts", "reel", "vertical" | `--mode short` (default) | 1080x1920, `letterbox`, duration 60 |
| "youtube video", "video", "landscape", "16:9" | `--mode video` | 1920x1080, `crop`, duration `auto` |

A preset only fills a flag the caller left alone, so any explicit `--size`,
`--layout`, `--duration`, `--font-size` or `--words-per-caption` still wins. Output
lands in `output/<mode>_<W>x<H>.mp4`.

`--mode video` uses `crop`, which for a 16:9 source is a 1:1 passthrough — nothing
cropped, nothing upscaled. It pairs with `--duration auto`, the natural length of the
dialogue once dead air is gone, because a long-form cut should run as long as it needs
to rather than snapping to 60 seconds. `auto` works in either mode.

Never hand a landscape render to Shorts, and never make a "youtube video" vertical.

## Behaviour that will surprise you

Four mechanics decide whether a render comes out the way you intended.

**`--duration` is an exact length, not a ceiling.** `build_plan` produces precisely that
many seconds or exits. It starts from one window per dialogue line (padded 0.35s before,
0.40s after; windows within 0.25s merge), then:

- *Over target* → pads shrink, then whole windows are dropped **shortest-first**. The
  shortest window is often a one-word punchline or reaction. Dropped lines are printed —
  read that list every time.
- *Under target* → the tightest inter-line gaps re-open first (dramatic rhythm returns,
  long dead air stays out), then leftover budget extends the tail into a musical outro,
  then the head into a cold open.
- *Still leftover* → hard exit: `source has only Xs of usable material; lower --duration`.

So choose a duration close to the natural padded length of the dialogue you selected.
Estimate it from `--analyze`: sum of the line lengths, plus ~0.75s per line.

**`--speech-from` / `--speech-to` select ONE contiguous window.** Lines are kept only if
fully inside it (`start >= from and end <= to`). There is no way to reorder moments and
no way to stitch two separate regions. Every candidate must be a single contiguous span.
The Short is not the window itself — it is that window's dialogue with the dialogue-free
stretches removed, then fitted to exactly `--duration`.

**Layouts are not what their names suggest:**

- `letterbox` (default for `--mode short`) — a **native-pixel slice exactly `--size`
  wide**, not a scale-to-fit, padded with plain black — no blur pass, so it's the fastest
  layout to render. From a 1920-wide source at 480x720 you keep 25% of the frame width. It
  only preserves the original composition when the output width is near the source picture
  width (e.g. 1080x1920 from 1920x1080, the default). At small sizes (480x720, 720x1280) it
  is the most aggressive crop of the three — use `blur` there instead.
- `blur` — ~3:2 centre crop, scaled to full output width, seated slightly above centre over
  a blurred, darkened copy of itself. At 480x720 the picture band is roughly y=123-445 and
  captions sit at y~583, i.e. on the blur, never over faces. Opt-in: pick it explicitly when
  a filled/blurred background is wanted, or at output sizes where letterbox crops too hard.
- `crop` — centre crop to the output aspect, anchored to the **top** of the picture area,
  full bleed. Fills the frame, cuts the sides hard on landscape sources.

**Captions have no CJK, Cyrillic, Arabic or Indic glyphs in the Latin faces**, and a
missing glyph renders as a hollow tofu box with no warning. `pick_font` switches to
Arial Unicode automatically for non-Latin text and logs which face it used — check that
line whenever the transcript language is not English. Verified: Arial Unicode.ttf has real
glyph coverage (not tofu) for Devanagari (Hindi), Tamil, Telugu and Kannada, so a
Whisper transcript in any of those scripts captions correctly without a font change. Stroke
width, line gap and side margin all scale from the font size and output width, so the
480x720 look is preserved at 1080x1920.

**`--output` defaults to `output/<mode>_<W>x<H>.mp4` and overwrites silently.** Pass
`--output` whenever keeping more than one cut at the same size.

Captions: uppercase, ~5 words per chunk, sized per `--mode` (64px short / 56px video,
overridable with `--font-size`), centred at 81% of output height with shadow and dark
stroke. `--fix WRONG=RIGHT` is case-insensitive and repeatable.

Audio: always highpass → EQ → compressor → limiter → two-pass `loudnorm` to −14 LUFS,
with a 0.6s fade on picture and sound at the end.

Sidecars written beside the video: `.srt`, `.title.txt`, `.description.txt`, `.tags.txt`.
Without `--title`/`--description` they are auto-filled with the first 70/400 characters of
the transcript. Never ship that — always pass real metadata.

**A non-English source is usually captioned by its burned-in subtitles, and the
default render throws them away.** Fansub and re-upload sources often pair foreign
audio with burned-in English text; step 3 detects that band and crops above it, then
step 5 burns in Whisper's transcription of the *spoken* language. The result is
unreadable for the intended audience. Whenever the transcript language is not English:
pull a frame from the subtitle band and look at it before choosing. If the burned-in
text is the only translation, render with `--keep-subs --no-subs` at `720x1280` —
`blur` keeps the full frame width so the lines survive, whereas `crop` slices a narrow
centre column and cuts the text off at both ends, and `480x720` shrinks it to roughly
15px.

## Flags

`README.md` has the full reference; `--help` is the authority if this drifts. Do not
invent flags. Notable ones beyond the obvious:

```
--url                  fetch the source from a link into input/ (instead of --input)
--max-height           cap the --url download resolution, default 1080
--force-download       refetch even if the file is already in input/
--mode short|video     delivery target; sets size/layout/duration/caption defaults
--duration N|auto      exact seconds, or the natural length of the dialogue
--analyze              report + cut plan, render nothing
--speech-from / --speech-to    the contiguous window (seconds)
--duration             EXACT output length, default 60
--fix WRONG=RIGHT      caption correction, repeatable
--keep-subs            do NOT crop away burned-in subtitles
--no-subs              render no captions of our own
--refresh              ignore all three caches
--quality 1-100        videotoolbox quality, default 60
--title / --description / --tags / --category    metadata (category default 24)
--privacy private|unlisted|public                default private
--publish-at YYYY-MM-DDTHH:MM:SSZ                schedule public release (UTC, must be future); uploads private regardless of --privacy, YouTube flips it public at this time
--cleanup work,output,input                      ignored without --upload
--interactive          blocks on stdin — NEVER use it non-interactively
```

## Workflow

1. **Get the source and analyze it.** Local file:
   `.venv/bin/python3 scripts/make_short.py --input input/VIDEO.mp4 --analyze`
   From a link: swap `--input` for `--url "<link>"`. The first analysis of a new file
   runs a full transcription (a minute or two); every run after that is cached.
   If the transcript language is not English, inspect a subtitle-band frame before
   deciding how to caption.
2. **Pick the mode from what they asked for** (see the table above), then
   **do the editorial work** per the `short-editor` skill: read every line, find the
   strongest contiguous span, offer up to 3 candidates, recommend one with duration,
   layout, size, title, description and tags.
3. **Dry-run the exact cut** before rendering — the same command plus your
   `--speech-from/--speech-to/--duration`, still with `--analyze`. Confirm the kept list
   contains the hook and the payoff, and that nothing important was dropped to fit.
4. **Always ask which aspect ratio/size to render at**, batched with the candidate
   presentation — never default to 1080x1920 (or any size) silently. Beyond that, ask
   again only when two candidates are close or duration/framing is genuinely unclear;
   otherwise proceed.
5. **Render.**
6. **Check the render**: the final probe line reports actual size, duration and file size —
   confirm they match the intent. Read the `.srt` for misheard names. Confirm the first
   caption is the hook, not a fragment of setup.
7. **Upload only when explicitly asked.**

## Upload and privacy

`--upload` shells out to `scripts/upload_youtube.py`. Never build a second OAuth flow and
never ask the user to paste a token.

Default and only safe default is `--privacy private`. Public requires an explicit,
in-conversation confirmation from the user.

The OAuth token carries the `youtube.upload` scope only, so it **cannot read a video's
status back**. Report what the request set — "upload request completed with
privacyStatus=private" — never "I verified the video is private on YouTube."

## File safety

- `input/` holds the originals. Never delete, never overwrite. `--cleanup input` also
  requires `--delete-original`; do not pass it without an explicit instruction.
- `output/` renders and sidecars · `work/` intermediates, safe to remove · `.cache/`
  transcription and geometry, removing it costs a full re-transcribe.
- Never copy anything from `credentials/` into `output/`, `work/`, `.cache/`, or a commit.

## Credentials — absolute

`credentials/client_secret.json` and `credentials/token.json` must never be read, printed,
parsed, copied, summarized or quoted — not with `cat`/`head`/`less`/`jq`, not through
Python or Node, not to debug an authentication failure. The existence of the file is not
permission to open it.

Never emit access tokens, refresh tokens, client secrets, API keys, auth headers or
cookies into chat, logs, generated files, video titles, descriptions, tags, or commits.

If a secret appears in any output: stop, do not repeat it, tell the user, recommend
rotating it, and do not commit or upload it.

If authentication fails, report the non-sensitive error and the next safe action.

## Never

Fabricate dialogue or reactions · splice or reorder to change meaning · cut context that
changes what a speaker meant · ship captions known to be wrong · use deceptive clickbait ·
pad a Short to reach 60 seconds · publish publicly without explicit confirmation.
