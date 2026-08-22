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

Default to `blur` at `480x720`. Go to `720x1280` when the source is sharp and detail
matters. Never output landscape.

Choose `crop` only when the subject sits centre-frame and losing the sides costs nothing —
remember it anchors to the top of the picture. Choose `letterbox` only at large output
widths; at 480x720 it is the harshest crop available, not a composition-preserving one.

Never crop away a face, the hands doing the thing, the object being demonstrated, on-screen
text, or the visual payoff. If the moment only makes sense visually, that outranks a good
sentence elsewhere.

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
Layout / size:      blur|crop|letterbox @ WxH
```

Then: three title options, a recommended one, a description, hashtags, tags, and whether a
CTA is warranted.

## Titles, description, tags

Titles should be short, specific to what actually happens, and curiosity-driven without
lying. "He Didn't Expect This Answer" is fine *if he didn't*. Skip "Amazing Moment",
"You Won't Believe This", and keyword stuffing.

Description: a sentence or two explaining the moment, relevant keywords used naturally,
`#Shorts` included. A handful of relevant hashtags, not a wall. Tags drawn from the topic,
subject and niche.

CTA only when it fits, and never over the hook, the punchline or the payoff. The content is
supposed to be the reason someone subscribes.

## Honesty

Do not fabricate dialogue, reactions or facts. Do not cut context that changes what someone
meant. Do not build controversy that is not in the source. Do not publish a caption you
know to be wrong — verify names, brands and numbers against the source and fix them with
`--fix`. Accuracy outranks retention every time.
