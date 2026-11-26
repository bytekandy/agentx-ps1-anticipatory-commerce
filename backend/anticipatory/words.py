"""General English word frequencies: what counts as a real word, and how common it is.

The spelling corrector and the unknown-word detector both need to tell a real English word
("short", "skirt", "purple") from a typo ("snekers") or a name. A hand-written list of "words
not to touch" never ends, so the knowledge comes from data: the 60,000 most frequent words of a
large web corpus with their counts (`data/english_words.tsv`). Standard library only, loaded
once, about 20 ms.
"""
from pathlib import Path
from typing import Dict, Optional

DEFAULT_WORDS_PATH = Path(__file__).resolve().parent / "data" / "english_words.tsv"


class EnglishWords:
    def __init__(self, counts: Dict[str, int]):
        self._count = counts
        ordered = sorted(counts, key=counts.get, reverse=True)
        self._rank = {w: i for i, w in enumerate(ordered)}

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "EnglishWords":
        counts: Dict[str, int] = {}
        with open(path or DEFAULT_WORDS_PATH, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                word, _, count = line.partition("\t")
                counts[word] = int(count)
        return cls(counts)

    def count(self, word: str) -> int:
        """How often the word occurs in the corpus; 0 if it is not among the top 60,000."""
        return self._count.get(word, 0)

    def rank(self, word: str) -> Optional[int]:
        """0 for the most frequent word, None if not in the list."""
        return self._rank.get(word)

    def __contains__(self, word: str) -> bool:
        return word in self._count

    def is_stopword(self, word: str, top: int = 300) -> bool:
        """One of the `top` most frequent words ("the", "you", "my", "for"...)."""
        rank = self._rank.get(word)
        return rank is not None and rank < top

    def __len__(self) -> int:
        return len(self._count)


_shared: Optional[EnglishWords] = None


def english_words() -> EnglishWords:
    """The shared instance, loaded on first use."""
    global _shared
    if _shared is None:
        _shared = EnglishWords.from_file()
    return _shared
