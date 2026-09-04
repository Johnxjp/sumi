import pytest

from src.notion.mirror import (
    build_child_dir,
    build_mirror_path,
    extract_page_id,
    regenerate_mirror,
    sanitise_title,
)

PAGE_ID = "2abd52d026fc80f58efef0d149aa57d0"
OTHER_ID = "3b5d52d026fc80f58efef0d149aa4a24"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Job Hunt 2025-2026", "Job Hunt 2025-2026"),
        ("Work/Life: balance", "WorkLife balance"),
        ('Why? *this* <one> | "that"', "Why this one that"),
        ("  spaced   out  ", "spaced out"),
        ("", "Untitled"),
        ("   ", "Untitled"),
        ("..", "Untitled"),
        ("///", "Untitled"),
    ],
    ids=[
        "plain-title",
        "slashes-and-colons-go",
        "every-unsafe-character-goes",
        "whitespace-collapses",
        "empty-title",
        "blank-title",
        "a-title-that-would-escape-the-folder",
        "a-title-that-sanitises-to-nothing",
    ],
)
def test_sanitise_title(title, expected):
    assert sanitise_title(title) == expected


@pytest.mark.parametrize(
    ("parent_dir", "expected"),
    [
        ("", f"Job Hunt {PAGE_ID}.md"),
        ("Life OS/Career", f"Life OS/Career/Job Hunt {PAGE_ID}.md"),
    ],
    ids=["at-the-root", "under-its-ancestors"],
)
def test_build_mirror_path(parent_dir, expected):
    assert build_mirror_path("Job Hunt", PAGE_ID, parent_dir) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (f"Journal/Take responsibility {PAGE_ID}.md", PAGE_ID),
        (f"Take responsibility {PAGE_ID}", PAGE_ID),
        (f"../data/notion-export-markdown/Journal/a {PAGE_ID}.md", PAGE_ID),
        (f"Note {PAGE_ID.upper()}.md", PAGE_ID),
        ("Journal/Untitled 3b5d-4a24/career-direction.md", ""),
        ("", ""),
    ],
    ids=[
        "an-export-path",
        "no-extension",
        "a-full-path-with-a-prefix",
        "uppercase-is-normalised",
        "an-uploaded-file-has-no-id",
        "empty",
    ],
)
def test_extract_page_id(name, expected):
    assert extract_page_id(name) == expected


def test_build_child_dir_uses_the_plain_title_when_it_is_unique():
    assert build_child_dir("Journal", PAGE_ID, "Life OS", ["Journal", "Career"]) == (
        "Life OS/Journal"
    )


def test_two_siblings_with_the_same_title_get_the_short_id_suffix():
    assert build_child_dir(
        "Untitled", OTHER_ID, "Journal", ["Untitled", "Untitled"]
    ) == ("Journal/Untitled 3b5d-4a24")


def test_a_page_with_no_siblings_listed_keeps_its_plain_title():
    assert build_child_dir("Journal", PAGE_ID) == "Journal"


def test_regenerate_mirror_writes_every_page(tmp_path):
    mirror = tmp_path / "notion-mirror"
    rows = [
        (f"Journal/Caring {PAGE_ID}.md", "# Caring\n\nbody"),
        (f"Notes {OTHER_ID}.md", "# Notes\n\nbody\n"),
    ]

    assert regenerate_mirror(rows, mirror) == 2
    assert (mirror / f"Journal/Caring {PAGE_ID}.md").read_text() == "# Caring\n\nbody\n"
    assert (mirror / f"Notes {OTHER_ID}.md").read_text() == "# Notes\n\nbody\n"


def test_regenerating_replaces_the_previous_folder(tmp_path):
    mirror = tmp_path / "notion-mirror"
    regenerate_mirror(
        [
            (f"Journal/Caring {PAGE_ID}.md", "old text"),
            (f"Gone {OTHER_ID}.md", "deleted since"),
        ],
        mirror,
    )

    regenerate_mirror([(f"Life OS/Caring {PAGE_ID}.md", "new text")], mirror)

    assert (mirror / f"Life OS/Caring {PAGE_ID}.md").read_text() == "new text\n"
    assert not (mirror / f"Journal/Caring {PAGE_ID}.md").exists()
    assert not (mirror / f"Gone {OTHER_ID}.md").exists()


def test_regenerating_leaves_no_staging_or_backup_folder(tmp_path):
    mirror = tmp_path / "notion-mirror"
    regenerate_mirror([(f"Notes {PAGE_ID}.md", "text")], mirror)
    regenerate_mirror([(f"Notes {PAGE_ID}.md", "text")], mirror)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["notion-mirror"]


def test_an_interrupted_previous_run_does_not_block_the_next(tmp_path):
    mirror = tmp_path / "notion-mirror"
    (tmp_path / "notion-mirror.tmp").mkdir()
    (tmp_path / "notion-mirror.tmp" / "half-written.md").write_text("junk")

    regenerate_mirror([(f"Notes {PAGE_ID}.md", "text")], mirror)

    assert sorted(p.name for p in mirror.iterdir()) == [f"Notes {PAGE_ID}.md"]
