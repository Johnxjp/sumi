from src.retrieval.cleaner import clean_text

NBSP = chr(0xA0)
ZERO_WIDTH_SPACE = chr(0x200B)
BOM = chr(0xFEFF)
NUL = chr(0)
COMBINING_ACUTE = chr(0x301)


def test_strips_and_collapses_spaces():
    assert clean_text("  hello   world  ") == "hello world"


def test_normalizes_newlines():
    assert clean_text("a\r\nb\rc") == "a\nb\nc"


def test_collapses_blank_lines_to_one_paragraph_break():
    assert clean_text("para one\n\n\n\npara two") == "para one\n\npara two"


def test_strips_spaces_around_newlines():
    assert clean_text("line one \n line two") == "line one\nline two"


def test_removes_control_and_zero_width_chars():
    assert clean_text(f"a{NUL}b{ZERO_WIDTH_SPACE}c{BOM}d") == "abcd"


def test_nfkc_folds_ligatures_and_fullwidth():
    assert clean_text("ﬁle") == "file"
    assert clean_text("Ｆｕｌｌ") == "Full"


def test_nfkc_converts_nbsp_to_space():
    assert clean_text(f"one{NBSP}two") == "one two"


def test_nfkc_composes_combining_accents():
    assert clean_text(f"e{COMBINING_ACUTE}") == "é"
