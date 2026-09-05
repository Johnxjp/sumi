import pytest

from src.notion.properties import (
    flatten_properties,
    format_datetime,
    format_property_lines,
    get_page_title,
    get_property_text,
)


def text_runs(text: str) -> list[dict]:
    return [{"type": "text", "plain_text": text}]


@pytest.mark.parametrize(
    ("prop", "expected"),
    [
        ({"type": "title", "title": text_runs("A note")}, ""),
        ({"type": "created_time", "created_time": "2026-04-02T12:39:07.000Z"}, None),
        (
            {"type": "last_edited_time", "last_edited_time": "2026-04-02T12:39:07Z"},
            None,
        ),
        ({"type": "date", "date": {"start": "2026-05-24"}}, "May 24, 2026"),
        ({"type": "date", "date": None}, ""),
        ({"type": "select", "select": {"name": "Daily"}}, "Daily"),
        ({"type": "select", "select": None}, ""),
        ({"type": "status", "status": {"name": "In progress"}}, "In progress"),
        (
            {"type": "multi_select", "multi_select": [{"name": "a"}, {"name": "b"}]},
            "a, b",
        ),
        ({"type": "checkbox", "checkbox": True}, "Yes"),
        ({"type": "checkbox", "checkbox": False}, "No"),
        ({"type": "number", "number": 22}, "22"),
        ({"type": "number", "number": 22.0}, "22"),
        ({"type": "number", "number": 1.5}, "1.5"),
        ({"type": "url", "url": "https://example.com"}, "https://example.com"),
        ({"type": "email", "email": "a@b.com"}, "a@b.com"),
        ({"type": "phone_number", "phone_number": "+44 1"}, "+44 1"),
        ({"type": "rich_text", "rich_text": text_runs("some prose")}, "some prose"),
        (
            {"type": "people", "people": [{"name": "John"}, {"name": "Ada"}]},
            "John, Ada",
        ),
        ({"type": "files", "files": [{"name": "deck.pdf"}]}, "deck.pdf"),
        (
            {"type": "formula", "formula": {"type": "string", "string": "done"}},
            "done",
        ),
        (
            {"type": "formula", "formula": {"type": "boolean", "boolean": True}},
            "Yes",
        ),
        ({"type": "formula", "formula": {"type": "number", "number": 3}}, "3"),
        ({"type": "rollup", "rollup": {"type": "number", "number": 3}}, "3"),
        (
            {
                "type": "rollup",
                "rollup": {
                    "type": "array",
                    "array": [
                        {"type": "select", "select": {"name": "x"}},
                        {"type": "select", "select": {"name": "y"}},
                    ],
                },
            },
            "x, y",
        ),
        ({"type": "created_by", "created_by": {"name": "John"}}, ""),
    ],
    ids=[
        "title-is-the-heading-not-a-line",
        "created-time",
        "last-edited-time",
        "date-without-a-time",
        "empty-date",
        "select",
        "empty-select",
        "status",
        "multi-select",
        "checkbox-true",
        "checkbox-false",
        "whole-number",
        "float-that-is-whole",
        "fractional-number",
        "url",
        "email",
        "phone",
        "rich-text",
        "people",
        "files",
        "formula-string",
        "formula-boolean",
        "formula-number",
        "rollup-number",
        "rollup-array",
        "unsupported-type-is-dropped",
    ],
)
def test_get_property_text_per_type(prop, expected):
    if expected is None:
        expected = "April 2, 2026 1:39 PM"
    assert get_property_text(prop) == expected


def test_relation_reads_titles_from_the_object_table():
    prop = {"type": "relation", "relation": [{"id": "p1"}, {"id": "unknown"}]}
    assert get_property_text(prop, {"p1": "Career"}) == "Career"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-04-02T12:39:07.000Z", "April 2, 2026 1:39 PM"),
        ("2026-01-02T12:39:07.000Z", "January 2, 2026 12:39 PM"),
        ("2026-08-01T23:00:00.000Z", "August 2, 2026 12:00 AM"),
        ("2026-12-25T00:30:00.000Z", "December 25, 2026 12:30 AM"),
        ("2026-05-24", "May 24, 2026"),
        ("", ""),
    ],
    ids=[
        "summer-time-shifts-the-hour",
        "winter-keeps-utc",
        "late-utc-evening-is-the-next-london-day",
        "midnight-reads-as-twelve",
        "date-only",
        "empty",
    ],
)
def test_format_datetime_renders_in_london(value, expected):
    assert format_datetime(value) == expected


def test_flatten_properties_keeps_dates_as_iso_and_drops_empties():
    page = {
        "properties": {
            "Name": {"type": "title", "title": text_runs("Caring")},
            "Created": {"type": "created_time", "created_time": "2026-05-28T02:23:00Z"},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "Daily"}]},
            "Notes": {"type": "rich_text", "rich_text": []},
        }
    }
    assert flatten_properties(page) == {
        "Created": "2026-05-28T02:23:00Z",
        "Tags": "Daily",
    }


def test_format_property_lines_follows_the_schema_order():
    properties = {
        "Category": {"type": "select", "select": {"name": "Daily"}},
        "Created time": {
            "type": "created_time",
            "created_time": "2026-08-01T00:00:00+01:00",
        },
        "Name": {"type": "title", "title": text_runs("Daily Check In")},
        "Empty": {"type": "select", "select": None},
    }

    lines = format_property_lines(properties, ["Name", "Created time", "Category"])

    assert lines == "Created time: August 1, 2026 12:00 AM\nCategory: Daily"


def test_format_property_lines_appends_columns_missing_from_the_schema():
    properties = {
        "Extra": {"type": "select", "select": {"name": "x"}},
        "Category": {"type": "select", "select": {"name": "Daily"}},
    }
    assert format_property_lines(properties, ["Category"]) == (
        "Category: Daily\nExtra: x"
    )


def test_format_property_lines_without_a_schema_keeps_the_json_order():
    properties = {
        "B": {"type": "select", "select": {"name": "b"}},
        "A": {"type": "select", "select": {"name": "a"}},
    }
    assert format_property_lines(properties) == "B: b\nA: a"


def test_pages_without_properties_have_no_lines():
    assert format_property_lines({}) == ""
    assert flatten_properties({}) == {}


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        ({"properties": {"Name": {"type": "title", "title": text_runs("A")}}}, "A"),
        ({"title": text_runs("A database")}, "A database"),
        ({"properties": {}}, ""),
    ],
    ids=["from-the-title-property", "from-a-database-object", "untitled"],
)
def test_get_page_title(page, expected):
    assert get_page_title(page) == expected
