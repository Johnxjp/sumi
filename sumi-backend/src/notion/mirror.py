"""The folder of markdown files the agent's read_file, list_dir and grep read.

The mirror is derived, never edited in place: every page's normalised text
lives in the `notion_objects` table, and each run writes the whole folder
afresh and swaps it in. Regenerating 2,329 files takes about 0.2 s, which
buys the removal of all rename, move and delete bookkeeping — a page that
moved simply lands in its new place, and a deleted one is not written.

The layout copies the export's, so paths stay readable and the links the
normaliser writes between pages resolve.
"""

import posixpath
import re
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

# The characters the export stripped from a title before using it as a name.
UNSAFE_CHARACTERS = re.compile(r'[/\\:*?"<>|]')
FALLBACK_TITLE = "Untitled"
STAGING_SUFFIX = ".tmp"
PREVIOUS_SUFFIX = ".old"


def sanitise_title(title: str) -> str:
    """A title as a file or directory name, as the export wrote it."""
    cleaned = " ".join(UNSAFE_CHARACTERS.sub("", title).split())
    return FALLBACK_TITLE if cleaned in ("", ".", "..") else cleaned


def build_short_id(page_id: str) -> str:
    """The export's tie-breaker for two sibling directories of the same name."""
    return f"{page_id[:4]}-{page_id[-4:]}"


def build_mirror_path(title: str, page_id: str, parent_dir: str = "") -> str:
    """A page's markdown file inside the mirror, relative to the mirror root.

    The 32-hex page id is part of the file name, exactly as in the export, so
    two notes with the same title never collide.
    """
    name = f"{sanitise_title(title)} {page_id}.md"
    return posixpath.join(parent_dir, name) if parent_dir else name


def build_child_dir(
    title: str,
    page_id: str,
    parent_dir: str = "",
    sibling_titles: Sequence[str] = (),
) -> str:
    """The directory holding a page's own child pages.

    `sibling_titles` is every title under the same parent, this page's
    included; when the same title appears twice the directory takes the
    short-id suffix, which is what the export did.
    """
    safe = sanitise_title(title)
    collides = [sanitise_title(other) for other in sibling_titles].count(safe) > 1
    name = f"{safe} {build_short_id(page_id)}" if collides else safe
    return posixpath.join(parent_dir, name) if parent_dir else name


def regenerate_mirror(rows: Iterable[tuple[str, str]], data_dir: Path | str) -> int:
    """Write every page into a fresh folder and swap it in. Returns the count.

    Writing beside the mirror and renaming means a reader never sees a
    half-written folder, and an interrupted run leaves the old one in place.
    """
    target = Path(data_dir)
    staging = target.with_name(target.name + STAGING_SUFFIX)
    previous = target.with_name(target.name + PREVIOUS_SUFFIX)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(previous, ignore_errors=True)
    staging.mkdir(parents=True)

    written = 0
    for mirror_path, markdown in rows:
        path = staging.joinpath(mirror_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = markdown if markdown.endswith("\n") else f"{markdown}\n"
        path.write_text(text, encoding="utf-8")
        written += 1

    if target.exists():
        target.rename(previous)
    staging.rename(target)
    shutil.rmtree(previous, ignore_errors=True)
    return written
