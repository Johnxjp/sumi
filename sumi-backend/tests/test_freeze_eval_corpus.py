from unittest import mock

from scripts.freeze_eval_corpus import build_metadata, measure

SYNC_RUN = {"mode": "full", "status": "ok", "pages_indexed": 2131}


def test_measure_counts_the_documents_and_their_size(tmp_path):
    (tmp_path / "Journal").mkdir()
    (tmp_path / "Journal" / "a.md").write_text("hello")
    (tmp_path / "b.md").write_text("worldly")
    (tmp_path / "notes.txt").write_text("not markdown")

    assert measure(tmp_path) == (2, len("hello") + len("worldly"))


@mock.patch(
    "scripts.freeze_eval_corpus.get_renderer_commit",
    autospec=True,
    return_value="abc123",
)
def test_metadata_records_what_the_corpus_is_and_what_made_it(_commit):
    metadata = build_metadata("eval-corpus-2026-09-05", 2131, 8004854, SYNC_RUN)

    assert metadata["name"] == "eval-corpus-2026-09-05"
    assert metadata["source"] == "notion api"
    assert metadata["unit"] == "document"
    assert metadata["documents"] == 2131
    assert metadata["bytes"] == 8004854
    assert metadata["sync_run"] == SYNC_RUN
    # The same page renders differently as the normaliser's rules change, so a
    # corpus is only reproducible alongside the code that wrote it.
    assert metadata["renderer_commit"] == "abc123"


@mock.patch(
    "scripts.freeze_eval_corpus.subprocess.run", autospec=True, side_effect=OSError
)
def test_the_renderer_commit_is_unknown_outside_a_git_checkout(_run):
    from scripts.freeze_eval_corpus import get_renderer_commit

    assert get_renderer_commit() == "unknown"
