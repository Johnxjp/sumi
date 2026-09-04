import json

import pytest

from scripts.check_export_fidelity import (
    compare_page,
    compute_chunk_keys,
    find_export_pages,
    find_first_difference,
    load_judged_page_ids,
    order_pages,
    read_cached,
    summarise,
    write_cached,
)

PAGE_A = "336d52d026fc8076ade8f7b2612f1fef"
PAGE_B = "146d52d026fc8065a351fc6e2ea53f8b"
NOTE = "# Caring\n\nCreated: May 28, 2026 3:23 AM\n\nSome body text.\n"


@pytest.fixture
def export(tmp_path):
    root = tmp_path / "export"
    (root / "Journal").mkdir(parents=True)
    (root / "Journal" / f"Caring {PAGE_A}.md").write_text(NOTE, encoding="utf-8")
    (root / f"Notes {PAGE_B}.md").write_text(
        "# Notes\n\nOther text.\n", encoding="utf-8"
    )
    # An uploaded file, not a page: its name has no 32-hex id.
    (root / "Journal" / "career-direction.md").write_text("no id", encoding="utf-8")
    return root


def test_find_export_pages_reads_the_id_out_of_each_file_name(export):
    pages = find_export_pages(export)

    assert {page.page_id for page in pages} == {PAGE_A, PAGE_B}
    caring = next(page for page in pages if page.page_id == PAGE_A)
    assert caring.text == NOTE


def test_files_without_a_page_id_are_not_compared(export):
    assert all(
        "career-direction" not in str(page.path) for page in find_export_pages(export)
    )


def test_identical_text_gives_identical_chunk_keys():
    assert compute_chunk_keys(NOTE) == compute_chunk_keys(NOTE)


def test_whitespace_alone_does_not_change_a_chunk_key():
    assert compute_chunk_keys("a  b") == compute_chunk_keys("a b")


@pytest.mark.parametrize(
    ("exported", "synced", "expected"),
    [
        ("same\ntext", "same\ntext", None),
        ("> quote\n> ", "> quote\n>", ("> ", ">")),
        ("one line", "one line\nextra", ("", "extra")),
        ("one line\nextra", "one line", ("extra", "")),
    ],
    ids=["no-difference", "a-changed-line", "sync-has-more", "export-has-more"],
)
def test_find_first_difference(exported, synced, expected):
    assert find_first_difference(exported, synced) == expected


def test_compare_page_reports_an_exact_match():
    comparison = compare_page(PAGE_A, NOTE, NOTE)

    assert comparison.identical is True
    assert comparison.shares_a_chunk is True
    assert comparison.first_difference is None


def test_compare_page_reports_a_page_that_differs():
    comparison = compare_page(PAGE_A, NOTE, NOTE.replace("Some body", "Other body"))

    assert comparison.identical is False
    assert comparison.shares_a_chunk is False
    assert comparison.first_difference == ("Some body text.", "Other body text.")


def test_summarise_counts_matches_and_the_commonest_difference():
    comparisons = [
        compare_page(PAGE_A, NOTE, NOTE),
        compare_page(PAGE_B, NOTE, NOTE.replace("Some body", "Other body")),
        compare_page("c" * 32, NOTE, NOTE.replace("Some body", "Other body")),
    ]

    report = summarise(comparisons)

    assert report.compared == 3
    assert report.identical == 1
    assert report.differences.most_common(1) == [
        (("Some body text.", "Other body text."), 2)
    ]
    assert "1/3 (33.3%)" in report.describe()


def test_load_judged_page_ids_reads_them_out_of_the_chunk_ids(tmp_path):
    path = tmp_path / "annotations.json"
    path.write_text(
        json.dumps(
            {
                "queries": {
                    "q": {
                        "annotations": {
                            "k": {
                                "sources": [
                                    {"chunk_id": f"Journal/Caring {PAGE_A}.md#0"},
                                    {"chunk_id": "no-id.md#0"},
                                ]
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_judged_page_ids(path) == {PAGE_A}


def test_load_judged_page_ids_of_a_missing_file_is_empty(tmp_path):
    assert load_judged_page_ids(tmp_path / "nothing.json") == set()


def test_judged_pages_are_checked_first(export):
    pages = find_export_pages(export)

    ordered = order_pages(pages, {PAGE_B}, judged_first=True)

    assert ordered[0].page_id == PAGE_B
    assert order_pages(pages, {PAGE_B}, judged_first=False) == pages


def test_the_cache_returns_what_was_written(tmp_path):
    cache = tmp_path / "cache"

    assert read_cached(cache, PAGE_A) is None

    write_cached(cache, PAGE_A, "raw notion markdown")

    assert read_cached(cache, PAGE_A) == "raw notion markdown"


def test_no_cache_directory_means_no_caching(tmp_path):
    write_cached(None, PAGE_A, "raw")
    assert read_cached(None, PAGE_A) is None
