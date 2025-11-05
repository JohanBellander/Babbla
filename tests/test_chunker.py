from voicecli.chunker import chunk_text


def test_split_basic():
    text = "Hello world! This is VoiceCLI. Enjoy streaming."
    chunks = chunk_text(text, max_chars=25)

    assert chunks == [
        "Hello world!",
        "This is VoiceCLI.",
        "Enjoy streaming.",
    ]


def test_max_length_boundary():
    text = "Sentence one. Sentence two is slightly longer but still fine."
    chunks = chunk_text(text, max_chars=30)

    assert chunks[0] == "Sentence one."
    assert chunks[1] == "Sentence two is slightly longer"
    assert chunks[2] == "but still fine."


def test_long_token_split():
    text = "Supercalifragilisticexpialidocious!"
    chunks = chunk_text(text, max_chars=10)

    assert chunks == [
        "Supercali-",
        "fragilist-",
        "icexpiali-",
        "docious!",
    ]


def test_trailing_punctuation():
    text = "Wait... What?! Really???"
    chunks = chunk_text(text, max_chars=20)

    assert chunks == ["Wait...", "What?!", "Really???"]


def test_empty_input_returns_empty_list():
    assert chunk_text("   \n\t") == []
