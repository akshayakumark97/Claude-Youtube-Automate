import argparse
import datetime
import os
import shutil

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_SECRET = os.path.join(
    BASE_DIR,
    "credentials",
    "client_secret.json",
)
TOKEN_FILE = os.path.join(
    BASE_DIR,
    "credentials",
    "token.json",
)

# Sidecars written alongside an edited video, matched by filename stem.
SIDECAR_SUFFIXES = (
    ".srt",
    ".title.txt",
    ".description.txt",
    ".tags.txt",
    ".thumb.jpg",
)

# Directories cleanup is ever allowed to touch, relative to BASE_DIR.
CLEANUP_TARGETS = ("work", "output", "input")


def authenticate():
    credentials = None

    if os.path.exists(TOKEN_FILE):
        credentials = Credentials.from_authorized_user_file(
            TOKEN_FILE,
            SCOPES,
        )

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET,
                SCOPES,
            )
            credentials = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(credentials.to_json())

    return credentials


def upload_video(
    filename,
    title,
    description,
    privacy="private",
    tags=None,
    category_id="22",
    publish_at=None,
    thumbnail=None,
):
    credentials = authenticate()

    youtube = build(
        "youtube",
        "v3",
        credentials=credentials,
    )

    # YouTube only honors publishAt when the video is uploaded private; it
    # flips privacyStatus to public itself at that timestamp.
    effective_privacy = "private" if publish_at else privacy

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": effective_privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    if publish_at:
        request_body["status"]["publishAt"] = publish_at

    if tags:
        request_body["snippet"]["tags"] = tags

    media = MediaFileUpload(
        filename,
        chunksize=-1,
        resumable=True,
        mimetype="video/*",
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media,
    )

    response = None

    while response is None:
        status, response = request.next_chunk()

        if status:
            print(
                f"Upload progress: "
                f"{int(status.progress() * 100)}%"
            )

    print("Upload completed!")
    print(f"https://www.youtube.com/watch?v={response['id']}")

    if thumbnail:
        youtube.thumbnails().set(
            videoId=response["id"],
            media_body=MediaFileUpload(thumbnail, mimetype="image/jpeg"),
        ).execute()
        print("Thumbnail set.")

    if publish_at:
        print(
            f"Scheduled to go public at {publish_at} "
            f"(uploaded as privacyStatus=private until then)."
        )

    return response["id"]


def _inside_base(path):
    """Refuse to touch anything outside the project directory."""
    real = os.path.realpath(path)
    base = os.path.realpath(BASE_DIR)

    return real == base or real.startswith(base + os.sep)


def _remove(path, dry_run):
    if not os.path.exists(path):
        return 0

    if not _inside_base(path):
        print(f"  REFUSED (outside project): {path}")
        return 0

    rel = os.path.relpath(path, BASE_DIR)

    if dry_run:
        print(f"  would remove: {rel}")
        return 1

    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)

    print(f"  removed: {rel}")

    return 1


def cleanup(
    uploaded_file,
    targets,
    work_dir="work",
    delete_original=False,
    dry_run=False,
):
    """Remove build artifacts after a confirmed successful upload.

    'work'   -> intermediates (regenerable): always safe.
    'output' -> only the uploaded video and its own sidecars, never the
                whole directory, so other renders survive.
    'input'  -> the source video. CLAUDE.md rule 7 says never delete the
                original, so this additionally requires delete_original.
    """
    unknown = [t for t in targets if t not in CLEANUP_TARGETS]

    if unknown:
        raise ValueError(
            f"unknown cleanup target(s): {', '.join(unknown)}; "
            f"choose from {', '.join(CLEANUP_TARGETS)}"
        )

    print("\nCleanup" + (" (dry run)" if dry_run else "") + ":")

    removed = 0

    if "work" in targets:
        removed += _remove(
            os.path.join(BASE_DIR, work_dir),
            dry_run,
        )

    if "output" in targets:
        video = os.path.abspath(uploaded_file)
        stem = video[: -len(os.path.splitext(video)[1])]

        removed += _remove(video, dry_run)

        for suffix in SIDECAR_SUFFIXES:
            removed += _remove(stem + suffix, dry_run)

    if "input" in targets:
        if not delete_original:
            print(
                "  SKIPPED input/: CLAUDE.md rule 7 says never delete the "
                "original video.\n"
                "           Pass --delete-original to override this "
                "deliberately."
            )
        else:
            print(
                "  WARNING: deleting the original source video. This is "
                "irreversible\n"
                "           and overrides CLAUDE.md rule 7."
            )
            input_dir = os.path.join(BASE_DIR, "input")

            for name in sorted(os.listdir(input_dir)):
                removed += _remove(
                    os.path.join(input_dir, name),
                    dry_run,
                )

    if not removed:
        print("  nothing to remove")

    return removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--file",
        required=True,
    )

    parser.add_argument(
        "--title",
        required=True,
    )

    parser.add_argument(
        "--description",
        default="",
    )

    parser.add_argument(
        "--privacy",
        choices=["private", "unlisted", "public"],
        default="private",
    )

    parser.add_argument(
        "--publish-at",
        default=None,
        help=(
            "schedule the public release for this UTC time instead of "
            "publishing immediately, e.g. 2026-08-22T12:30:00Z; uploads as "
            "privacyStatus=private and YouTube flips it public at this "
            "timestamp"
        ),
    )

    parser.add_argument(
        "--tags",
        default="",
        help="comma-separated YouTube tags",
    )

    parser.add_argument(
        "--thumbnail",
        help="path to a custom thumbnail image to set after upload",
    )

    parser.add_argument(
        "--category",
        default="22",
        help="YouTube categoryId (24=Entertainment, 1=Film & Animation)",
    )

    parser.add_argument(
        "--cleanup",
        default="",
        help=(
            "comma-separated artifacts to delete after a successful upload: "
            "work,output,input (default: keep everything)"
        ),
    )

    parser.add_argument(
        "--work-dir",
        default="work",
        help="intermediates directory removed by --cleanup work",
    )

    parser.add_argument(
        "--delete-original",
        action="store_true",
        help=(
            "required alongside '--cleanup input' to delete the source "
            "video; overrides CLAUDE.md rule 7"
        ),
    )

    parser.add_argument(
        "--dry-run-cleanup",
        action="store_true",
        help="list what --cleanup would delete without deleting it",
    )

    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="run cleanup only, for a video already uploaded",
    )

    args = parser.parse_args()

    if args.publish_at:
        try:
            when = datetime.datetime.strptime(
                args.publish_at,
                "%Y-%m-%dT%H:%M:%SZ",
            ).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            parser.error(
                "--publish-at must look like 2026-08-22T12:30:00Z (UTC)"
            )

        if when <= datetime.datetime.now(datetime.timezone.utc):
            parser.error("--publish-at must be in the future")

    targets = [t.strip() for t in args.cleanup.split(",") if t.strip()]

    if args.skip_upload:
        if not targets:
            parser.error("--skip-upload requires --cleanup")

        video_id = None
    else:
        video_id = upload_video(
            args.file,
            args.title,
            args.description,
            args.privacy,
            [t.strip() for t in args.tags.split(",") if t.strip()],
            args.category,
            args.publish_at,
            args.thumbnail,
        )

        # Never clean up unless YouTube actually accepted the video.
        if targets and not video_id:
            print("\nUpload did not return a video id; skipping cleanup.")
            targets = []

    if targets:
        cleanup(
            args.file,
            targets,
            args.work_dir,
            args.delete_original,
            args.dry_run_cleanup,
        )
