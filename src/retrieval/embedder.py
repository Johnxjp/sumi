import asyncio
from abc import ABC, abstractmethod

from google import genai
from google.genai import errors, types


class Embedder(ABC):
    @abstractmethod
    async def embed_documents(
        self, texts: list[str], titles: list[str] | None = None
    ) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class GeminiEmbedder(Embedder):
    """Generates embeddings via the Gemini API (available on the free tier).

    gemini-embedding-2 does not support task_type; retrieval quality relies on
    the prompt templates applied by embed_documents and embed_query. Batches
    are sent sequentially to stay within free-tier rate limits.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-2",
        output_dimensionality: int = 768,
        batch_size: int = 100,
    ):
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.output_dimensionality = output_dimensionality
        self.batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts verbatim, returning one vector per text in order."""
        config = types.EmbedContentConfig(
            output_dimensionality=self.output_dimensionality
        )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            # One Content per text: a plain list of strings would be embedded
            # as parts of a single content and aggregated into one vector.
            contents = [types.Content(parts=[types.Part(text=text)]) for text in batch]
            response = await self._embed_batch(contents, config)
            vectors.extend(embedding.values for embedding in response.embeddings)
        return vectors

    async def _embed_batch(
        self, contents: list[types.Content], config: types.EmbedContentConfig
    ) -> types.EmbedContentResponse:
        """The free tier allows 100 embedded contents per minute, so on 429
        wait out the window and retry before giving up."""
        attempts = 5
        for attempt in range(attempts):
            try:
                return await self._client.aio.models.embed_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.ClientError as e:
                if e.code != 429 or attempt == attempts - 1:
                    raise
                await asyncio.sleep(30)

    async def embed_documents(
        self, texts: list[str], titles: list[str] | None = None
    ) -> list[list[float]]:
        """Embed document chunks using the recommended retrieval template."""
        if titles is not None and len(titles) != len(texts):
            raise ValueError("titles must have the same length as texts")
        if titles is None:
            titles = ["none"] * len(texts)
        formatted = [
            f"title: {title} | text: {text}"
            for title, text in zip(titles, texts, strict=True)
        ]
        return await self.embed(formatted)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query using the recommended retrieval template."""
        vectors = await self.embed([f"task: search result | query: {text}"])
        return vectors[0]


class QwenEmbedder(Embedder):
    """Local embeddings via sentence-transformers, free and offline.

    The model is loaded (and downloaded from Hugging Face on first use) lazily
    on the first embed call. Qwen3-Embedding is instruction-aware: queries are
    encoded with the model's built-in query prompt, documents verbatim, so
    titles are ignored. Embeddings are normalized to match pgvector's cosine
    scoring. Encoding runs in a worker thread to keep the event loop free.
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-Embedding-0.6B",
        output_dimensionality: int = 1024,
    ):
        self.model_name = model_name
        self.output_dimensionality = output_dimensionality
        self._model = None

    async def embed_documents(
        self, texts: list[str], titles: list[str] | None = None
    ) -> list[list[float]]:
        if not texts:
            return []
        embeddings = await asyncio.to_thread(self._encode, texts)
        return embeddings.tolist()

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await asyncio.to_thread(self._encode, [text], prompt_name="query")
        return embeddings[0].tolist()

    def _encode(self, texts: list[str], **kwargs):
        if self._model is None:
            # Imported here so that torch only loads when this embedder is used.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name, truncate_dim=self.output_dimensionality
            )
        return self._model.encode(texts, normalize_embeddings=True, **kwargs)
