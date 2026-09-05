from scripts.prune_generated_queries import find_corpus_page_ids, partition_queries

PAGE_A = "336d52d026fc8076ade8f7b2612f1fef"
PAGE_B = "146d52d026fc8065a351fc6e2ea53f8b"
GONE = "3aed52d026fc8113822bde48d2297067"


def make_query(source: str) -> dict:
    return {"query": "what did I write?", "source_file": source}


def test_page_ids_are_read_from_the_file_names_at_any_depth(tmp_path):
    (tmp_path / "Journal").mkdir()
    (tmp_path / "Journal" / f"Take responsibility {PAGE_A}.md").write_text("x")
    (tmp_path / f"Vision {PAGE_B}.md").write_text("x")
    (tmp_path / "career-direction.md").write_text("an upload, not a page")

    assert find_corpus_page_ids(tmp_path) == {PAGE_A, PAGE_B}


def test_a_query_is_kept_when_its_note_is_in_the_corpus():
    """The note is matched by page id, so a note that moved is still found."""
    queries = [
        make_query(f"../data/notion-export-markdown/Old/Path {PAGE_A}.md"),
        make_query(f"../data/notion-export-markdown/Trashed {GONE}.md"),
        make_query("../data/notion-export-markdown/no-page-id.md"),
    ]

    kept, dropped = partition_queries(queries, {PAGE_A, PAGE_B})

    assert [q["source_file"] for q in kept] == [
        f"../data/notion-export-markdown/Old/Path {PAGE_A}.md"
    ]
    assert len(dropped) == 2
