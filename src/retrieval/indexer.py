from abc import ABC, abstractmethod
from typing import Any

import requests
from pydantic import BaseModel


class Document(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any]


class Indexer(ABC):
    @abstractmethod
    def index(self, documents: list[str]):
        raise NotImplementedError("Subclasses must implement the index method.")


class BreadBowlIndexer(Indexer):
    def __init__(self, api_base_url: str, api_key: str, index_id: str | None = None):
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.index_id = index_id
        self._index_metadata = None

    def create_index(self):
        # Implement the logic to create an index in BreadBowl using the API
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {"name": "production", "text_retention": "none"}  # Customize as needed
        response = requests.post(
            f"{self.api_base_url}/v1/indexes", headers=headers, json=data
        )
        if response.status_code == 200:
            self.index_id = response.json().get("id")
            self._index_metadata = response.json()
            print("Index created successfully.")
            return self.index_id

        raise ValueError(
            f"Failed to create index: {response.status_code} - {response.text}"
        )

    def index(self, documents: list[Document]) -> list[tuple[str, str]]:
        """Returns failed documents"""
        if not self.index_id:
            raise ValueError("Index ID is not set. Please create an index first.")

        max_documents_per_request = 50  # Set by API
        url = f"{self.api_base_url}/v1/indexes/{self.index_id}/documents"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        failed_documents = []
        for batch_start in range(0, len(documents), max_documents_per_request):
            batch = documents[batch_start : batch_start + max_documents_per_request]
            data = {
                "documents": [
                    {"doc_id": str(doc.id), "text": doc.text, "metadata": doc.metadata}
                    for doc in batch
                ]
            }
            response = requests.post(
                url,
                headers=headers,
                json=data,
            )
            response = response.json()
            if len(response["failed"]):
                failed_documents.extend(
                    (response["failed"]["doc_id"], response["failed"]["error"])
                )

        return failed_documents

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search the index for documents matching the query."""
        if not self.index_id:
            raise ValueError("Index ID is not set. Please create an index first.")

        url = f"{self.api_base_url}/v1/indexes/{self.index_id}/search"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {"query": query}

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            return response.json().get("results", [])

        raise ValueError(
            f"Failed to search index: {response.status_code} - {response.text}"
        )