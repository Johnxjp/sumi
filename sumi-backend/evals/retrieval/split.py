"""Train/val split over the combined query sets.

The split is generated once and read back by every run: comparing two runs is
only meaningful when they were scored on the same queries.
"""

import json
import random
from dataclasses import dataclass
from pathlib import Path

TRAIN_FRACTION = 0.7


@dataclass(frozen=True)
class Split:
    seed: int
    train: set[str]
    val: set[str]


def build_split(
    strata: dict[str, list[str]],
    seed: int,
    train_fraction: float = TRAIN_FRACTION,
) -> Split:
    """Split each stratum independently so both datasets keep their proportions.

    Keys already assigned by an earlier stratum are skipped, so a query text
    present in both datasets lands on one side only and cannot leak.
    """
    rng = random.Random(seed)
    train: set[str] = set()
    val: set[str] = set()
    for keys in strata.values():
        remaining = sorted(set(keys) - train - val)
        rng.shuffle(remaining)
        cut = round(len(remaining) * train_fraction)
        train.update(remaining[:cut])
        val.update(remaining[cut:])
    return Split(seed=seed, train=train, val=val)


def save_split(path: Path, split: Split) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": split.seed,
                "train": sorted(split.train),
                "val": sorted(split.val),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def load_split(path: Path) -> Split:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Split(seed=data["seed"], train=set(data["train"]), val=set(data["val"]))
