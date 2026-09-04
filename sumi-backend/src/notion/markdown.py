"""Turn Notion's "enhanced markdown" into the markdown the export produced.

Notion's page endpoint returns its own markdown dialect: ordinary markdown
plus HTML-style tags for the things markdown has no syntax for (callouts,
tables, toggles, page mentions). The hand-made export wrote plainer markdown
with different spacing.

The sync normalises to the export's shape for three reasons. Human relevance
judgments are joined by a hash of the chunk's text, so different text orphans
them; `<span>` tags and five-minute signed image URLs are noise to embed; and
the folder the agent greps should read like notes, not like markup.

The rules below are line-based and each one is a row of the table in
`docs/designs/notion-sync.md` §6.4.
"""

import posixpath
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlparse

from src.notion.properties import MONTHS, get_page_title

TAB_WIDTH = 4
# Tags that wrap other blocks; each is closed by </tag> on a later line.
CONTAINER_TAGS = (
    "callout",
    "table",
    "details",
    "columns",
    "column",
    "synced_block",
    "synced_block_reference",
    "meeting-notes",
)
# Wrappers whose children are kept in order and whose own markup goes.
TRANSPARENT_TAGS = ("columns", "column", "synced_block", "synced_block_reference")
# Blocks the export had no form for. Dropped, and counted in the run report.
DROPPED_TAGS = ("table_of_contents", "embed", "unknown", "bookmark", "link_preview")
# Notion's own file host. Its URLs are signed and expire after five minutes,
# so only the file name is worth keeping.
NOTION_FILE_HOST = "prod-files-secure"

PAGE_ID_RE = re.compile(r"([0-9a-fA-F]{32})")
OPEN_TAG_RE = re.compile(r"^<([a-zA-Z_][\w-]*)\b")
SELF_CLOSING_RE = re.compile(r"^<([a-zA-Z_][\w-]*)\b[^>]*/>\s*$")
ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')
ATTRIBUTE_LIST_RE = re.compile(r'\s*\{(?:[\w-]+="[^"]*"\s*)+\}\s*$')
SPAN_RE = re.compile(r"</?span\b[^>]*>")
MENTION_PAGE_RE = re.compile(
    r"<mention-page\b([^>]*?)(?:/>|>(.*?)</mention-page>)", re.DOTALL
)
CHILD_PAGE_RE = re.compile(
    r"<(page|database)\b([^>]*?)(?:/>|>(.*?)</\1>)",
    re.DOTALL,
)
MENTION_DATE_RE = re.compile(r"<mention-date\b([^>]*?)/?>")
MENTION_USER_RE = re.compile(
    r"<mention-user\b([^>]*?)(?:/>|>(.*?)</mention-user>)", re.DOTALL
)
ATTACHMENT_RE = re.compile(
    r"<(file|pdf|video|audio)\b([^>]*?)(?:/>|>(.*?)</\1>)", re.DOTALL
)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
INLINE_EQUATION_RE = re.compile(r"\$`(.+?)`\$")
ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>|~])")
TODO_RE = re.compile(r"^(\s*)[-*] \[([ xX])\]\s*")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")
FENCE_RE = re.compile(r"^\s*```")
EQUATION_FENCE_RE = re.compile(r"^\s*\$\$\s*$")
SUMMARY_RE = re.compile(r"<summary\b[^>]*>(.*?)</summary>", re.DOTALL)
TABLE_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL)
TABLE_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.DOTALL)


@dataclass(frozen=True)
class LinkResolver:
    """Renders a link to another Notion page the way the export wrote it.

    `mirror_paths` and `titles` are keyed by page id (32 hex characters, no
    dashes). `base_dir` is the directory of the page being rendered, relative
    to the mirror root, because the export's links are relative to the file
    that holds them. A page the sync has never seen keeps its title as plain
    text, since there is no file to link to.
    """

    mirror_paths: Mapping[str, str] = field(default_factory=dict)
    titles: Mapping[str, str] = field(default_factory=dict)
    base_dir: str = ""

    def build_link(self, page_id: str, fallback_title: str = "") -> str:
        title = self.titles.get(page_id) or fallback_title or "Untitled"
        path = self.mirror_paths.get(page_id)
        if not path:
            return title
        relative = posixpath.relpath(path, self.base_dir) if self.base_dir else path
        return f"[{title}]({quote(relative)})"


@dataclass(frozen=True)
class Block:
    """One rendered block and whether it is a list item.

    List items sit directly under each other in the export; every other block
    is followed by a blank line.
    """

    lines: tuple[str, ...]
    is_list_item: bool = False


def normalise(
    enhanced: str,
    links: LinkResolver | None = None,
    dropped: Counter[str] | None = None,
) -> str:
    """Enhanced markdown in, the export's markdown out.

    `dropped` collects the tags that had no export form, counted by tag name,
    so a syntax Notion adds later shows up as a number instead of silence.
    """
    resolver = links if links is not None else LinkResolver()
    counter: Counter[str] = Counter() if dropped is None else dropped
    lines = enhanced.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return join_blocks(convert_lines(lines, resolver, counter))


def join_blocks(blocks: Sequence[Block]) -> str:
    out: list[str] = []
    previous_was_list = False
    for index, block in enumerate(blocks):
        if index and not (block.is_list_item and previous_was_list):
            out.append("")
        out.extend(block.lines)
        previous_was_list = block.is_list_item
    return "\n".join(out).strip("\n")


def convert_lines(
    lines: Sequence[str], links: LinkResolver, dropped: Counter[str]
) -> list[Block]:
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            index += 1
            continue
        if stripped == "<empty-block/>":
            blocks.append(Block(("",)))
            index += 1
            continue
        verbatim = FENCE_RE if FENCE_RE.match(raw) else None
        if verbatim is None and EQUATION_FENCE_RE.match(raw):
            verbatim = EQUATION_FENCE_RE
        if verbatim is not None:
            end = find_region_end(lines, index, verbatim)
            blocks.append(Block(tuple(expand_tabs(line) for line in lines[index:end])))
            index = end
            continue
        tag = get_open_tag(stripped)
        if tag in CONTAINER_TAGS:
            end = find_close(lines, index, tag)
            blocks.extend(
                convert_container(tag, lines[index : end + 1], links, dropped)
            )
            index = end + 1
            continue
        if tag in DROPPED_TAGS:
            dropped[tag] += 1
            index += 1
            continue
        if is_quote(stripped):
            end = index
            while end < len(lines) and is_quote(lines[end].strip()):
                end += 1
            quoted = [
                convert_inline(expand_tabs(line), links, dropped)
                for line in lines[index:end]
            ]
            blocks.append(Block((*quoted, "> ")))
            index = end
            continue
        text = convert_inline(expand_tabs(raw), links, dropped)
        if text.strip():
            blocks.append(Block((text,), is_list_item=bool(LIST_ITEM_RE.match(text))))
        index += 1
    return blocks


def convert_container(
    tag: str, region: Sequence[str], links: LinkResolver, dropped: Counter[str]
) -> list[Block]:
    if tag == "meeting-notes":
        dropped[tag] += 1
        return []
    if tag == "table":
        return [build_table(region, links, dropped)]
    inner = get_container_inner(region, tag)
    if tag in TRANSPARENT_TAGS:
        return convert_lines(inner, links, dropped)
    if tag == "callout":
        return [build_callout(region[0], inner, links, dropped)]
    return [build_toggle(region, inner, links, dropped)]


def get_container_inner(region: Sequence[str], tag: str) -> list[str]:
    """The lines a container wraps, with one level of indentation removed."""
    text = "\n".join(region)
    start = text.find(">") + 1
    end = text.rfind(f"</{tag}>")
    inner = text[start:] if end == -1 else text[start:end]
    return dedent(inner.split("\n"))


def build_callout(
    opening: str, inner: Sequence[str], links: LinkResolver, dropped: Counter[str]
) -> Block:
    """The export wrote a callout as an <aside> with its icon on its own line."""
    icon = get_attributes(opening).get("icon", "")
    body = join_blocks(convert_lines(inner, links, dropped))
    lines = ["<aside>"]
    if icon:
        lines.append(icon)
    lines.extend(["", *body.split("\n"), "", "</aside>"])
    return Block(tuple(lines))


def build_table(
    region: Sequence[str], links: LinkResolver, dropped: Counter[str]
) -> Block:
    """A pipe table, with an empty header when Notion says there is no header row.

    A cell can hold anything a line can — a page mention, a date — so its text
    goes through the same inline rules, then onto one line, because a pipe
    table cannot contain a line break.
    """
    text = "\n".join(region)
    rows = [
        [
            " ".join(convert_inline(cell, links, dropped).split())
            for cell in TABLE_CELL_RE.findall(row)
        ]
        for row in TABLE_ROW_RE.findall(text)
    ]
    if not rows:
        return Block(())
    width = max(len(row) for row in rows)
    has_header = get_attributes(region[0]).get("header-row") == "true"
    header = rows[0] if has_header else [""] * width
    body = rows[1:] if has_header else rows
    lines = [format_table_row(header, width), format_table_row(["---"] * width, width)]
    lines.extend(format_table_row(row, width) for row in body)
    return Block(tuple(lines))


def format_table_row(cells: Sequence[str], width: int) -> str:
    padded = list(cells) + [""] * (width - len(cells))
    return "| " + " | ".join(padded) + " |"


def build_toggle(
    region: Sequence[str],
    inner: Sequence[str],
    links: LinkResolver,
    dropped: Counter[str],
) -> Block:
    """A toggle becomes a bullet whose children are indented under it."""
    summary_match = SUMMARY_RE.search("\n".join(region))
    summary = summary_match.group(1).strip() if summary_match else ""
    body = join_blocks(
        convert_lines(SUMMARY_RE.sub("", "\n".join(inner)).split("\n"), links, dropped)
    )
    lines = [f"- {convert_inline(summary, links, dropped)}"]
    if body:
        lines.extend(
            " " * TAB_WIDTH + line if line else "" for line in body.split("\n")
        )
    return Block(tuple(lines), is_list_item=True)


def convert_inline(line: str, links: LinkResolver, dropped: Counter[str]) -> str:
    text = replace_page_mentions(line, links)
    text = replace_date_mentions(text)
    text = MENTION_USER_RE.sub(replace_user_mention, text)
    text = ATTACHMENT_RE.sub(replace_attachment, text)
    text = drop_self_closing_tags(text, dropped)
    text = SPAN_RE.sub("", text)
    text = ATTRIBUTE_LIST_RE.sub("", text)
    text = IMAGE_RE.sub(replace_image, text)
    text = INLINE_EQUATION_RE.sub(r"$\1$", text)
    text = TODO_RE.sub(r"\1- [\2]  ", text)
    return ESCAPE_RE.sub(r"\1", text)


def replace_page_mentions(text: str, links: LinkResolver) -> str:
    def render(attributes_text: str, inner: str | None) -> str:
        title = (inner or "").strip()
        page_id = extract_page_id(get_attributes(attributes_text).get("url", ""))
        return links.build_link(page_id, title) if page_id else title

    text = MENTION_PAGE_RE.sub(lambda m: render(m.group(1), m.group(2)), text)
    return CHILD_PAGE_RE.sub(lambda m: render(m.group(2), m.group(3)), text)


def replace_date_mentions(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        attributes = get_attributes(match.group(1))
        start = attributes.get("start", "")
        if not start:
            return ""
        rendered = format_mention_date(start, attributes.get("startTime", ""))
        return f"@{rendered}"

    return MENTION_DATE_RE.sub(render, text)


def format_mention_date(start: str, start_time: str) -> str:
    year, month, day = (int(part) for part in start[:10].split("-"))
    rendered = f"{MONTHS[month - 1]} {day}, {year}"
    if not start_time:
        return rendered
    hour, minute = (int(part) for part in start_time.split(":")[:2])
    meridiem = "AM" if hour < 12 else "PM"
    return f"{rendered} {hour % 12 or 12}:{minute:02d} {meridiem}"


def replace_user_mention(match: re.Match[str]) -> str:
    name = (match.group(2) or "").strip()
    return f"@{name}" if name else ""


def replace_attachment(match: re.Match[str]) -> str:
    attributes = get_attributes(match.group(2))
    name = get_file_name(attributes.get("src", ""))
    caption = (match.group(3) or "").strip() or attributes.get("alt", "") or name
    return f"[{caption}]({name})" if name else caption


def replace_image(match: re.Match[str]) -> str:
    url = match.group(2)
    if NOTION_FILE_HOST not in url:
        return match.group(0)
    name = get_file_name(url)
    return f"![{name}]({name})" if name else ""


def drop_self_closing_tags(text: str, dropped: Counter[str]) -> str:
    for tag in DROPPED_TAGS:
        pattern = re.compile(rf"<{re.escape(tag)}\b[^>]*/?>(?:.*?</{re.escape(tag)}>)?")
        text, count = pattern.subn("", text)
        if count:
            dropped[tag] += count
    return text


def get_file_name(url: str) -> str:
    return unquote(posixpath.basename(urlparse(url).path))


def extract_page_id(url: str) -> str:
    matches = PAGE_ID_RE.findall(url.replace("-", ""))
    return matches[-1].lower() if matches else ""


def get_attributes(text: str) -> dict[str, str]:
    return dict(ATTRIBUTE_RE.findall(text))


def get_open_tag(stripped: str) -> str:
    match = SELF_CLOSING_RE.match(stripped) or OPEN_TAG_RE.match(stripped)
    return match.group(1) if match else ""


def is_quote(stripped: str) -> bool:
    return stripped == ">" or stripped.startswith("> ")


def expand_tabs(line: str) -> str:
    stripped = line.lstrip("\t")
    depth = len(line) - len(stripped)
    return " " * (TAB_WIDTH * depth) + stripped


def dedent(lines: Iterable[str]) -> list[str]:
    return [
        line[1:]
        if line.startswith("\t")
        else line[TAB_WIDTH:]
        if line.startswith(" " * TAB_WIDTH)
        else line
        for line in lines
    ]


def find_region_end(lines: Sequence[str], start: int, closing: re.Pattern[str]) -> int:
    """One past the line that closes a code fence or a block equation."""
    for index in range(start + 1, len(lines)):
        if closing.match(lines[index]):
            return index + 1
    return len(lines)


def find_close(lines: Sequence[str], start: int, tag: str) -> int:
    open_pattern = re.compile(rf"<{re.escape(tag)}\b(?![^>]*/>)")
    close_pattern = re.compile(rf"</{re.escape(tag)}>")
    depth = 0
    for index in range(start, len(lines)):
        depth += len(open_pattern.findall(lines[index]))
        depth -= len(close_pattern.findall(lines[index]))
        if depth <= 0:
            return index
    return len(lines) - 1


def render_page(page: Mapping[str, object], body: str, property_lines: str = "") -> str:
    """The export's page frame: title heading, property lines, then the body.

    The markdown endpoint may already start the body with the title as a `#`
    heading; when it does, the frame keeps that one rather than adding a
    second.
    """
    title = get_page_title(page)
    heading = f"# {title}"
    body_lines = body.split("\n")
    if body_lines and body_lines[0].strip() == heading:
        body = "\n".join(body_lines[1:]).lstrip("\n")
    parts = [heading, ""]
    if property_lines:
        parts.extend([property_lines, ""])
    parts.append(body)
    # Only newlines are trimmed: the export ends a quote with a "> " line whose
    # trailing space is part of the text the judgments were hashed from.
    return "\n".join(parts).rstrip("\n") + "\n"
