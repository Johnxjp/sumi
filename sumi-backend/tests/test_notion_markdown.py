from collections import Counter

import pytest

from src.notion.markdown import LinkResolver, normalise, render_page

PAGE_ID = "146d52d026fc8065a351fc6e2ea53f8b"
LINKS = LinkResolver(
    mirror_paths={PAGE_ID: f"Life OS/Personal Mission Statement {PAGE_ID}.md"},
    titles={PAGE_ID: "Personal Mission Statement"},
)


@pytest.mark.parametrize(
    ("enhanced", "expected"),
    [
        ("first\nsecond", "first\n\nsecond"),
        ("- one\n- two", "- one\n- two"),
        ("1. one\n2. two", "1. one\n2. two"),
        ("- one\ntext", "- one\n\ntext"),
        ("text\n- one", "text\n\n- one"),
        ("- [ ] task\n- [x] done", "- [ ]  task\n- [x]  done"),
        ("- one\n\tnested", "- one\n\n    nested"),
        ("- one\n\t- nested", "- one\n    - nested"),
        ("para\n<empty-block/>\npara", "para\n\npara"),
        ("> quoted", "> quoted\n> "),
        ("> line one\n> line two", "> line one\n> line two\n> "),
        ("## Heading\ntext", "## Heading\n\ntext"),
        ("---\ntext", "---\n\ntext"),
        ("- item \nnext", "- item\n\nnext"),
        ("paragraph \nnext", "paragraph \n\nnext"),
        ("```plain text\ncode\n```", "```\ncode\n```"),
        ("```python\ncode\n```", "```python\ncode\n```"),
    ],
    ids=[
        "blocks-are-separated-by-a-blank-line",
        "bullets-stay-contiguous",
        "numbered-items-stay-contiguous",
        "a-block-after-a-list-gets-a-blank-line",
        "a-list-after-a-block-gets-a-blank-line",
        "to-dos-get-two-spaces-after-the-bracket",
        "a-tab-becomes-four-spaces",
        "nested-list-items-stay-contiguous",
        "an-empty-block-is-dropped",
        "a-quote-gains-a-trailing-marker-line",
        "a-multi-line-quote-gains-one-marker-line",
        "headings-pass-through",
        "dividers-pass-through",
        "a-list-item-loses-its-trailing-space",
        "a-paragraph-keeps-its-trailing-space",
        "a-plain-text-fence-loses-its-language",
        "a-real-fence-language-is-kept",
    ],
)
def test_block_spacing_and_line_rules(enhanced, expected):
    assert normalise(enhanced) == expected


@pytest.mark.parametrize(
    ("enhanced", "expected"),
    [
        ('<span color="pink">bright</span> text', "bright text"),
        ('<span discussion-urls="https://x">noted</span>', "noted"),
        ('a heading {color="blue"}', "a heading"),
        ('a line {toggle="true" color="red"}', "a line"),
        (r"escaped \* star and \[bracket\]", "escaped * star and [bracket]"),
        ("inline $`x^2`$ maths", "inline $x^2$ maths"),
        ("$$\nx^2\n$$", "$$\nx^2\n$$"),
        ("**bold** and `code`", "**bold** and `code`"),
        ('<mention-user id="u1">Ada</mention-user> replied', "@Ada replied"),
        ('<mention-date start="2026-05-24"/>', "@May 24, 2026"),
        (
            '<mention-date start="2026-05-24" startTime="13:39"/>',
            "@May 24, 2026 1:39 PM",
        ),
        (
            "![](https://prod-files-secure.s3.amazonaws.com/x/Kobe%20run.jpg?X-Amz-Expires=300)",
            "![Kobe run.jpg](Kobe%20run.jpg)",
        ),
        (
            "![alt](https://static01.nyt.com/images/a.png)",
            "![alt](https://static01.nyt.com/images/a.png)",
        ),
        (
            '<file src="https://prod-files-secure.s3.amazonaws.com/x/notes.csv">Notes</file>',
            "[Notes](notes.csv)",
        ),
        (
            '<pdf src="https://prod-files-secure.s3.amazonaws.com/x/deck.pdf"/>',
            "[deck.pdf](deck.pdf)",
        ),
    ],
    ids=[
        "colour-span-is-unwrapped",
        "comment-span-is-unwrapped",
        "trailing-attribute-list-is-removed",
        "several-trailing-attributes-are-removed",
        "backslash-escapes-become-the-character",
        "inline-equations-lose-the-backticks",
        "block-equations-pass-through",
        "bold-and-inline-code-pass-through",
        "a-user-mention-becomes-an-at-name",
        "a-date-mention-becomes-an-at-date",
        "a-date-mention-with-a-time",
        "a-signed-notion-image-keeps-only-its-file-name",
        "an-external-image-is-untouched",
        "an-attachment-becomes-a-link-to-its-name",
        "an-attachment-without-a-caption-uses-its-name",
    ],
)
def test_inline_rules(enhanced, expected):
    assert normalise(enhanced) == expected


@pytest.mark.parametrize(
    "enhanced",
    [
        f'<mention-page url="https://app.notion.com/p/{PAGE_ID}"/>',
        (
            f'<mention-page url="https://www.notion.so/Anything-{PAGE_ID}">'
            "Ignored</mention-page>"
        ),
        (
            f'<page url="https://app.notion.com/p/{PAGE_ID}">'
            "Personal Mission Statement</page>"
        ),
        (
            f'<database url="https://app.notion.com/p/{PAGE_ID}">'
            "Personal Mission Statement</database>"
        ),
    ],
    ids=["mention-self-closing", "mention-with-text", "child-page", "child-database"],
)
def test_page_links_use_the_mirror_path(enhanced):
    assert normalise(enhanced, LINKS) == (
        "[Personal Mission Statement]"
        f"(Life%20OS/Personal%20Mission%20Statement%20{PAGE_ID}.md)"
    )


def test_links_are_relative_to_the_linking_page():
    links = LinkResolver(
        mirror_paths={PAGE_ID: f"Life OS/Career/Job Hunt {PAGE_ID}.md"},
        titles={PAGE_ID: "Job Hunt"},
        base_dir="Life OS",
    )
    assert normalise(
        f'<page url="https://app.notion.com/p/{PAGE_ID}">x</page>', links
    ) == (f"[Job Hunt](Career/Job%20Hunt%20{PAGE_ID}.md)")


def test_a_page_the_sync_has_never_seen_keeps_its_title_as_text():
    unknown = "0" * 32
    assert normalise(
        f'<page url="https://app.notion.com/p/{unknown}">Draft</page>'
    ) == ("Draft")


def test_a_callout_becomes_an_aside():
    enhanced = '<callout icon="\U0001f4a1">\n\tRemember this.\n</callout>'
    assert normalise(enhanced) == ("<aside>\n\U0001f4a1\n\nRemember this.\n\n</aside>")


def test_a_callout_with_several_blocks_keeps_their_spacing():
    enhanced = '<callout icon="\U0001f4a1">\n\tOne.\n\tTwo.\n</callout>'
    assert normalise(enhanced) == ("<aside>\n\U0001f4a1\n\nOne.\n\nTwo.\n\n</aside>")


def test_a_table_becomes_a_pipe_table():
    enhanced = (
        '<table header-row="true">\n'
        "\t<tr><td>Quote</td><td>Page</td></tr>\n"
        "\t<tr><td>Only by relying on oneself</td><td>22</td></tr>\n"
        "</table>"
    )
    assert normalise(enhanced) == (
        "| Quote | Page |\n| --- | --- |\n| Only by relying on oneself | 22 |"
    )


def test_table_cells_go_through_the_inline_rules():
    enhanced = (
        '<table header-row="true">\n'
        "\t<tr><td>Note</td><td>Link</td></tr>\n"
        '\t<tr><td><span color="pink">Coloured</span></td>'
        f'<td><mention-page url="https://app.notion.com/p/{PAGE_ID}"/></td></tr>\n'
        "</table>"
    )

    assert normalise(enhanced, LINKS).splitlines()[-1] == (
        "| Coloured | [Personal Mission Statement]"
        f"(Life%20OS/Personal%20Mission%20Statement%20{PAGE_ID}.md) |"
    )


def test_a_table_without_a_header_row_gets_an_empty_one():
    enhanced = "<table>\n\t<tr><td>a</td><td>b</td></tr>\n</table>"
    assert normalise(enhanced) == "|  |  |\n| --- | --- |\n| a | b |"


def test_a_toggle_becomes_a_bullet_with_indented_children():
    enhanced = "<details><summary>More detail</summary>\n\tHidden text.\n</details>"
    assert normalise(enhanced) == "- More detail\n    Hidden text."


@pytest.mark.parametrize(
    "wrapper", ["columns", "column", "synced_block", "synced_block_reference"]
)
def test_layout_wrappers_are_removed_and_children_kept(wrapper):
    enhanced = f"<{wrapper}>\n\tfirst\n\tsecond\n</{wrapper}>"
    assert normalise(enhanced) == "first\n\nsecond"


def test_nested_columns_keep_every_child():
    enhanced = (
        "<columns>\n"
        "\t<column>\n\t\tleft\n\t</column>\n"
        "\t<column>\n\t\tright\n\t</column>\n"
        "</columns>"
    )
    assert normalise(enhanced) == "left\n\nright"


@pytest.mark.parametrize(
    ("enhanced", "tag"),
    [
        ("before\n<table_of_contents/>\nafter", "table_of_contents"),
        ('before\n<unknown url="https://x" alt="A bookmark"/>\nafter', "unknown"),
        ('before\n<embed url="https://x"/>\nafter', "embed"),
        (
            "before\n<meeting-notes>\n\ttranscript\n</meeting-notes>\nafter",
            "meeting-notes",
        ),
    ],
    ids=["table-of-contents", "unknown-block", "embed", "meeting-notes"],
)
def test_unrenderable_blocks_are_dropped_and_counted(enhanced, tag):
    dropped: Counter[str] = Counter()

    assert normalise(enhanced, dropped=dropped) == "before\n\nafter"
    assert dropped[tag] == 1


def test_a_code_fence_passes_through_untouched():
    enhanced = "```python\nx = [1]  # \\* not an escape\n```\nafter"
    assert (
        normalise(enhanced) == "```python\nx = [1]  # \\* not an escape\n```\n\nafter"
    )


def test_render_page_frames_the_body_like_the_export():
    page = {
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Caring"}]}}
    }
    assert render_page(
        page, "body text", "Created: May 28, 2026 3:23 AM\nTags: Daily"
    ) == ("# Caring\n\nCreated: May 28, 2026 3:23 AM\nTags: Daily\n\nbody text\n")


def test_render_page_omits_property_lines_for_a_plain_page():
    page = {
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Notes"}]}}
    }
    assert render_page(page, "body text") == "# Notes\n\nbody text\n"


def test_render_page_does_not_repeat_a_title_the_body_already_has():
    page = {
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Notes"}]}}
    }
    assert render_page(page, "# Notes\n\nbody text") == "# Notes\n\nbody text\n"


def test_an_uploaded_file_is_linked_inside_the_notes_attachment_folder():
    """The export put a note's uploads in a folder named after the note."""
    links = LinkResolver(attachment_dir="A moodboard for myself")
    enhanced = (
        "![](https://prod-files-secure.s3.amazonaws.com/x/image.png?X-Amz-Expires=300)"
    )
    assert (
        normalise(enhanced, links)
        == "![image.png](A%20moodboard%20for%20myself/image.png)"
    )
