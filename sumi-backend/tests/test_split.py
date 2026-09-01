import json

from evals.retrieval.split import build_split, load_split, save_split

STRATA = {
    "annotated": [f"annotated {i}" for i in range(20)],
    "generated": [f"generated {i}" for i in range(100)],
}


def test_build_split_partitions_each_stratum_at_the_train_fraction():
    split = build_split(STRATA, seed=1)
    all_keys = {key for keys in STRATA.values() for key in keys}
    assert split.train | split.val == all_keys
    assert not split.train & split.val
    for prefix, size in (("annotated", 20), ("generated", 100)):
        in_train = sum(1 for key in split.train if key.startswith(prefix))
        assert in_train == round(size * 0.7)


def test_build_split_is_deterministic_for_a_seed():
    assert build_split(STRATA, seed=1) == build_split(STRATA, seed=1)
    assert build_split(STRATA, seed=1) != build_split(STRATA, seed=2)


def test_build_split_assigns_a_shared_key_to_one_side_only():
    split = build_split(
        {"annotated": ["shared"], "generated": ["shared", "other"]}, seed=1
    )
    assert "shared" in split.train
    assert "shared" not in split.val


def test_save_and_load_split_round_trip(tmp_path):
    path = tmp_path / "nested" / "split.json"
    split = build_split(STRATA, seed=3)
    save_split(path, split)
    assert load_split(path) == split
    assert sorted(json.loads(path.read_text())) == ["seed", "train", "val"]
