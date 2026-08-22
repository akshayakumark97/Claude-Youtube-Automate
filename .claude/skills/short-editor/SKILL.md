---
name: short-editor
description: Editorial judgement for turning a long source video into a high-retention YouTube Short with scripts/make_short.py. Use whenever asked to make, cut, plan, or pick the best moment for a Short, or when reviewing --analyze output to choose what to keep.
---

# Choosing the Short

Do not ask "what can I trim this down to?" Ask:

> What is the strongest story, surprise, reveal, argument, emotion or piece of
> useful knowledge hidden anywhere in this video — and can a stranger scrolling
> past understand it in three seconds?

The beginning of the source is almost never the beginning of the Short. Greetings,
channel intros, setup and preamble are the first things to go.

## Get the story context first

Before picking a window, understand what's actually happening — don't select a span just
because its transcript happens to be clean or a caption is easy to trust. A dialogue line
read in isolation, without knowing who's talking, what they want, and what's at stake,
tells you nothing about whether it holds a stranger's attention.

Build that context before evaluating candidates:

- Pull whatever metadata is available first — the source's own title and description (for
  a `--url` fetch, the real YouTube title/description, not just the filename), cast,
  genre. This is often enough to tell a scene-setting beat from the actual payoff.
- For a movie/show clip, a quick web search on the title (plot, characters, what the scene
  in question is from) turns a guess into an informed choice — worth doing whenever the
  transcript alone doesn't make the stakes clear, especially for a trailer/glimpse where
  individual lines are fragments of a larger plot.
- Read enough of the surrounding footage (frames, not just the transcript window you're
  considering) to know where a candidate span sits in the story — right before a reveal,
  mid-argument, after the twist — not just whether the audio transcribed cleanly.
- Only after that: judge hook strength, emotion, and payoff against the real story, and
  choose the span that keeps attention because of what's actually happening, not because
  it was the easiest one to caption.

This context also makes titles, descriptions, and thumbnail text sharper — you're
describing what a scene means, not paraphrasing a transcript fragment.

## What the pipeline lets you do

Read the "Behaviour that will surprise you" section of `CLAUDE.md` before proposing
anything. The three constraints that shape editorial choices:

- **One contiguous window.** `--speech-from/--speech-to` is a single span. You cannot
  reorder beats or stitch two moments from different parts of the video. Every candidate
  is a contiguous range, so the hook has to be *inside* the span you pick — you cannot
  lift a great line from 4:12 and paste it in front of a story at 9:30.
- **Exact duration.** Too small and the shortest windows get dropped, punchlines first.
  Too large and you get a musical outro and cold open padding the ends. Size the duration
  to the material.
- **Dialogue-free stretches vanish.** A visually strong but silent moment inside your
  window will be cut unless dialogue brackets it. If the payoff is a wordless reaction,
  make sure a line lands just after it.

## Reading the analyze output

`--analyze` prints every detected line with timestamps, and marks with `X` the ones the
current plan would drop. Work through the whole list before deciding. Look for:

- **Surprise** — an unexpected answer, an outcome nobody set up, a reversal.
- **Curiosity** — an open question, an unexplained situation, a claim that demands a "why".
- **Emotion** — read it from wording, reaction and context, not from volume. A quiet line
  can beat a loud one. If you are inferring, say you are inferring.
- **Humour** — a punchline, an awkward beat, irony, a landed piece of timing.
- **Conflict** — disagreement, a challenge, a mistake, something going wrong.
- **Information** — a fact worth knowing, a clean explanation, a comparison.
- **Transformation** — before/after, a result, a reveal.
- **Story** — problem → attempt → complication → result. A clear payoff is worth more than
  any other single property.

Dialogue density is not a signal. A dense stretch of nothing is still nothing.

## Regional language and emotion

These Shorts are made for Indian audiences across Telugu, Kannada, Hindi, Tamil and other
regional-language sources, not just English. Read emotion, humour and hook strength in the
source language itself — its own idiom, cadence, honorifics and cultural references — never
by mentally translating to English first and scoring the English version. A line that looks
flat translated word-for-word can be the biggest emotional beat in Telugu or Tamil, and a
literal English gloss of a Hindi punchline usually kills the timing that makes it land.

This affects editorial judgement, not just captioning:

- **Emotion and humour read natively.** Sarcasm, affection, scolding-as-love, filmi
  dialogue delivery, and regional comedic timing don't map 1:1 onto English hook patterns.
  Judge the beat the way a native speaker of that language would feel it.
- **Titles, descriptions and tags should match the audience's language and idiom**, not be
  a literal English translation of the transcript. If the source is Telugu, a Telugu (or
  natural code-mixed Telugu-English) title that carries the real emotional hook usually
  outperforms an English gloss — offer the in-language option alongside an English one when
  useful, and say which you'd ship.
- **Whisper still misreads names, brands and numbers** in every one of these languages, often
  worse than in English — verify anything load-bearing against the source before trusting a
  caption, per `CLAUDE.md`.
- **Burned-in subtitles matter here too.** Per `CLAUDE.md`'s non-English guidance, check
  whether the source already carries burned-in translation before assuming Whisper's
  transcription of the spoken language is what should be captioned.
- If you are inferring emotional tone because you don't have native fluency in the specific
  language, say so explicitly rather than presenting a guess as a confident read.
- **Caption policy: English dialogue always gets captions. Regional-language dialogue only
  gets captions if the source has burned-in subtitles to draw from — otherwise render with
  `--no-subs`, full stop.** Do not caption regional dialogue from a Whisper transcript, even
  with `--language` forced to the right code. Whisper hallucinates fluently-readable-looking
  text over music, noise, or uncertain audio in any language, and neither you nor most
  viewers can tell a hallucination from real dialogue in an unfamiliar script — a wrong
  caption there is worse than no caption. `--language` is still worth using to get cleaner
  dialogue-line timing for the cut itself, even when the result won't carry on-screen text.

## The hook

The first 1–3 seconds decide everything. The viewer should think *wait, what?* / *how did
that happen?* / *I need the answer to this.*

Score it 1–10 on surprise, curiosity, clarity, speed and uniqueness. 8+ is worth
rendering; below 6, go find a different span. Never manufacture curiosity the source does
not support.

Because captions are burned in, the hook is read as well as heard — check that the first
caption chunk reads as a hook on its own.

## Duration

Fit the length to the story, never to a round number.

- 15–25s — a reaction, a joke, a single clean reveal
- 25–35s — a short story or a surprising moment
- 35–45s — a strong explanation with a real payoff
- 45–60s — a story that genuinely needs the room
- 60s+ — only when it truly cannot be told shorter

A great 22-second Short beats a padded 55-second one. Then reconcile against the exact-
duration mechanic: estimate the padded length of your selected lines and set `--duration`
near it, so nothing is dropped and nothing is padded.

## Framing

Default to `letterbox` at `1080x1920` — native pixels, plain black fill, no blur pass, so
it renders faster. That default only holds because 1080 sits close to a 1920-wide source's
picture width; if you size down to `480x720` or `720x1280`, letterbox becomes the harshest
crop available and you should switch to `blur` instead.

Only reach for `blur` when the user explicitly asks for a filled/blurred background, or the
output width is much narrower than the source picture width. Don't apply it by default —
the blur pass (split, scale, gblur, overlay) is the slowest part of the filtergraph, and a
plain background is the faster, and now standard, choice.

If letterbox still leaves too much black (a 16:9 source has a short picture band relative
to a 1920-tall canvas) and a fuller, more zoomed frame is wanted, reach for `crop` — not
`fit`. `fit` scales the *entire* source width down to fit, which on a 16:9-ish source
leaves the visible picture occupying only ~25% of the output height with blur/pad filling
the rest; it reads as small and thin on a Short. `crop` fills edge-to-edge with no bars.

Choose `crop` when the subject sits centre-frame — remember it anchors to the top of the
picture and cuts the sides hard on a landscape source. Don't avoid `crop` just to protect a
peripheral on-screen overlay (a character name card, a channel bug); the "never crop away
... on-screen text" rule below is about text that carries the payoff, not incidental
overlays. A full, well-filled vertical frame matters more for retention than saving a name
card at the edge. Still pull a frame at the moment in question to confirm the actual
payoff — a face, the object being demonstrated — survives the crop before finalizing.

Never crop away a face, the hands doing the thing, the object being demonstrated, payoff-
carrying on-screen text (a reveal, a key stat), or the visual payoff. If the moment only
makes sense visually, that outranks a good sentence elsewhere. This does not extend to
incidental overlays — a character name card, a channel bug — which are fine to lose to a
full-bleed `crop`; see "Framing" above.

## Retention pass

Walk the candidate as a viewer, honestly:

- **0–3s** — why does anyone stop scrolling?
- **3–10s** — why do they stay?
- **Middle** — what question is still open?
- **End** — is the payoff delivered, or does it just stop?
- **After** — would this make someone watch a second video from the channel?

Flag the risks before rendering: weak hook, slow setup, too much context, confusing order,
thin payoff, unclear subject, caption overload. If two or more are weak, pick a different
span rather than rendering and hoping.

Context is not optional. A stranger must know who is talking, what is happening and why it
matters. Never trade away meaning for pace.

## Presenting candidates

Offer up to three — best, strong alternative, experimental — then recommend one. Never
dump a dozen options on the user.

```
Candidate:          one line
Window:             --speech-from X --speech-to Y   (contiguous)
Duration:           XXs   (+ why that number fits the material)
Hook:               the actual opening words
Hook score:         X/10
Emotion:            what, and how intense
Story:              two sentences
Payoff:             what the viewer gets
Visual strength:    low / medium / high
Retention risk:     what could go wrong
Layout / size:      blur|crop|letterbox @ WxH   (recommended — see below)
```

Then: three title options, a recommended one, a description, hashtags, tags, and whether a
CTA is warranted.

**Always ask which aspect ratio/size to render at, batched into this same presentation** —
recommend one (per Framing above) but confirm before rendering. Never default to
1080x1920, or any size, silently; this holds even when the rest of the candidate is
otherwise obvious. Duration and layout stay under the normal "ask only when genuinely
unclear" rule — this carve-out is specifically for aspect ratio/size.

## Titles, description, tags — SEO

Titles should be short, specific to what actually happens, and curiosity-driven without
lying. "He Didn't Expect This Answer" is fine *if he didn't*. Skip "Amazing Moment",
"You Won't Believe This", and keyword stuffing.

SEO and curiosity are not in tension — write for both at once:
- Put the highest-value searchable term early in the title: the show/movie/person/topic
  name, not buried after a clever phrase. "KAAKA: [hook]" beats "[hook] — a KAAKA moment."
- Use the terms a fan would actually type into search (movie name, actor/character name,
  franchise number, event name) rather than a vaguer paraphrase, as long as it stays true
  to the clip.
- One idea per title — don't cram multiple keywords in if it stops reading like a title a
  human would click.

Description: front-load it — the first 1–2 lines are what search and suggested-videos
surfaces, so put the searchable specifics (who, what, from where) up top, not buried after
a mood-setting sentence. Relevant keywords used naturally, `#Shorts` included. A handful of
relevant hashtags, not a wall — put the highest-value one first.

Tags: drawn from the topic, subject and niche, ordered highest-value first — title/topic
name, then people, then genre/category terms. Same accuracy bar as everything else: don't
tag a name or claim that isn't actually true of the clip just because it would rank well.

Thumbnail: always pass `--thumbnail --thumbnail-text "SHORT PHRASE"` when rendering — 2-4
words, the same searchable term that leads the title (a name, a topic), not a full
sentence. The pipeline auto-picks the sharpest frame and composites bold text; don't
hand-pick a frame or build a thumbnail outside this flag.

**Rights disclaimer for studio/licensed source material.** When the source is an official
movie/show trailer, glimpse, or other studio-owned footage (not the user's own content),
append a disclaimer to the description, after the normal copy:

```
Disclaimer: All footage and rights belong to [production house / rights holder] and the
makers of [title]. This fan edit is shared for promotional/discussion purposes only. No
copyright infringement intended — contact for removal.
```

Fill in the actual production house/rights holder from what's confirmed during the story-
context research step — never guess a company name. This doesn't guarantee a Content ID
claim won't land (recent, heavily-promoted studio trailers get matched fast, sometimes
within minutes), but it's a reasonable-effort attachment of attribution up front rather
than something bolted on after a block. Once uploaded, the upload-only OAuth scope cannot
edit an existing video's description (`videos.update` fails the same way `delete` and
`list` do) — get the disclaimer in at upload time, not as a follow-up fix.

CTA only when it fits, and never over the hook, the punchline or the payoff. The content is
supposed to be the reason someone subscribes.

## Honesty

Do not fabricate dialogue, reactions or facts. Do not cut context that changes what someone
meant. Do not build controversy that is not in the source. Do not publish a caption you
know to be wrong — verify names, brands and numbers against the source and fix them with
`--fix`. Accuracy outranks retention every time.
