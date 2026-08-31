import asyncio
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

from src.retrieval.embedder import (
    BgeM3Embedder,
    Embedder,
    GeminiEmbedder,
    QwenEmbedder,
    SentenceTransformerEmbedder,
    TitlePrefixEmbedder,
)


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


class FakeTokenizer:
    """Whitespace tokenizer: one word, one token; the words are the ids."""

    def encode(self, text, add_special_tokens=False):
        return text.split()

    def decode(self, ids):
        return " ".join(ids)


class FakeSentenceTransformer:
    def __init__(self):
        self.calls = []
        self.tokenizer = FakeTokenizer()

    def encode(self, texts, normalize_embeddings=False, prompt_name=None):
        self.calls.append(SimpleNamespace(texts=texts, prompt_name=prompt_name))
        return np.array([[float(len(t)), 0.0] for t in texts])


def make_qwen_embedder() -> tuple[QwenEmbedder, FakeSentenceTransformer]:
    embedder = QwenEmbedder()
    fake = FakeSentenceTransformer()
    embedder._model = fake
    return embedder, fake


def make_bge_embedder(**kwargs) -> tuple[BgeM3Embedder, FakeSentenceTransformer]:
    embedder = BgeM3Embedder(**kwargs)
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


def test_bge_documents_encoded_verbatim_without_prompt():
    embedder, fake = make_bge_embedder()
    vectors = asyncio.run(embedder.embed_documents(["doc one", "much longer doc"]))
    assert fake.calls[0].texts == ["doc one", "much longer doc"]
    assert fake.calls[0].prompt_name is None
    assert vectors == [[7.0, 0.0], [15.0, 0.0]]


def test_bge_query_encoded_verbatim_without_prompt():
    embedder, fake = make_bge_embedder()
    vector = asyncio.run(embedder.embed_query("what is sleep?"))
    assert fake.calls[0].texts == ["what is sleep?"]
    assert fake.calls[0].prompt_name is None
    assert vector == [14.0, 0.0]


def test_bge_empty_documents_skip_model():
    embedder, fake = make_bge_embedder()
    assert asyncio.run(embedder.embed_documents([])) == []
    assert fake.calls == []


def test_bge_construction_does_not_load_model():
    embedder = BgeM3Embedder()
    assert embedder._model is None


def inject_fake_model(embedder):
    embedder._model = FakeSentenceTransformer()


@mock.patch.object(
    SentenceTransformerEmbedder,
    "_load_model",
    autospec=True,
    side_effect=inject_fake_model,
)
def test_token_primitives_load_model_lazily(mock_load):
    embedder = BgeM3Embedder()
    assert embedder._count_tokens("two words") == 2
    mock_load.assert_called_once()


# max_seq_length=20 leaves a 4-token budget after the 16-token headroom.
@pytest.mark.parametrize(
    ("strategy", "text", "encoded", "expected"),
    [
        ("truncate", "w1 w2 w3 w4 w5 w6", ["w1 w2 w3 w4"], [[11.0, 0.0]]),
        ("barbell", "w1 w2 w3 w4 w5 w6", ["w1 w2 w5 w6"], [[11.0, 0.0]]),
        ("chunking-average", "a b. c d. e f.", ["a b. c d.", "e f."], [[6.5, 0.0]]),
        (
            "chunking-average",
            "w1 w2 w3 w4 w5 w6",
            ["w1 w2 w3 w4", "w5 w6"],
            [[8.0, 0.0]],
        ),
    ],
)
def test_overflow_strategies_use_model_tokenizer(strategy, text, encoded, expected):
    embedder, fake = make_bge_embedder(max_seq_length=20, overflow_strategy=strategy)
    vectors = asyncio.run(embedder.embed_documents([text]))
    assert fake.calls[0].texts == encoded
    assert vectors == expected


def test_pool_vectors_rejects_non_matrix_input():
    embedder = BgeM3Embedder()
    with pytest.raises(ValueError, match="matrix"):
        embedder._pool_vectors([1.0, 2.0])


def test_overflow_leaves_under_budget_texts_untouched():
    embedder, fake = make_bge_embedder(max_seq_length=20)
    vectors = asyncio.run(embedder.embed_documents(["a b", "a b. c d. e f."]))
    assert fake.calls[0].texts == ["a b", "a b. c d.", "e f."]
    assert vectors == [[3.0, 0.0], [6.5, 0.0]]


# Gemini has no local tokenizer, so budgets use the 3 chars/token proxy:
# a 4-token budget is 12 chars.
@pytest.mark.parametrize(
    ("strategy", "encoded", "expected"),
    [
        ("truncate", ["title: T | text: aaaa bbbb. c"], [[29.0]]),
        ("barbell", ["title: T | text: aaaa b  ffff."], [[30.0]]),
        (
            "chunking-average",
            [
                "title: T | text: aaaa bbbb.",
                "title: T | text: cccc dddd.",
                "title: T | text: eeee ffff.",
            ],
            [[27.0]],
        ),
    ],
)
def test_gemini_overflow_uses_char_proxy_and_keeps_titles(strategy, encoded, expected):
    embedder, fake = make_embedder(max_seq_length=20, overflow_strategy=strategy)
    vectors = asyncio.run(
        embedder.embed_documents(["aaaa bbbb. cccc dddd. eeee ffff."], titles=["T"])
    )
    assert fake.calls[0].texts == encoded
    assert vectors == expected


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


def make_title_prefix_embedder() -> tuple[TitlePrefixEmbedder, mock.AsyncMock]:
    inner = mock.create_autospec(Embedder, instance=True)
    inner.output_dimensionality = 1024
    inner.embed_documents.return_value = [[1.0]]
    inner.embed_query.return_value = [2.0]
    return TitlePrefixEmbedder(inner), inner


def test_title_prefix_prepends_the_title_to_each_document():
    embedder, inner = make_title_prefix_embedder()

    asyncio.run(embedder.embed_documents(["body one"], titles=["A Note"]))

    inner.embed_documents.assert_awaited_once_with(
        ["A Note\n\nbody one"], titles=["A Note"]
    )


def test_title_prefix_embeds_verbatim_without_titles():
    embedder, inner = make_title_prefix_embedder()

    asyncio.run(embedder.embed_documents(["body one"]))

    inner.embed_documents.assert_awaited_once_with(["body one"])


def test_title_prefix_passes_queries_straight_through():
    embedder, inner = make_title_prefix_embedder()

    assert asyncio.run(embedder.embed_query("a query")) == [2.0]
    inner.embed_query.assert_awaited_once_with("a query")


def test_title_prefix_reports_the_inner_dimensionality():
    embedder, _ = make_title_prefix_embedder()
    assert embedder.output_dimensionality == 1024
