import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from src.retrieval.embedder import GeminiEmbedder, QwenEmbedder


class FakeModels:
    def __init__(self):
        self.calls = []

    async def embed_content(self, *, model, contents, config):
        texts = [content.parts[0].text for content in contents]
        self.calls.append(SimpleNamespace(model=model, texts=texts, config=config))
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[float(len(t))]) for t in texts]
        )


def make_embedder(**kwargs) -> tuple[GeminiEmbedder, FakeModels]:
    embedder = GeminiEmbedder(api_key="test-key", **kwargs)
    fake = FakeModels()
    embedder._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
    return embedder, fake


def test_one_vector_per_text_in_order():
    embedder, _ = make_embedder()
    vectors = asyncio.run(embedder.embed(["a", "bb", "ccc"]))
    assert vectors == [[1.0], [2.0], [3.0]]


def test_batches_are_split_by_batch_size():
    embedder, fake = make_embedder(batch_size=2)
    vectors = asyncio.run(embedder.embed(["a", "bb", "ccc", "dddd", "eeeee"]))
    assert [len(call.texts) for call in fake.calls] == [2, 2, 1]
    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]


def test_empty_input_makes_no_api_call():
    embedder, fake = make_embedder()
    assert asyncio.run(embedder.embed([])) == []
    assert fake.calls == []


def test_config_carries_model_and_default_dimensionality():
    embedder, fake = make_embedder()
    asyncio.run(embedder.embed(["hello"]))
    call = fake.calls[0]
    assert call.model == "gemini-embedding-2"
    assert call.config.output_dimensionality == 768


def test_dimensionality_override_is_passed_through():
    embedder, fake = make_embedder(output_dimensionality=3072)
    asyncio.run(embedder.embed(["hello"]))
    assert fake.calls[0].config.output_dimensionality == 3072


def test_embed_documents_applies_template():
    embedder, fake = make_embedder()
    asyncio.run(embedder.embed_documents(["doc one", "doc two"]))
    assert fake.calls[0].texts == [
        "title: none | text: doc one",
        "title: none | text: doc two",
    ]


def test_embed_documents_uses_given_titles():
    embedder, fake = make_embedder()
    asyncio.run(embedder.embed_documents(["doc one"], titles=["Sleep Study"]))
    assert fake.calls[0].texts == ["title: Sleep Study | text: doc one"]


def test_embed_documents_rejects_mismatched_titles():
    embedder, _ = make_embedder()
    with pytest.raises(ValueError):
        asyncio.run(embedder.embed_documents(["doc one"], titles=["a", "b"]))


def test_embed_query_applies_template_and_returns_single_vector():
    embedder, fake = make_embedder()
    vector = asyncio.run(embedder.embed_query("what is sleep?"))
    assert fake.calls[0].texts == ["task: search result | query: what is sleep?"]
    assert isinstance(vector[0], float)


class FakeSentenceTransformer:
    def __init__(self):
        self.calls = []

    def encode(self, texts, normalize_embeddings=False, prompt_name=None):
        self.calls.append(SimpleNamespace(texts=texts, prompt_name=prompt_name))
        return np.array([[float(len(t)), 0.0] for t in texts])


def make_qwen_embedder() -> tuple[QwenEmbedder, FakeSentenceTransformer]:
    embedder = QwenEmbedder()
    fake = FakeSentenceTransformer()
    embedder._model = fake
    return embedder, fake


def test_qwen_documents_encoded_verbatim_without_prompt():
    embedder, fake = make_qwen_embedder()
    vectors = asyncio.run(embedder.embed_documents(["doc one", "much longer doc"]))
    assert fake.calls[0].texts == ["doc one", "much longer doc"]
    assert fake.calls[0].prompt_name is None
    assert vectors == [[7.0, 0.0], [15.0, 0.0]]


def test_qwen_query_uses_query_prompt():
    embedder, fake = make_qwen_embedder()
    vector = asyncio.run(embedder.embed_query("what is sleep?"))
    assert fake.calls[0].texts == ["what is sleep?"]
    assert fake.calls[0].prompt_name == "query"
    assert vector == [14.0, 0.0]


def test_qwen_empty_documents_skip_model():
    embedder, fake = make_qwen_embedder()
    assert asyncio.run(embedder.embed_documents([])) == []
    assert fake.calls == []


def test_qwen_construction_does_not_load_model():
    embedder = QwenEmbedder()
    assert embedder._model is None


def test_embed_waits_out_rate_limit_and_retries(monkeypatch):
    from google.genai import errors

    class RateLimitedModels(FakeModels):
        def __init__(self, failures: int):
            super().__init__()
            self.failures = failures

        async def embed_content(self, *, model, contents, config):
            if self.failures:
                self.failures -= 1
                raise errors.ClientError(429, {"error": {"message": "quota"}}, None)
            return await super().embed_content(
                model=model, contents=contents, config=config
            )

    embedder, _ = make_embedder()
    fake = RateLimitedModels(failures=2)
    embedder._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("src.retrieval.embedder.asyncio.sleep", fake_sleep)
    assert asyncio.run(embedder.embed(["hello"])) == [[5.0]]
    assert sleeps == [30, 30]

    embedder2, _ = make_embedder()
    embedder2._client = SimpleNamespace(
        aio=SimpleNamespace(models=RateLimitedModels(failures=99))
    )
    with pytest.raises(errors.ClientError):
        asyncio.run(embedder2.embed(["hello"]))
