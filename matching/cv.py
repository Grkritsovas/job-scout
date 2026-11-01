"""Short overlapping CV passages for semantic evidence retrieval."""


def chunk_cv_text(cv, words_per_chunk=80, overlap_words=20):
    words = str(cv or "").split()
    chunks = []
    for start in range(0, len(words), words_per_chunk - overlap_words):
        chunks.append(" ".join(words[start : start + words_per_chunk]))
        if start + words_per_chunk >= len(words):
            break
    return chunks
