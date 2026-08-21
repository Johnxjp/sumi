from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(
    text: str,
    max_chunk_size: int = 2000,
    min_chunk_size: int = 200,
    chunk_overlap: int = 50,
) -> list[str]:
    """Split text into chunks of at most max_chunk_size characters.

    Wraps langchain's RecursiveCharacterTextSplitter, configured to break on
    paragraph, then line, then sentence, then word boundaries. chunk_overlap
    is in characters; the splitter carries whole trailing sentences into the
    next chunk where possible. Text that fits in one chunk is returned whole,
    and a final chunk shorter than min_chunk_size is folded into the previous
    chunk.
    """
    if min_chunk_size >= max_chunk_size:
        raise ValueError("min_chunk_size must be smaller than max_chunk_size")
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        keep_separator="end",
        chunk_size=max_chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = splitter.split_text(text)
    return _fold_small_last_chunk(chunks, min_chunk_size)


def _fold_small_last_chunk(chunks: list[str], min_chunk_size: int) -> list[str]:
    if len(chunks) < 2 or len(chunks[-1]) >= min_chunk_size:
        return chunks
    last = chunks.pop()
    prev = chunks[-1]
    # The last chunk may start with overlap already present at the end of the
    # previous chunk; merge only the part that is new.
    overlap_len = next(k for k in range(len(last), -1, -1) if prev.endswith(last[:k]))
    remainder = last[overlap_len:]
    if overlap_len == 0:
        chunks[-1] = f"{prev} {remainder}"
    elif remainder:
        chunks[-1] = prev + remainder
    return chunks
