import argparse
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
import os

load_dotenv()

from src.retrieval.indexer import BreadBowlIndexer, Document


def parse_args():
    parser = argparse.ArgumentParser(description="Test BreadBowl indexer")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Index command
    index_parser = subparsers.add_parser("index", help="Index documents")
    index_parser.add_argument("document-dir", type=str, help="Directory with documents")
    index_parser.add_argument("--index-id", type=str, help="Optional index ID")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search the index")
    search_parser.add_argument("query", type=str, help="Search query")
    search_parser.add_argument("--index-id", type=str, required=True, help="Index ID")

    return parser.parse_args()


def load_document_filepaths(directory: str) -> list[str]:
    """Load all full filepaths from a directory recursively."""
    dir_path = Path(directory)
    if not dir_path.exists():
        raise ValueError(f"Directory {directory} does not exist")
    return [str(f.resolve()) for f in dir_path.rglob("*") if f.is_file()]


def index_command(args):
    """Index documents from a directory."""
    documents_filepaths = load_document_filepaths(args.document_dir)
    index_id = args.index_id or None
    indexer = BreadBowlIndexer(
        api_base_url=os.getenv("BREADBOWL_API_URL"),
        api_key=os.getenv("BREADBOWL_API_KEY"),
        index_id=index_id,
    )
    if not index_id:
        try:
            index_id = indexer.create_index()
            print(index_id)
        except ValueError:
            return

    documents = []
    for file in documents_filepaths[:5]:
        with open(file, encoding="utf-8") as f:
            text = f.read().strip()
            documents.append(Document(id=str(uuid4()), text=text, metadata={}))

    failed_documents = indexer.index(documents)
    for doc_id, error in failed_documents:
        print(f"Failed to insert {doc_id}: {error}")


def search_command(args):
    """Search the index for documents."""
    indexer = BreadBowlIndexer(
        api_base_url=os.getenv("BREADBOWL_API_URL"),
        api_key=os.getenv("BREADBOWL_API_KEY"),
        index_id=args.index_id,
    )
    results = indexer.search(args.query)
    for result in results:
        print(result)


def main():
    args = parse_args()

    if args.command == "index":
        index_command(args)
    elif args.command == "search":
        search_command(args)
    else:
        print("No command specified. Use --help for usage.")


if __name__ == "__main__":
    main()
