import re
import unicodedata


def clean_text(text: str) -> str:
    r"""Normalize a document to clean plain text.

    Applies NFKC unicode normalization, normalizes newlines to ``\n``,
    removes control and zero-width characters, collapses whitespace runs,
    and reduces blank-line runs to a single blank line so paragraph
    boundaries survive for the chunker.
    """
    junk_chars = (
        "[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f"
        "\\u007f-\\u009f\\u200b-\\u200d\\u2060\\ufeff]"
    )
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(junk_chars, "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
