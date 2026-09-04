"""Embedding models (Gemini, Qwen, BGE-M3) with shared over-length handling."""

import asyncio
import math
import re
from abc import ABC, abstractmethod
from typing import Literal

import numpy as np
from google import genai
from google.genai import errors, types

OverflowStrategy = Literal["chunking-average", "truncate", "barbell"]

# Token-length proxy for embedders without a local tokenizer. English averages
# ~4 chars/token, so 3 errs safe both ways: counting overestimates a text's
# tokens and slicing under-fills the budget.
CHARS_PER_TOKEN = 3


class Embedder(ABC):
    """Embedding backend with shared handling of over-length inputs.

    The public embed methods own the overflow recipe — fit texts to the token
    budget, encode via the subclass hooks, pool piece vectors back to one per
    text — so subclasses only implement _embed_pieces and _embed_query_pieces
    and cannot skip the length handling. Inputs longer than max_seq_length
    tokens are transformed per overflow_strategy: "chunking-average" (default)
    splits into sentence-packed pieces whose embeddings are averaged into one
    vector, "truncate" keeps the leading tokens, and "barbell" keeps the
    leading and trailing halves. Length is measured with the CHARS_PER_TOKEN
    proxy unless a subclass overrides the token primitives with the model's
    own tokenizer.
    """

    def __init__(
        self,
        max_seq_length: int,
        overflow_strategy: OverflowStrategy = "chunking-average",
    ):
        # max_seq_length is in tokens: the model's own tokens where a tokenizer
        # is available, CHARS_PER_TOKEN-proxy tokens otherwise.
        self.max_seq_length = max_seq_length
        self.overflow_strategy = overflow_strategy

    async def embed_documents(
        self, texts: list[str], titles: list[str] | None = None
    ) -> list[list[float]]:
        if titles is not None and len(titles) != len(texts):
            raise ValueError("titles must have the same length as texts")
        if not texts:
            return []
        # Fitting may tokenize (and lazily load a local model), so keep it off
        # the event loop.
        groups = await asyncio.to_thread(
            lambda: [self._fit_text(text) for text in texts]
        )
        pieces = [piece for group in groups for piece in group]
        piece_titles = None
        if titles is not None:
            piece_titles = [
                title
                for title, group in zip(titles, groups, strict=True)
                for _ in group
            ]
        vectors = await self._embed_pieces(pieces, piece_titles)
        if len(pieces) == len(texts):
            return vectors
        return self._pool_groups(vectors, groups).tolist()

    async def embed_query(self, text: str) -> list[float]:
        pieces = await asyncio.to_thread(self._fit_text, text)
        vectors = await self._embed_query_pieces(pieces)
        if len(pieces) == 1:
            return vectors[0]
        return self._pool_vectors(vectors).tolist()

    @abstractmethod
    async def _embed_pieces(
        self, pieces: list[str], titles: list[str] | None
    ) -> list[list[float]]:
        """Encode budget-fitting document pieces, one vector per piece."""
        raise NotImplementedError

    @abstractmethod
    async def _embed_query_pieces(self, pieces: list[str]) -> list[list[float]]:
        """Encode budget-fitting query pieces, one vector per piece."""
        raise NotImplementedError

    def _fit_text(self, text: str) -> list[str]:
        """
        Preprocess text longer than sequence length according to
        overflow strategy before encoding.
        """
        # Headroom for special tokens and the templates subclasses wrap around
        # the text. 16 is based on judgement call
        token_budget = self.max_seq_length - 16
        if self._count_tokens(text) <= token_budget:
            return [text]
        if self.overflow_strategy == "truncate":
            return [self._take_tokens(text, token_budget)]
        if self.overflow_strategy == "barbell":
            head = self._take_tokens(text, token_budget // 2)
            tail = self._take_tokens(
                text, token_budget - token_budget // 2, from_end=True
            )
            return [f"{head} {tail}"]
        return self._pack_sentences(text, token_budget)

    def _pack_sentences(self, text: str, token_budget: int) -> list[str]:
        """
        Greedily pack consecutive sentences into groups of <= budget tokens.

        Split by sentence boundaries and pack together before embedding so
        more efficient
        """
        groups: list[str] = []
        current = ""
        current_tokens = 0
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if not sentence:
                continue
            sentence_tokens = self._count_tokens(sentence)
            if sentence_tokens > token_budget:
                if current:
                    groups.append(current)
                    current, current_tokens = "", 0
                groups.extend(self._split_tokens(sentence, token_budget))
            elif not current:
                current, current_tokens = sentence, sentence_tokens
            elif current_tokens + sentence_tokens <= token_budget:
                current = f"{current} {sentence}"
                current_tokens += sentence_tokens
            else:
                groups.append(current)
                current, current_tokens = sentence, sentence_tokens
        if current:
            groups.append(current)
        return groups

    def _pool_vectors(self, vectors: list[list[float]]) -> np.ndarray:
        """Average an N x dim matrix of piece embeddings into one vector."""
        matrix = np.asarray(vectors, dtype=float)
        if matrix.ndim != 2:
            raise ValueError(f"expected an N x dim matrix, got shape {matrix.shape}")
        return matrix.mean(axis=0)

    def _pool_groups(
        self, vectors: list[list[float]], groups: list[list[str]]
    ) -> np.ndarray:
        """Collapse piece embeddings back to one row per original text.

        Texts that were never split keep their vector untouched, so a text
        embeds identically regardless of what else was in the batch.
        """
        rows = []
        start = 0
        for group in groups:
            if len(group) == 1:
                rows.append(np.asarray(vectors[start]))
            else:
                rows.append(self._pool_vectors(vectors[start : start + len(group)]))
            start += len(group)
        return np.stack(rows)

    def _count_tokens(self, text: str) -> int:
        return math.ceil(len(text) / CHARS_PER_TOKEN)

    def _take_tokens(self, text: str, k: int, from_end: bool = False) -> str:
        chars = k * CHARS_PER_TOKEN
        return text[-chars:] if from_end else text[:chars]

    def _split_tokens(self, text: str, k: int) -> list[str]:
        chars = k * CHARS_PER_TOKEN
        return [text[i : i + chars] for i in range(0, len(text), chars)]


class TitlePrefixEmbedder:
    """Embeds documents with their note title prepended, queries unchanged.

    Wraps any Embedder rather than subclassing one, so it composes with all of
    them. Only the embedded string carries the title: the chunk text stored in
    the index, and therefore chunk ids and text hashes, is untouched.
    """

    def __init__(self, inner: Embedder):
        self.inner = inner
        self.output_dimensionality = inner.output_dimensionality

    async def embed_documents(
        self, texts: list[str], titles: list[str] | None = None
    ) -> list[list[float]]:
        if titles is None:
            return await self.inner.embed_documents(texts)
        prefixed = [
            f"{title}\n\n{text}" for title, text in zip(titles, texts, strict=True)
        ]
        return await self.inner.embed_documents(prefixed, titles=titles)

    async def embed_query(self, text: str) -> list[float]:
        return await self.inner.embed_query(text)


class GeminiEmbedder(Embedder):
    """Generates embeddings via the Gemini API (available on the free tier).

    gemini-embedding-2 does not support task_type; retrieval quality relies on
    the prompt templates applied to document and query pieces. Batches are
    sent sequentially to stay within free-tier rate limits. Input length is
    measured with the CHARS_PER_TOKEN proxy — there is no local tokenizer.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-embedding-2",
        output_dimensionality: int = 768,
        batch_size: int = 100,
        max_seq_length: int = 2048,
        overflow_strategy: OverflowStrategy = "chunking-average",
    ):
        super().__init__(max_seq_length, overflow_strategy)
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

    async def _embed_pieces(
        self, pieces: list[str], titles: list[str] | None
    ) -> list[list[float]]:
        """Embed document pieces using the recommended retrieval template."""
        if titles is None:
            titles = ["none"] * len(pieces)
        return await self.embed(
            [
                f"title: {title} | text: {piece}"
                for title, piece in zip(titles, pieces, strict=True)
            ]
        )

    async def _embed_query_pieces(self, pieces: list[str]) -> list[list[float]]:
        """Embed query pieces using the recommended retrieval template."""
        return await self.embed(
            [f"task: search result | query: {piece}" for piece in pieces]
        )


class SentenceTransformerEmbedder(Embedder):
    """Local embeddings via sentence-transformers, free and offline.

    The model is loaded (and downloaded from Hugging Face on first use)
    lazily by the first call that needs it — encoding or a token primitive —
    or up front by load_model().
    Documents embed verbatim, so titles are ignored; instruction-aware
    subclasses set _query_prompt_name to the model's built-in query prompt.
    Embeddings are normalized to match pgvector's cosine scoring, and
    encoding runs in a worker thread to keep the event loop free. Token
    primitives use the model's own tokenizer, and the model's native
    truncation is capped to max_seq_length as a backstop.
    """

    _query_prompt_name: str | None = None

    def __init__(
        self,
        model_name: str,
        output_dimensionality: int,
        max_seq_length: int,
        overflow_strategy: OverflowStrategy = "chunking-average",
        truncate_dim: int | None = None,
    ):
        super().__init__(max_seq_length, overflow_strategy)
        self.model_name = model_name
        self.output_dimensionality = output_dimensionality
        self._truncate_dim = truncate_dim
        self._model = None

    async def _embed_pieces(
        self, pieces: list[str], titles: list[str] | None
    ) -> list[list[float]]:
        vectors = await asyncio.to_thread(self._encode_pieces, pieces)
        return vectors.tolist()

    async def _embed_query_pieces(self, pieces: list[str]) -> list[list[float]]:
        vectors = await asyncio.to_thread(
            self._encode_pieces, pieces, prompt_name=self._query_prompt_name
        )
        return vectors.tolist()

    def _encode_pieces(self, pieces: list[str], **kwargs) -> np.ndarray:
        self.load_model()
        return self._model.encode(pieces, normalize_embeddings=True, **kwargs)

    def load_model(self) -> None:
        """Loads the model now; later calls are no-ops. Otherwise the first encode loads it."""
        if self._model is None:
            # Imported here so that torch only loads when this embedder is used.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name, truncate_dim=self._truncate_dim
            )
            self._model.max_seq_length = min(
                self._model.max_seq_length, self.max_seq_length
            )

    def _count_tokens(self, text: str) -> int:
        return len(self._tokenize(text))

    def _take_tokens(self, text: str, k: int, from_end: bool = False) -> str:
        ids = self._tokenize(text)
        return self._model.tokenizer.decode(ids[-k:] if from_end else ids[:k])

    def _split_tokens(self, text: str, k: int) -> list[str]:
        ids = self._tokenize(text)
        return [
            self._model.tokenizer.decode(ids[i : i + k]) for i in range(0, len(ids), k)
        ]

    def _tokenize(self, text: str) -> list[int]:
        self.load_model()
        return self._model.tokenizer.encode(text, add_special_tokens=False)


class QwenEmbedder(SentenceTransformerEmbedder):
    """Qwen3-Embedding is instruction-aware: queries are encoded with the
    model's built-in query prompt, documents verbatim."""

    _query_prompt_name = "query"

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-Embedding-0.6B",
        output_dimensionality: int = 1024,
        max_seq_length: int = 32768,
        overflow_strategy: OverflowStrategy = "chunking-average",
    ):
        super().__init__(
            model_name=model_name,
            output_dimensionality=output_dimensionality,
            max_seq_length=max_seq_length,
            overflow_strategy=overflow_strategy,
            truncate_dim=output_dimensionality,
        )


class BgeM3Embedder(SentenceTransformerEmbedder):
    """BGE-M3 is symmetric — no query prompt, queries and documents are encoded
    alike — and emits fixed 1024-dim vectors (not Matryoshka), so titles and
    dimensionality are not configurable."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        max_seq_length: int = 8192,
        overflow_strategy: OverflowStrategy = "chunking-average",
    ):
        super().__init__(
            model_name=model_name,
            output_dimensionality=1024,
            max_seq_length=max_seq_length,
            overflow_strategy=overflow_strategy,
        )
