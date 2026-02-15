def get_words(text: str) -> list:
    return [w.lower() for w in text.split() if w]
