"""
Uses an LLM to generate queries for a sample of notes.
This is the dataset will use to evaluate RAG sytem.

Method:
- Load each note from the sample provided
- Generate 3 queries for each note using an LLM
- Discard any queries that are too simple
- Collect all queries
- Remove semantically similar queries using embeddings
- Save the final set of queries to a JSON file

The objective is to create a diverse set of queries that can be used to evaluate the RAG system's retrieval performance.

"""

import argparse
import asyncio
import json

from pydantic import BaseModel, Field
from tqdm import tqdm

from evals.config import settings as eval_settings
from evals.utils import generate_queries


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-json",
        type=str,
        default="sample_notes.json",
        help="JSON file containing the sample notes.",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default="generated_queries.json",
        help="Output file to save the generated queries.",
    )
    parser.add_argument(
        "--system-prompt-loc",
        type=str,
        default="",
        help="Markdown system prompt for query generation.",
    )
    return parser.parse_args()


class GeneratedQuery(BaseModel):
    query: str = Field(..., description="The generated query text.")
    passage: str = Field(
        ..., description="The passage from which the query was generated."
    )


class GeneratedQueries(BaseModel):
    queries: list[GeneratedQuery] = Field(..., description="List of generated queries.")


# def split_response(response: str) -> list[str]:
#     """Split the response string into a list of queries."""
#     pattern = re.compile(r"<query>(.*?)</query>")
#     return [match.group(1).strip() for match in pattern.finditer(response)]


def load_existing_queries(output_file: str) -> list[dict]:
    """Load queries from a previous partial run so it can be resumed."""
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            return json.load(f)["queries"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save_output(output_file: str, generated_queries: list[dict]) -> None:
    output = {
        "num_generated_queries": len(generated_queries),
        "queries": generated_queries,
        "model": eval_settings.model_name,
        "temperature": eval_settings.temperature,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)


async def process_note(
    note_file: str,
    note_content: str,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    user_prompt = f"Generate {eval_settings.queries_per_note} queries for the following note:\n\n{note_content}"
    try:
        async with semaphore:
            response = await generate_queries(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=GeneratedQueries,
                temperature=eval_settings.temperature,
                model=eval_settings.model_name,
            )
    # Broad catch is deliberate: a failure on one note (API error,
    # validation, etc.) must not abort the batch — log, skip, keep going.
    except Exception as e:  # noqa: BLE001
        print(f"Error generating queries for {note_file}: {e}")
        return []

    return [
        {
            "source_file": str(note_file),
            "query": query.query,
            "passage": query.passage,
        }
        for query in response.queries
    ]


async def generate_all(
    todo: list[tuple[str, str]],
    system_prompt: str,
    generated_queries: list[dict],
    output_file: str,
) -> None:
    semaphore = asyncio.Semaphore(eval_settings.concurrency)
    tasks = [
        asyncio.create_task(
            process_note(note_file, note_content, system_prompt, semaphore)
        )
        for note_file, note_content in todo
    ]

    for completed in tqdm(
        asyncio.as_completed(tasks), total=len(tasks), desc="Processing notes"
    ):
        queries = await completed
        if queries:
            generated_queries.extend(queries)
            save_output(output_file, generated_queries)


def main():
    args = parse_args()
    with open(args.system_prompt_loc, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()

    with open(args.sample_json, "r", encoding="utf-8") as f:
        sample_notes = json.load(f)

    generated_queries = load_existing_queries(args.output_file)
    processed_files = {q["source_file"] for q in generated_queries}
    if processed_files:
        print(f"Resuming: {len(processed_files)} notes already processed.")

    todo = []
    for note_file in sample_notes["samples"]:
        if str(note_file) in processed_files:
            continue
        with open(note_file, "r", encoding="utf-8") as f:
            todo.append((note_file, f.read().strip()))

    asyncio.run(generate_all(todo, system_prompt, generated_queries, args.output_file))
    save_output(args.output_file, generated_queries)


if __name__ == "__main__":
    main()
