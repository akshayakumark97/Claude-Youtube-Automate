#!/usr/bin/env python3
"""Fetch a source video from a link into input/.

Wraps yt-dlp so the rest of the pipeline only ever sees a local file.
Handles page links (YouTube, Vimeo, TikTok, Instagram, ...) and plain
direct file URLs, which yt-dlp's generic extractor also covers.

    fetch_source.py "https://youtu.be/XXXXXXXXXXX"
    make_short.py --url "https://youtu.be/XXXXXXXXXXX" --analyze

Things baked in here so they are not rediscovered:

  * The render pass wants H.264 + AAC in MP4. VP9 and AV1 decode much
    slower through the filter graph, so avc1+m4a is preferred and only
    fallen back on when the site offers nothing else.
  * Above 1080p costs a large download and buys nothing: a Short is at
    most 1080 wide.
  * A file already in input/ is reused, never re-fetched, so repeat runs
    cost nothing. --force overrides.
  * Many fansub re-uploads carry burned-in subtitles. Those are the only
    translation present when the audio is not English, so check a frame
    before letting make_short.py crop them away.
"""

import argparse
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "input")

# avc1 + m4a first; then anything at the height cap; then anything at all.
FORMAT = ("bv*[vcodec^=avc1][height<={h}]+ba[ext=m4a]/"
          "bv*[height<={h}]+ba/"
          "b[height<={h}]/"
          "bv*+ba/b")

VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")


def slugify(text, fallback="source"):
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60].strip("_") or fallback


def _ytdlp():
    """The yt-dlp entry point, or a clear instruction to install it."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise SystemExit(
            "yt-dlp is not installed in this environment.\n"
            f"  install it with:  {sys.executable} -m pip install yt-dlp")
    return [sys.executable, "-m", "yt_dlp"]


def _run(cmd, capture):
    p = subprocess.run(cmd, capture_output=capture, text=True)
    if p.returncode:
        tail = (p.stderr or "")[-1500:] if capture else ""
        raise SystemExit(f"yt-dlp failed (exit {p.returncode})\n{tail}".strip())
    return p


def existing(stem, out_dir):
    for ext in VIDEO_EXTS:
        path = os.path.join(out_dir, stem + ext)
        if os.path.exists(path):
            return path
    return None


def fetch(url, out_dir=INPUT_DIR, max_height=1080, force=False, quiet=False):
    """Download `url` into out_dir. Returns the absolute path to the file."""
    base = _ytdlp()
    os.makedirs(out_dir, exist_ok=True)

    def say(msg):
        if not quiet:
            print(msg, flush=True)

    # Cheap metadata call first: it gives a stable filename, so an already
    # downloaded source can be reused instead of pulled again.
    meta = _run(base + ["--no-playlist", "--skip-download", "--quiet",
                        "--no-warnings", "--print",
                        "%(id)s\t%(title)s\t%(duration)s", url], True)
    line = [ln for ln in meta.stdout.strip().splitlines() if ln][-1]
    vid, title, duration = (line.split("\t") + ["", "", ""])[:3]
    stem = f"{slugify(title)}_{vid}" if title else slugify(vid)

    hit = existing(stem, out_dir)
    if hit and not force:
        say(f"      already downloaded: {os.path.relpath(hit, BASE_DIR)} "
            f"(--force-download to refetch)")
        return os.path.abspath(hit)

    say(f"      {title or url}"
        + (f"  [{float(duration):.0f}s]" if duration.replace('.', '').isdigit()
           else ""))
    _run(base + [
        "--no-playlist", "--newline", "--no-warnings",
        "-f", FORMAT.format(h=max_height),
        "--merge-output-format", "mp4",
        "-o", os.path.join(out_dir, stem + ".%(ext)s"),
        url,
    ], False)

    got = existing(stem, out_dir)
    if not got:
        raise SystemExit(f"download reported success but no file named "
                         f"{stem}.* landed in {out_dir}")
    size = os.path.getsize(got) / 1e6
    say(f"      {os.path.relpath(got, BASE_DIR)}  {size:.1f}MB")
    return os.path.abspath(got)


def main():
    ap = argparse.ArgumentParser(
        description="Download a source video into input/.")
    ap.add_argument("url")
    ap.add_argument("--out-dir", default=INPUT_DIR)
    ap.add_argument("--max-height", type=int, default=1080,
                    help="cap the download resolution (default 1080)")
    ap.add_argument("--force", action="store_true",
                    help="refetch even if the file is already in input/")
    args = ap.parse_args()

    path = fetch(args.url, args.out_dir, args.max_height, args.force)
    print(path)


if __name__ == "__main__":
    main()
