from google import genai
from google.genai import types


class GeminiEmbedder:
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
            response = await self._client.aio.models.embed_content(
                model=self.model, contents=contents, config=config
            )
            vectors.extend(embedding.values for embedding in response.embeddings)
        return vectors

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
