#!/usr/bin/env python3
"""Turn a long video into a YouTube Short in one command.

Everything this project learned the hard way is baked in here so it never
has to be rediscovered:

  * This ffmpeg has NO libass and NO drawtext, so captions are rendered as
    PNGs with Pillow and composited as a single timed overlay stream.
  * Source videos are often letterboxed AND carry burned-in subtitles.
    Both are detected automatically and cropped away.
  * "Remove silence" means removing dialogue-free stretches. Trailers have
    continuous music, so silencedetect finds nothing useful.
  * h264_videotoolbox is ~10x faster than libx264 preset slow here.
  * Transcription is cached, so re-runs are nearly free.

Quick start:
    make_short.py --url "https://youtu.be/XXXXXXXXXXX" --analyze
    make_short.py --input input/test.mp4 --interactive
    make_short.py --input input/test.mp4 --analyze
    make_short.py --input input/test.mp4 --duration 60 --layout blur --upload
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WORK_DIR = os.path.join(BASE_DIR, "work")

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

# Those faces are bold and read well at speed, but they carry no CJK,
# Cyrillic, Arabic or Indic glyphs — such text comes out as hollow tofu
# boxes with no warning at all. Anything beyond Latin gets a broad-coverage
# face instead, at the cost of a lighter weight.
UNICODE_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
)

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

LAYOUTS = ("blur", "fit", "crop", "letterbox")

# Two delivery targets. A preset only fills a flag the caller left alone, so
# any explicit flag always wins.
#
#   short — 9:16 vertical at the Shorts native size. blur keeps the whole
#           landscape frame (no faces lost) and parks captions on the fill
#           rather than over the picture.
#   video — 16:9 landscape. crop is a 1:1 passthrough for a 16:9 source, so
#           nothing is cropped and nothing is upscaled. Length is 'auto'
#           because a long-form cut should run as long as the dialogue does.
#
# Caption sizes are scaled from the hand-tuned 38px at 480x720: by width for
# vertical, by height for landscape, since a 16:9 frame is wide but no taller.
MODE_PRESETS = {
    "short": {"size": "1080x1920", "layout": "blur", "duration": "60",
              "font_size": 84, "words_per_caption": 5},
    "video": {"size": "1920x1080", "layout": "crop", "duration": "auto",
              "font_size": 56, "words_per_caption": 9},
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def sh(cmd, capture=True, check=True):
    p = subprocess.run(cmd, capture_output=capture, text=True)
    if check and p.returncode:
        sys.stderr.write((p.stderr or "")[-3000:] + "\n")
        raise SystemExit(f"command failed: {' '.join(cmd[:6])}...")
    return p


def say(msg):
    print(msg, flush=True)


def step(n, total, msg):
    say(f"[{n}/{total}] {msg}")


def fingerprint(path):
    """Cheap content key: size + mtime + head/tail bytes."""
    st = os.stat(path)
    h = hashlib.sha1(f"{st.st_size}:{int(st.st_mtime)}".encode())
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if st.st_size > 131072:
            f.seek(-65536, os.SEEK_END)
            h.update(f.read(65536))
    return h.hexdigest()[:16]


def cached(key, builder, force=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(path) and not force:
        with open(path) as f:
            return json.load(f), True
    value = builder()
    with open(path, "w") as f:
        json.dump(value, f)
    return value, False


def hms(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


# --------------------------------------------------------------------------
# 1. probe + geometry detection
# --------------------------------------------------------------------------

def probe(src):
    p = sh([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json", src,
    ])
    d = json.loads(p.stdout)
    st = d["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    has_audio = bool(json.loads(sh([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=index", "-of", "json", src,
    ]).stdout).get("streams"))
    return {
        "width": int(st["width"]),
        "height": int(st["height"]),
        "fps": int(num) / int(den),
        "fps_str": st["r_frame_rate"],
        "duration": float(d["format"]["duration"]),
        "has_audio": has_audio,
    }


def detect_letterbox(src, info):
    """Find the real picture area inside any black bars."""
    err = sh([
        "ffmpeg", "-hide_banner", "-i", src,
        "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-",
    ], check=False).stderr
    votes = {}
    for line in err.splitlines():
        if "crop=" in line:
            c = line.split("crop=")[-1].strip()
            if c.count(":") == 3:
                votes[c] = votes.get(c, 0) + 1
    if not votes:
        return {"x": 0, "y": 0, "w": info["width"], "h": info["height"]}
    best = max(votes, key=votes.get)
    w, h, x, y = (int(v) for v in best.split(":"))
    return {"x": x, "y": y, "w": w, "h": h}


def detect_burned_subs(src, info, picture, speech_times):
    """Locate burned-in subtitle text inside the picture.

    Subtitle rows show a sharp spike in near-white pixel count relative to
    the rest of the frame. Returns (top, bottom) in source coordinates, or
    None when the source carries no burned-in captions.
    """
    try:
        import numpy as np
    except ImportError:
        return None

    times = speech_times[:14] or [info["duration"] * f for f in
                                  (.2, .3, .4, .5, .6, .7, .8)]
    W, H = info["width"], info["height"]
    frames = []
    for t in times:
        buf = subprocess.run([
            "ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", src,
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ], capture_output=True).stdout
        if len(buf) >= W * H:
            frames.append(np.frombuffer(buf[:W * H], np.uint8).reshape(H, W))
    if not frames:
        return None

    a = np.stack(frames).astype(np.int16)
    bright = (a > 205).sum(axis=(0, 2))          # near-white pixels per row

    y0, y1 = picture["y"], picture["y"] + picture["h"]
    split = y0 + int(picture["h"] * 0.55)        # captions live low in frame
    if split >= y1 - 8:
        return None

    # Baseline MUST come from the region being searched. The upper picture is
    # full of bright image content, so using it would set the bar far above
    # the weaker upper line of a two-line caption.
    baseline = float(np.median(bright[split:y1]))
    strong = baseline * 2.2 + 80                 # unmistakable caption row
    soft = baseline * 1.35 + 40                  # faint upper caption lines

    rows = [y for y in range(split, y1) if bright[y] > strong]
    if len(rows) < 4:
        return None

    top, bottom = min(rows), max(rows)
    texty = bright > soft
    hop = 36                                     # tolerated inter-line gap

    def walk(start, direction):
        y = start
        while True:
            nxt = None
            for k in range(1, hop):
                probe_y = y + direction * k
                if not (y0 <= probe_y < y1):
                    break
                if texty[probe_y]:
                    nxt = probe_y
                    break
            if nxt is None:
                return y
            y = nxt

    top = max(y0, walk(top, -1) - 10)            # margin for glyph tops
    bottom = min(y1, walk(bottom, +1) + 6)

    if (bottom - top) > picture["h"] * 0.55:     # implausible: bail out
        return None
    return {"top": top, "bottom": bottom}


# --------------------------------------------------------------------------
# 2. transcription (cached)
# --------------------------------------------------------------------------

def transcribe(src, key, force=False, model=WHISPER_MODEL):
    def build():
        os.makedirs(WORK_DIR, exist_ok=True)
        wav = os.path.join(WORK_DIR, "asr.wav")
        sh(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav])
        import mlx_whisper
        r = mlx_whisper.transcribe(
            wav, path_or_hf_repo=model,
            word_timestamps=True, condition_on_previous_text=False,
        )
        os.remove(wav)
        return {
            "language": r.get("language"),
            "segments": [
                {"start": float(s["start"]), "end": float(s["end"]),
                 "text": s["text"].strip(),
                 "no_speech_prob": float(s.get("no_speech_prob", 0)),
                 "words": [{"w": w["word"].strip(),
                            "s": float(w["start"]), "e": float(w["end"])}
                           for w in (s.get("words") or []) if w["word"].strip()]}
                for s in r["segments"]
            ],
        }
    return cached(key + ".transcript", build, force)


def clean_segments(tr, duration):
    """Drop hallucinated tail segments over music/noise."""
    junk = ("we'll be right back", "thank you", "thanks for watching",
            "subscribe", "bye", "you", "[music]", "♪")
    out = []
    for s in tr["segments"]:
        txt = s["text"].strip()
        low = txt.lower().strip(" .!?")
        if not txt or not s["words"]:
            continue
        if low in junk and s["start"] > duration * 0.6:
            continue
        if s["no_speech_prob"] > 0.6:
            continue
        out.append(s)
    return out


# --------------------------------------------------------------------------
# 3. cut plan
# --------------------------------------------------------------------------

def natural_windows(segments, source_duration,
                    lead=0.35, tail=0.40, stitch=0.25):
    """One padded window per line of dialogue, touching windows merged."""
    if not segments:
        raise SystemExit("no speech found; nothing to cut")

    segs = [[s["start"] - lead, s["end"] + tail] for s in segments]
    owners = [[s] for s in segments]
    segs[0][0] = max(0.0, segs[0][0])
    segs[-1][1] = min(source_duration, segs[-1][1])

    m_segs, m_own = [segs[0]], [owners[0]]
    for s, o in zip(segs[1:], owners[1:]):
        if s[0] <= m_segs[-1][1] + stitch:
            m_segs[-1][1] = max(m_segs[-1][1], s[1])
            m_own[-1] = m_own[-1] + o
        else:
            m_segs.append(s)
            m_own.append(o)
    return m_segs, m_own


def natural_duration(segments, source_duration, **kw):
    """How long the dialogue runs once the dead air is gone.

    This is what --duration auto targets: every line kept, every
    dialogue-free stretch dropped, no padding either way.
    """
    segs, _ = natural_windows(segments, source_duration, **kw)
    return sum(e - s for s, e in segs)


def build_plan(segments, target, source_duration,
               lead=0.35, tail=0.40, stitch=0.25):
    """Keep every line of dialogue, drop the dialogue-free stretches.

    Starts from one padded window per line, then spends the remaining
    budget re-opening the SMALLEST gaps first. That restores the tight
    dramatic beats between lines while leaving the long dead stretches
    on the floor, and it never sacrifices a line to hit the target.
    """
    segs, owners = natural_windows(segments, source_duration,
                                   lead, tail, stitch)

    def total():
        return sum(e - s for s, e in segs)

    dropped = []

    if total() > target:
        over = total() - target
        shrink = min(over / (2 * len(segs)), lead * 0.7, tail * 0.7)
        for s in segs:
            s[0] += shrink
            s[1] -= shrink
        # only now, as a last resort, give up whole windows — quietest first
        while total() > target and len(segs) > 1:
            i = min(range(len(segs)), key=lambda k: segs[k][1] - segs[k][0])
            segs.pop(i)
            dropped.extend(owners.pop(i))
        segs[-1][1] -= total() - target
    else:
        budget = target - total()
        # re-open the tightest gaps first: rhythm back, dead air stays out
        while budget > 0.01 and len(segs) > 1:
            i = min(range(len(segs) - 1),
                    key=lambda k: segs[k + 1][0] - segs[k][1])
            gap = segs[i + 1][0] - segs[i][1]
            if gap > budget:
                break
            segs[i][1] = segs[i + 1][1]
            segs.pop(i + 1)
            owners[i] = owners[i] + owners.pop(i + 1)
            budget -= gap
        # leftover becomes a musical outro, then a longer cold open
        room_end = source_duration - segs[-1][1]
        add = min(budget, room_end)
        segs[-1][1] += add
        budget -= add
        if budget > 0.01:
            add = min(budget, segs[0][0])
            segs[0][0] -= add
            budget -= add
        if budget > 0.01:
            raise SystemExit(
                f"source has only {target - budget:.1f}s of usable material; "
                f"lower --duration")

    segs = [[round(s, 3), round(e, 3)] for s, e in segs]
    if abs(sum(e - s for s, e in segs) - target) > 0.05:
        raise SystemExit(f"could not hit target duration ({total():.3f}s)")

    kept = [ln for group in owners for ln in group]
    return segs, kept, dropped


def remapper(segs):
    def remap(t):
        off = 0.0
        for s, e in segs:
            if t < s:
                return None
            if t <= e:
                return off + (t - s)
            off += e - s
        return None
    return remap


# --------------------------------------------------------------------------
# 4. captions
# --------------------------------------------------------------------------

def caption_events(segments, segs, words_per_chunk=5,
                   min_hold=0.75, max_extra=1.0, gap=0.06, fixes=None):
    remap = remapper(segs)
    chunks = []
    for s in segments:
        ws = s["words"]
        n = max(1, math.ceil(len(ws) / words_per_chunk))
        size = math.ceil(len(ws) / n)
        for i in range(0, len(ws), size):
            chunks.append(ws[i:i + size])

    events = []
    for i, c in enumerate(chunks):
        a, spoken = remap(c[0]["s"]), remap(c[-1]["e"])
        if a is None or spoken is None:
            continue
        b = min(max(spoken, a + min_hold), spoken + max_extra)
        if i + 1 < len(chunks):
            nxt = remap(chunks[i + 1][0]["s"])
            if nxt is not None:
                b = min(b, nxt - gap)
        if b - a < 0.25:
            continue
        txt = " ".join(w["w"] for w in c).upper()
        for wrong, right in (fixes or {}).items():
            txt = txt.replace(wrong.upper(), right.upper())
        events.append({"a": round(a, 3), "b": round(b, 3), "t": txt})
    return events


def pick_font(text):
    """A Latin face when the captions are Latin, a Unicode face otherwise."""
    latin = all(ord(c) < 0x250 for c in text)
    order = FONT_CANDIDATES if latin else (UNICODE_FONT_CANDIDATES
                                           + FONT_CANDIDATES)
    path = next((f for f in order if os.path.exists(f)), None)
    if not path:
        raise SystemExit("no usable font found")
    if not latin:
        say(f"      non-Latin captions: using {os.path.basename(path)}")
    return path


def render_captions(events, size, out_dir, font_size=38, margin=None,
                    line_gap=None, bottom_frac=0.81, stroke=None):
    from PIL import Image, ImageDraw, ImageFont

    font_path = pick_font("".join(e["t"] for e in events))

    W, H = size
    # These were hand-tuned at 38px on a 480-wide frame. Hold those ratios so
    # a 1080- or 1920-wide render looks the same rather than hair-thin.
    if margin is None:
        margin = round(W * 0.092)
    if line_gap is None:
        line_gap = max(2, round(font_size * 0.184))
    if stroke is None:
        stroke = max(2, round(font_size * 0.079))
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    font = ImageFont.truetype(font_path, font_size)
    probe_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_w = W - margin
    bottom = int(H * bottom_frac)

    def wrap(txt):
        lines, cur = [], ""
        for word in txt.split():
            t = (cur + " " + word).strip()
            if probe_draw.textlength(t, font=font) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    asc, desc = font.getmetrics()
    lh = asc + desc + line_gap
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(
        os.path.join(out_dir, "blank.png"))

    widest = 0
    for i, e in enumerate(events):
        lines = wrap(e["t"])
        widest = max(widest, len(lines))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y0 = bottom - len(lines) * lh
        for j, ln in enumerate(lines):
            y = y0 + j * lh
            d.text((W // 2 + 2, y + 3), ln, font=font,
                   fill=(0, 0, 0, 150), anchor="ma")
            d.text((W // 2, y), ln, font=font, fill=(255, 255, 255, 255),
                   stroke_width=stroke, stroke_fill=(8, 8, 8, 235), anchor="ma")
        img.save(os.path.join(out_dir, f"c{i:03d}.png"))
    return widest


def caption_track(events, out_dir, duration, list_path):
    entries, t = [], 0.0
    blank = os.path.join(out_dir, "blank.png")
    for i, e in enumerate(events):
        if e["a"] - t > 1e-4:
            entries.append((blank, e["a"] - t))
        entries.append((os.path.join(out_dir, f"c{i:03d}.png"), e["b"] - e["a"]))
        t = e["b"]
    if duration - t > 1e-4:
        entries.append((blank, duration - t))
    with open(list_path, "w") as f:
        for p, d in entries:
            f.write(f"file '{os.path.abspath(p)}'\nduration {d:.3f}\n")
        f.write(f"file '{os.path.abspath(entries[-1][0])}'\n")
    return len(entries)


def write_srt(events, path):
    def ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    with open(path, "w") as f:
        for i, e in enumerate(events, 1):
            f.write(f"{i}\n{ts(e['a'])} --> {ts(e['b'])}\n{e['t']}\n\n")


# --------------------------------------------------------------------------
# 5. video geometry per layout
# --------------------------------------------------------------------------

def safe_picture(picture, subs):
    """Picture area with any burned-in subtitle band removed."""
    y, h = picture["y"], picture["h"]
    if subs:
        h = max(32, subs["top"] - y)
        note = f"cropped above burned-in subs at y={subs['top']}"
    else:
        note = "no burned-in subtitles detected"
    return {"x": picture["x"], "y": y, "w": picture["w"], "h": h}, note


def even(n):
    return int(n) - (int(n) % 2)


def video_chain(layout, area, out_w, out_h, fps_str, fade_at):
    """Return filtergraph nodes producing [vout] from [vc]."""
    ar = out_w / out_h

    if layout == "crop":
        cw = even(min(area["w"], area["h"] * ar))
        ch = even(min(area["h"], area["w"] / ar))
        cx = area["x"] + even((area["w"] - cw) / 2)
        cy = area["y"]
        nodes = [
            f"[vc]crop={cw}:{ch}:{cx}:{cy},setsar=1,"
            f"scale={out_w}:{out_h}:flags=lanczos,unsharp=5:5:0.4[comp]",
        ]

    elif layout == "letterbox":
        cw = even(min(area["w"], out_w))
        ch = even(area["h"])
        cx = area["x"] + even((area["w"] - cw) / 2)
        pad_y = even((out_h - ch) / 2 * 0.6)
        nodes = [
            f"[vc]crop={cw}:{ch}:{cx}:{area['y']},setsar=1,"
            f"pad={out_w}:{out_h}:{even((out_w - cw) / 2)}:{pad_y}:black[comp]",
        ]

    else:  # blur / fit: soft fill behind the picture, never an upscale
        # blur spends ~20% of the source width to make the picture bigger,
        # which is the right trade for faces and action. fit keeps every
        # pixel instead — necessary whenever the frame carries edge-to-edge
        # information: title cards, on-screen text, wide two-shots.
        cw = even(area["w"] if layout == "fit"
                  else min(area["w"], area["h"] * 1.49))
        ch = even(area["h"])
        cx = area["x"] + even((area["w"] - cw) / 2)
        fg_h = even(out_w * ch / cw)
        top = even((out_h - fg_h) / 2 * 0.62)
        nodes = [
            f"[vc]crop={cw}:{ch}:{cx}:{area['y']},setsar=1,split[m][bg]",
            f"[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},gblur=sigma=24,"
            f"eq=brightness=-0.14:saturation=0.85[bgb]",
            f"[m]scale={out_w}:{fg_h}:flags=lanczos,unsharp=5:5:0.3[fg]",
            f"[bgb][fg]overlay=0:{top}[comp]",
        ]

    nodes += [
        f"[1:v]fps={fps_str},format=rgba[caps]",
        f"[comp][caps]overlay=0:0:eof_action=pass:format=auto,"
        f"fade=t=out:st={fade_at:.3f}:d=0.6,format=yuv420p[vout]",
    ]
    return nodes


ACHAIN = ("highpass=f=55,equalizer=f=180:t=q:w=1.1:g=-1.5,"
          "equalizer=f=3000:t=q:w=0.9:g=2.2,"
          "acompressor=threshold=-18dB:ratio=2.4:attack=8:release=220:makeup=1.6,"
          "alimiter=limit=0.94")


def trim_nodes(segs, fade=0.05):
    vn, an, vl, al = [], [], [], []
    for i, (s, e) in enumerate(segs):
        d = e - s
        vn.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        an.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:st=0:d={fade},"
                  f"afade=t=out:st={d - fade:.3f}:d={fade}[a{i}]")
        vl.append(f"[v{i}]")
        al.append(f"[a{i}]")
    vn.append("".join(vl) + f"concat=n={len(segs)}:v=1:a=0[vc]")
    an.append("".join(al) + f"concat=n={len(segs)}:v=0:a=1[ac]")
    return vn, an


def measure_loudness(src, an):
    fg = ";".join(an + [
        f"[ac]{ACHAIN},loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[out]"])
    err = sh(["ffmpeg", "-y", "-i", src, "-filter_complex", fg,
              "-map", "[out]", "-f", "null", "-"]).stderr
    import re
    m = re.search(r"\{[^{}]*input_i.*?\}", err, re.S)
    return json.loads(m.group(0)) if m else None


# --------------------------------------------------------------------------
# 6. interactive menu
# --------------------------------------------------------------------------

def ask(prompt, options, default=0):
    say(f"\n{prompt}")
    for i, (label, hint) in enumerate(options):
        mark = "*" if i == default else " "
        say(f"  {mark} {i + 1}. {label}" + (f"  — {hint}" if hint else ""))
    raw = input(f"Choose 1-{len(options)} [{default + 1}]: ").strip()
    if not raw:
        return default
    try:
        n = int(raw) - 1
        return n if 0 <= n < len(options) else default
    except ValueError:
        return default


def ask_text(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw or str(default)


def interactive(args, info, subs, speech_total, n_lines):
    say("\n" + "=" * 62)
    say("  SOURCE")
    say("=" * 62)
    say(f"  file       {os.path.relpath(args.input, BASE_DIR)}")
    say(f"  video      {info['width']}x{info['height']} @ "
        f"{info['fps']:.2f}fps, {hms(info['duration'])}")
    say(f"  dialogue   {n_lines} lines, {speech_total:.1f}s of speech")
    say(f"  burned-in  {'YES — will be cropped away' if subs else 'none'}")

    sizes = [("480x720", "portrait 2:3, Short-eligible"),
             ("720x1280", "native Shorts 9:16, sharpest"),
             ("1080x1920", "full HD vertical"),
             ("custom", "type your own WxH")]
    i = ask("Output resolution?", sizes, 0)
    size = ask_text("  Enter WxH", "480x720") if i == 3 else sizes[i][0]

    durs = [("60", "classic Short limit"),
            ("30", "tighter, higher retention"),
            ("45", "middle ground"),
            ("custom", "type seconds")]
    i = ask("Target duration (seconds)?", durs, 0)
    dur = float(ask_text("  Enter seconds", 60) if i == 3 else durs[i][0])

    lays = [("blur", "wide crop + soft fill; keeps faces, no upscale"),
            ("crop", "full-bleed centre crop; fills frame, may cut faces"),
            ("letterbox", "native pixels + black bars; sharpest, narrower")]
    layout = lays[ask("Framing?", lays, 0)][0]

    quals = [("fast", "hardware encode, ~10x faster"),
             ("quality", "libx264 preset slow, smaller file")]
    encoder = quals[ask("Encode speed?", quals, 0)][0]

    ups = [("no", "render only; upload later"),
           ("private", "upload to YouTube as PRIVATE")]
    upload = ups[ask("Upload when done?", ups, 0)][0] != "no"

    return size, dur, layout, encoder, upload


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Make a YouTube Short from a long video.")
    ap.add_argument("--input",
                    help="local source video; omit when using --url")
    ap.add_argument("--url",
                    help="download the source from this link into "
                         "input/ first (see scripts/fetch_source.py)")
    ap.add_argument("--max-height", type=int, default=1080,
                    help="cap --url download resolution (default 1080)")
    ap.add_argument("--force-download", action="store_true",
                    help="refetch --url even if already in input/")
    ap.add_argument("--output")
    ap.add_argument("--mode", choices=tuple(MODE_PRESETS), default="short",
                    help="delivery target: short = 9:16 vertical for "
                         "YouTube Shorts, video = 16:9 landscape")
    ap.add_argument("--duration",
                    help="exact output seconds, or 'auto' for the "
                         "natural length of the dialogue")
    ap.add_argument("--size", help="WxH; defaults per --mode")
    ap.add_argument("--layout", choices=LAYOUTS,
                    help="defaults per --mode")
    ap.add_argument("--encoder", choices=("fast", "quality"), default="fast")
    ap.add_argument("--quality", type=int, default=60,
                    help="hardware encoder quality 1-100 (higher = bigger)")
    ap.add_argument("--interactive", action="store_true",
                    help="menu-driven: pick size, duration, framing, upload")
    ap.add_argument("--analyze", action="store_true",
                    help="print source report and cut plan, render nothing")
    ap.add_argument("--fix", action="append", default=[], metavar="WRONG=RIGHT",
                    help="caption text correction, repeatable")
    ap.add_argument("--speech-from", type=float, default=0.0,
                    help="ignore dialogue before this timestamp")
    ap.add_argument("--speech-to", type=float, default=None,
                    help="ignore dialogue after this timestamp")
    ap.add_argument("--font-size", type=int, help="defaults per --mode")
    ap.add_argument("--words-per-caption", type=int,
                    help="defaults per --mode")
    ap.add_argument("--no-subs", action="store_true",
                    help="skip burning captions")
    ap.add_argument("--keep-subs", action="store_true",
                    help="do NOT crop away burned-in subtitles")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore caches and redo analysis/transcription")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--privacy", default="private",
                    choices=("private", "unlisted", "public"))
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--tags", default="")
    ap.add_argument("--category", default="24")
    ap.add_argument("--cleanup", default="",
                    help="passed through to upload_youtube.py")
    ap.add_argument("--publish-at", default=None,
                    help="passed through to upload_youtube.py")
    args = ap.parse_args()

    for flag, value in MODE_PRESETS[args.mode].items():
        if getattr(args, flag) is None:
            setattr(args, flag, value)

    if args.url:
        if args.input:
            raise SystemExit("pass --input or --url, not both")
        say("[0/7] Fetching source...")
        from fetch_source import fetch
        args.input = fetch(args.url, max_height=args.max_height,
                           force=args.force_download)
    if not args.input:
        raise SystemExit("need --input PATH or --url LINK")

    src = os.path.abspath(args.input)
    if not os.path.exists(src):
        raise SystemExit(f"no such file: {args.input}")

    t_start = time.time()
    key = fingerprint(src)
    TOTAL = 7

    step(1, TOTAL, "Probing source...")
    info = probe(src)
    if not info["has_audio"]:
        raise SystemExit("source has no audio track")

    geo, hit = cached(key + ".geometry",
                      lambda: detect_letterbox(src, info), args.refresh)
    say(f"      {info['width']}x{info['height']} @ {info['fps']:.2f}fps, "
        f"{hms(info['duration'])}   picture {geo['w']}x{geo['h']}"
        f"+{geo['x']}+{geo['y']}" + ("  (cached)" if hit else ""))

    step(2, TOTAL, "Transcribing" + (" (cached)" if os.path.exists(
        os.path.join(CACHE_DIR, key + ".transcript.json"))
        and not args.refresh else " — first run, please wait") + "...")
    tr, hit = transcribe(src, key, args.refresh)
    segments = clean_segments(tr, info["duration"])
    speech = sum(s["end"] - s["start"] for s in segments)
    say(f"      {len(segments)} dialogue lines, {speech:.1f}s of speech "
        f"({tr.get('language')})" + ("  (cached)" if hit else ""))

    step(3, TOTAL, "Detecting burned-in subtitles...")
    if args.keep_subs:
        subs = None
        say("      skipped (--keep-subs)")
    else:
        subs, hit = cached(
            key + ".subs",
            lambda: detect_burned_subs(
                src, info, geo, [s["start"] + 0.6 for s in segments]),
            args.refresh)
        say(f"      {'band y=%d-%d — will crop above it' % (subs['top'], subs['bottom']) if subs else 'none found'}"
            + ("  (cached)" if hit else ""))

    if args.interactive:
        size, args.duration, args.layout, args.encoder, args.upload = \
            interactive(args, info, subs, speech, len(segments))
        args.size = size

    try:
        out_w, out_h = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        raise SystemExit(f"bad --size: {args.size}")
    out_w, out_h = even(out_w), even(out_h)
    if out_w > out_h and args.mode == "short":
        say(f"      NOTE: {out_w}x{out_h} is landscape — YouTube will not "
            f"treat this as a Short. Use --mode video for 16:9.")

    if args.speech_from or args.speech_to is not None:
        hi = args.speech_to if args.speech_to is not None else info["duration"]
        before = len(segments)
        segments = [s for s in segments
                    if s["start"] >= args.speech_from and s["end"] <= hi]
        say(f"      speech range {args.speech_from:.1f}-{hi:.1f}s: "
            f"kept {len(segments)} of {before} lines")

    if isinstance(args.duration, str):
        if args.duration == "auto":
            args.duration = round(
                natural_duration(segments, info["duration"]), 3)
            say(f"      auto duration: {args.duration:.1f}s of dialogue "
                f"once the dead air is gone")
        else:
            try:
                args.duration = float(args.duration)
            except ValueError:
                raise SystemExit(f"bad --duration: {args.duration} "
                                 f"(seconds, or 'auto')")

    step(4, TOTAL, f"Planning cut to exactly {args.duration:.0f}s...")
    segs, kept, dropped = build_plan(segments, args.duration, info["duration"])
    segments = kept
    say(f"      {len(segs)} segments, kept {sum(e - s for s, e in segs):.3f}s, "
        f"removed {info['duration'] - args.duration:.1f}s of dialogue-free "
        f"footage")
    say(f"      dialogue: {len(kept)} lines kept" +
        (f", {len(dropped)} DROPPED to fit" if dropped else ", none dropped"))
    for d in dropped:
        say(f"        dropped: [{d['start']:6.2f}] {d['text'][:70]}")

    if args.analyze:
        say("\n      segment    source range         length")
        for i, (s, e) in enumerate(segs):
            say(f"      {i:>2}        {s:7.2f} -> {e:7.2f}     {e - s:5.2f}s")
        say("\n      every line detected in the source:")
        for ln in sorted(segments + dropped, key=lambda x: x["start"]):
            flag = "  " if ln in segments else "X "
            say(f"      {flag}[{ln['start']:6.2f} -> {ln['end']:6.2f}] "
                f"{ln['text']}")
        say("\n      (X = not in the cut. Use --speech-from/--speech-to to "
            "exclude junk lines,")
        say("       and --fix WRONG=RIGHT to correct a caption.)")
        say(f"\nAnalysis only ({time.time() - t_start:.1f}s). "
            f"Re-run without --analyze to render.")
        return

    area, note = safe_picture(geo, subs)
    say(f"      framing: {args.layout} — {note}")

    step(5, TOTAL, "Rendering captions...")
    os.makedirs(WORK_DIR, exist_ok=True)
    caps_dir = os.path.join(WORK_DIR, "caps")
    fixes = dict(f.split("=", 1) for f in args.fix if "=" in f)
    events = [] if args.no_subs else caption_events(
        segments, segs, args.words_per_caption, fixes=fixes)
    if events:
        lines = render_captions(events, (out_w, out_h), caps_dir,
                                font_size=args.font_size)
        list_path = os.path.join(caps_dir, "list.txt")
        n = caption_track(events, caps_dir, args.duration, list_path)
        say(f"      {len(events)} captions (max {lines} lines), {n} track entries")
    else:
        say("      captions disabled")

    step(6, TOTAL, "Encoding...")
    vn, an = trim_nodes(segs)
    ln = measure_loudness(src, an)
    achain = ACHAIN
    if ln:
        achain += (f",loudnorm=I=-14:TP=-1.5:LRA=11:linear=true:"
                   f"measured_I={ln['input_i']}:measured_TP={ln['input_tp']}:"
                   f"measured_LRA={ln['input_lra']}:"
                   f"measured_thresh={ln['input_thresh']}:"
                   f"offset={ln['target_offset']}")
        say(f"      loudness {ln['input_i']} LUFS -> -14 LUFS")

    fade_at = args.duration - 0.6
    if events:
        vnodes = video_chain(args.layout, area, out_w, out_h,
                             info["fps_str"], fade_at)
    else:
        base = video_chain(args.layout, area, out_w, out_h,
                           info["fps_str"], fade_at)[:-2]
        vnodes = base + [f"[comp]fade=t=out:st={fade_at:.3f}:d=0.6,"
                         f"format=yuv420p[vout]"]

    fg = ";".join(vn + an + vnodes + [
        f"[ac]{achain},afade=t=out:st={fade_at:.3f}:d=0.6,"
        f"aresample=48000[aout]"])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = args.output or os.path.join(
        OUTPUT_DIR, f"{args.mode}_{out_w}x{out_h}.mp4")

    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", "-i", src]
    if events:
        cmd += ["-f", "concat", "-safe", "0", "-i", list_path]
    else:
        fg = fg.replace(f"[1:v]fps={info['fps_str']},format=rgba[caps];", "")
    cmd += ["-filter_complex", fg, "-map", "[vout]", "-map", "[aout]"]
    if args.encoder == "fast":
        # constant-quality beats fixed bitrate here: same look, ~3x smaller
        cmd += ["-c:v", "h264_videotoolbox", "-q:v", str(args.quality),
                "-profile:v", "high", "-realtime", "false"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "20",
                "-profile:v", "high", "-level", "4.0"]
    cmd += ["-pix_fmt", "yuv420p", "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", out]
    t_enc = time.time()
    sh(cmd, capture=False)
    say(f"      encoded in {time.time() - t_enc:.1f}s ({args.encoder})")

    step(7, TOTAL, "Writing sidecars...")
    stem = out[: -len(os.path.splitext(out)[1])]
    if events:
        write_srt(events, stem + ".srt")
    transcript_text = " ".join(s["text"] for s in segments)
    title = args.title or (transcript_text[:70].rsplit(" ", 1)[0] + " #Shorts")
    desc = args.description or (transcript_text[:400] + "\n\n#Shorts")
    for suffix, body in ((".title.txt", title), (".description.txt", desc),
                         (".tags.txt", args.tags)):
        with open(stem + suffix, "w") as f:
            f.write(body + "\n")

    got = probe(out)
    say(f"      {os.path.relpath(out, BASE_DIR)}  "
        f"{got['width']}x{got['height']}  {got['duration']:.2f}s  "
        f"{os.path.getsize(out) / 1e6:.1f}MB")
    say(f"\nDone in {time.time() - t_start:.1f}s.")

    if args.upload:
        say("\nUploading...")
        up = [sys.executable, os.path.join(BASE_DIR, "scripts",
                                           "upload_youtube.py"),
              "--file", out, "--title", title, "--description", desc,
              "--privacy", args.privacy, "--category", args.category]
        if args.tags:
            up += ["--tags", args.tags]
        if args.cleanup:
            up += ["--cleanup", args.cleanup]
        if args.publish_at:
            up += ["--publish-at", args.publish_at]
        sh(up, capture=False)
    elif args.cleanup:
        say(f"(--cleanup ignored without --upload)")


if __name__ == "__main__":
    main()
