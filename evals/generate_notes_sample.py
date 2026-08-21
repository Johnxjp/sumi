"""
Script to generate a sample of notes to build evaluation set from.
"""

import argparse
import json
import random
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a sample of notes to build evaluation set from."
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        default="../data/notion-export-markdown",
        help="Directory containing the notes. Expected to be in the format.",
    )
    parser.add_argument(
        "--num_samples", type=int, default=100, help="Number of samples to generate."
    )
    parser.add_argument(
        "--filter_length",
        type=int,
        default=250,
        help="Minimum character length for notes to include.",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default="sample_notes.json",
        help="Output file to save the generated samples.",
    )
    return parser.parse_args()


def main():
    # Walk directory to get all notes
    # Filter out non-markdown files and short files
    # Randomly sample the specified number of notes
    args = parse_args()

    files = []
    paths = Path(args.data_dir).rglob("*")
    for path in paths:
        if path.is_file() and path.suffix in (".md", ".txt"):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if len(content) >= args.filter_length:  # Filter out short files
                    files.append(str(path))

    # Randomly sample the specified number of notes
    sampled_files = random.sample(files, min(args.num_samples, len(files)))

    # Save the sampled notes to the output file
    output = {
        "min_characters": args.filter_length,
        "num_samples": args.num_samples,
        "samples": sampled_files,
    }
    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    main()
