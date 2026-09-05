from datetime import UTC, datetime, timedelta

import pytest

from src.notion.sync import (
    NotionObject,
    Place,
    StoredObject,
    build_chunk_metadata,
    build_documents,
    compute_places,
    format_age,
    is_stale,
    parse_object,
    parse_parent,
    plan_run,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
LIFE_OS = "1" * 32
CAREER = "2" * 32
JOB_HUNT = "3" * 32
JOURNAL_DB = "4" * 32
JOURNAL_DS = "5" * 32
JOURNAL_ROW = "6" * 32


def make_page(
    page_id: str,
    title: str = "A page",
    parent_id: str | None = None,
    parent_kind: str = "workspace",
    edited: datetime = NOW,
    in_trash: bool = False,
    kind: str = "page",
) -> NotionObject:
    return NotionObject(
        id=page_id,
        kind=kind,
        title=title,
        parent_id=parent_id,
        parent_kind=parent_kind,
        last_edited_time=edited,
        in_trash=in_trash,
    )


def make_stored(
    page_id: str,
    title: str = "A page",
    path: str = "A page",
    mirror_path: str = "",
    edited: datetime | None = NOW,
    synced: datetime | None = NOW,
    parent_id: str | None = None,
    parent_kind: str = "workspace",
    kind: str = "page",
) -> StoredObject:
    return StoredObject(
        id=page_id,
        kind=kind,
        title=title,
        parent_id=parent_id,
        parent_kind=parent_kind,
        path=path,
        mirror_path=mirror_path or f"{title} {page_id}.md",
        last_edited_time=edited,
        synced_at=synced,
    )


def places_for(pages: list[NotionObject]) -> dict[str, Place]:
    return compute_places({page.id: page for page in pages})


@pytest.mark.parametrize(
    ("parent", "expected"),
    [
        ({"type": "page_id", "page_id": "AB-CD"}, ("abcd", "page")),
        ({"type": "data_source_id", "data_source_id": "ff"}, ("ff", "data_source")),
        ({"type": "database_id", "database_id": "ff"}, ("ff", "database")),
        ({"type": "block_id", "block_id": "ff"}, ("ff", "block")),
        ({"type": "workspace", "workspace": True}, (None, "workspace")),
        (None, (None, "workspace")),
    ],
    ids=["page", "data-source", "database", "block", "workspace", "missing"],
)
def test_parse_parent(parent, expected):
    assert parse_parent(parent) == expected


def test_parse_object_reads_a_listed_page():
    payload = {
        "object": "page",
        "id": "3336-d52d",
        "url": "https://notion.so/x",
        "created_time": "2026-04-02T12:39:07.000Z",
        "last_edited_time": "2026-09-03T08:00:00.000Z",
        "in_trash": False,
        "parent": {"type": "data_source_id", "data_source_id": JOURNAL_DS},
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Caring"}]},
            "Tags": {"type": "multi_select", "multi_select": [{"name": "Daily"}]},
        },
    }

    obj = parse_object(payload)

    assert obj.id == "3336d52d"
    assert obj.title == "Caring"
    assert obj.kind == "page"
    assert obj.parent_id == JOURNAL_DS
    assert obj.parent_kind == "data_source"
    assert obj.created_time == datetime(2026, 4, 2, 12, 39, 7, tzinfo=UTC)
    assert obj.schema_order == []
    assert "Tags" in obj.properties


def test_parse_object_reads_a_data_source_schema_order():
    payload = {
        "object": "data_source",
        "id": JOURNAL_DS,
        "title": [{"plain_text": "Journal"}],
        "parent": {"type": "database_id", "database_id": JOURNAL_DB},
        "properties": {"Name": {}, "Created": {}, "Tags": {}},
    }

    obj = parse_object(payload)

    assert obj.title == "Journal"
    assert obj.schema_order == ["Name", "Created", "Tags"]
    assert obj.properties == {}


def test_parse_object_treats_archived_as_trashed():
    assert parse_object({"id": "a", "archived": True}).in_trash is True


def test_compute_places_follows_parent_pointers_up():
    pages = [
        make_page(LIFE_OS, "Life OS"),
        make_page(CAREER, "Career", LIFE_OS, "page"),
        make_page(JOB_HUNT, "Job Hunt 2025-2026", CAREER, "page"),
    ]

    places = places_for(pages)

    assert places[JOB_HUNT].path == "Life OS / Career / Job Hunt 2025-2026"
    assert places[JOB_HUNT].mirror_path == (
        f"Life OS/Career/Job Hunt 2025-2026 {JOB_HUNT}.md"
    )
    assert places[JOB_HUNT].parent_dir == "Life OS/Career"


def test_the_data_source_level_is_skipped_in_a_path():
    pages = [
        make_page(LIFE_OS, "Life OS"),
        make_page(JOURNAL_DB, "Journal", LIFE_OS, "page", kind="database"),
        make_page(JOURNAL_DS, "Journal", JOURNAL_DB, "database", kind="data_source"),
        make_page(JOURNAL_ROW, "Caring", JOURNAL_DS, "data_source"),
    ]

    places = places_for(pages)

    assert places[JOURNAL_ROW].path == "Life OS / Journal / Caring"
    assert places[JOURNAL_ROW].mirror_path == (
        f"Life OS/Journal/Caring {JOURNAL_ROW}.md"
    )


def test_two_siblings_with_the_same_title_get_distinct_directories():
    child_a, child_b = "a" * 32, "b" * 32
    pages = [
        make_page(LIFE_OS, "Life OS"),
        make_page(child_a, "Untitled", LIFE_OS, "page"),
        make_page(child_b, "Untitled", LIFE_OS, "page"),
        make_page(JOB_HUNT, "Deep", child_a, "page"),
    ]

    places = places_for(pages)

    assert places[JOB_HUNT].parent_dir == "Life OS/Untitled aaaa-aaaa"


def test_a_page_whose_parent_is_missing_sits_at_the_root():
    places = places_for([make_page(JOB_HUNT, "Orphan", "unknown-id", "page")])
    assert places[JOB_HUNT].path == "Orphan"
    assert places[JOB_HUNT].mirror_path == f"Orphan {JOB_HUNT}.md"


def test_a_parent_cycle_does_not_hang():
    a, b = "a" * 32, "b" * 32
    places = compute_places(
        {a: make_page(a, "A", b, "page"), b: make_page(b, "B", a, "page")}
    )
    assert set(places) == {a, b}


def test_containers_have_no_mirror_file_of_their_own():
    places = places_for([make_page(JOURNAL_DB, "Journal", kind="database")])
    assert places[JOURNAL_DB].mirror_path == ""


def test_plan_run_sorts_the_listing():
    listed = [
        make_page(JOB_HUNT, "New page"),
        make_page(CAREER, "Edited", edited=NOW),
        make_page(LIFE_OS, "Unchanged", edited=NOW - timedelta(days=1)),
        make_page(JOURNAL_ROW, "Trashed", in_trash=True),
    ]
    stored = {
        CAREER: make_stored(CAREER, "Edited", edited=NOW - timedelta(hours=1)),
        LIFE_OS: make_stored(
            LIFE_OS,
            "Unchanged",
            path="Unchanged",
            mirror_path=f"Unchanged {LIFE_OS}.md",
            edited=NOW - timedelta(days=1),
        ),
        JOURNAL_ROW: make_stored(JOURNAL_ROW, "Trashed"),
    }

    plan = plan_run(listed, stored, places_for(listed))

    assert plan.new == {JOB_HUNT}
    assert plan.changed == {CAREER}
    assert plan.fetch == (JOB_HUNT, CAREER)
    assert plan.current == (LIFE_OS,)
    assert plan.gone == (JOURNAL_ROW,)
    assert plan.listed == 4


def test_a_page_whose_path_changed_is_a_move_not_a_fetch():
    listed = [
        make_page(LIFE_OS, "Life OS"),
        make_page(JOB_HUNT, "Job Hunt", LIFE_OS, "page"),
    ]
    stored = {
        LIFE_OS: make_stored(
            LIFE_OS, "Life OS", path="Life OS", mirror_path=f"Life OS {LIFE_OS}.md"
        ),
        JOB_HUNT: make_stored(
            JOB_HUNT,
            "Job Hunt",
            path="Job Hunt",
            mirror_path=f"Job Hunt {JOB_HUNT}.md",
            parent_id=LIFE_OS,
            parent_kind="page",
        ),
    }

    plan = plan_run(listed, stored, places_for(listed))

    assert plan.moved == (JOB_HUNT,)
    assert plan.fetch == ()


def test_an_incremental_run_stops_at_the_watermark():
    watermark = NOW
    listed = [
        make_page(JOB_HUNT, "Fresh", edited=NOW),
        make_page(CAREER, "Just inside the overlap", edited=NOW - timedelta(minutes=5)),
        make_page(LIFE_OS, "Older", edited=NOW - timedelta(minutes=30)),
    ]

    plan = plan_run(listed, {}, places_for(listed), watermark=watermark)

    assert plan.fetch == (JOB_HUNT, CAREER)
    assert plan.listed == 2
    assert plan.stopped_early is True


@pytest.mark.parametrize(
    ("full", "reindex"), [(True, False), (False, True)], ids=["full", "reindex"]
)
def test_full_and_reindex_runs_ignore_the_watermark(full, reindex):
    listed = [make_page(LIFE_OS, "Old", edited=NOW - timedelta(days=30))]

    plan = plan_run(
        listed, {}, places_for(listed), full=full, reindex=reindex, watermark=NOW
    )

    assert plan.stopped_early is False
    assert plan.fetch == (LIFE_OS,)


def test_reindex_refetches_pages_that_did_not_change():
    listed = [make_page(LIFE_OS, "Unchanged", edited=NOW)]
    stored = {
        LIFE_OS: make_stored(
            LIFE_OS,
            "Unchanged",
            path="Unchanged",
            mirror_path=f"Unchanged {LIFE_OS}.md",
        )
    }

    plan = plan_run(listed, stored, places_for(listed), reindex=True)

    assert plan.changed == {LIFE_OS}


def test_a_full_run_removes_pages_the_listing_no_longer_has():
    listed = [make_page(LIFE_OS, "Still here")]
    stored = {
        LIFE_OS: make_stored(
            LIFE_OS,
            "Still here",
            path="Still here",
            mirror_path=f"Still here {LIFE_OS}.md",
        ),
        JOB_HUNT: make_stored(JOB_HUNT, "Vanished"),
    }

    plan = plan_run(listed, stored, places_for(listed), full=True)

    assert plan.gone == (JOB_HUNT,)


def test_an_incremental_run_never_removes_a_page_it_did_not_see():
    listed = [make_page(LIFE_OS, "Fresh", edited=NOW)]
    stored = {JOB_HUNT: make_stored(JOB_HUNT, "Old but fine")}

    plan = plan_run(listed, stored, places_for(listed), watermark=NOW)

    assert plan.gone == ()


@pytest.mark.parametrize(
    ("synced", "edited", "expected"),
    [
        (None, NOW, True),
        (NOW - timedelta(hours=1), NOW, True),
        (NOW, NOW - timedelta(hours=1), False),
    ],
    ids=["never-fetched", "text-older-than-the-edit", "up-to-date"],
)
def test_is_stale(synced, edited, expected):
    assert is_stale(make_stored(LIFE_OS, synced=synced, edited=edited)) is expected


def test_failed_pages_are_retried_even_below_the_watermark():
    listed = [make_page(JOB_HUNT, "Fresh", edited=NOW)]
    stored = {
        CAREER: make_stored(CAREER, "Failed last time", synced=None),
        LIFE_OS: make_stored(LIFE_OS, "Fine", edited=NOW - timedelta(days=9)),
    }

    plan = plan_run(listed, stored, places_for(listed), watermark=NOW)

    assert plan.retry == {CAREER}
    assert plan.fetch == (JOB_HUNT, CAREER)


def test_a_limited_run_indexes_at_most_n_pages_and_deletes_nothing():
    listed = [make_page(f"{index}" * 32, f"Page {index}") for index in range(1, 5)]
    stored = {JOB_HUNT: make_stored(JOB_HUNT, "Vanished")}

    plan = plan_run(listed, stored, places_for(listed), full=True, limit=2)

    assert len(plan.fetch) == 2
    assert plan.gone == ()
    assert plan.new == set(plan.fetch)


def test_build_documents_numbers_chunks_by_page_id():
    documents = build_documents(JOB_HUNT, "# Title\n\nsome body text", {"title": "T"})

    assert [document.id for document in documents] == [f"{JOB_HUNT}#0"]
    assert documents[0].source == JOB_HUNT
    assert documents[0].metadata == {"title": "T"}


def test_build_documents_of_an_empty_page_is_empty():
    assert build_documents(JOB_HUNT, "   \n\n  ", {}) == []


def test_build_chunk_metadata_carries_the_mirror_path_for_read_file():
    obj = NotionObject(
        id=JOURNAL_ROW,
        kind="page",
        title="Caring",
        parent_id=JOURNAL_DS,
        parent_kind="data_source",
        url="https://notion.so/caring",
        created_time=datetime(2026, 5, 28, 2, 23, tzinfo=UTC),
        last_edited_time=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        properties={
            "Tags": {"type": "multi_select", "multi_select": [{"name": "Daily"}]}
        },
    )
    place = Place(
        path="Life OS / Journal / Caring",
        mirror_path=f"Life OS/Journal/Caring {JOURNAL_ROW}.md",
        parent_dir="Life OS/Journal",
    )

    assert build_chunk_metadata(obj, place) == {
        "title": "Caring",
        "path": f"Life OS/Journal/Caring {JOURNAL_ROW}.md",
        "created_time": "2026-05-28T02:23:00+00:00",
        "last_edited_time": "2026-06-01T09:00:00+00:00",
        "url": "https://notion.so/caring",
        "properties": {"Tags": "Daily"},
    }


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=30), "30 s"),
        (timedelta(minutes=12), "12 min"),
        (timedelta(hours=6), "6 h"),
        (timedelta(days=3), "3 days"),
    ],
    ids=["seconds", "minutes", "hours", "days"],
)
def test_format_age(delta, expected):
    assert format_age(datetime.now(UTC) - delta) == expected
