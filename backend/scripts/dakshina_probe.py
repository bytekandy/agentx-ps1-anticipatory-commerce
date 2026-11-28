"""What Google's Dakshina dataset (romanised Hindi, CC BY-SA 4.0) can and cannot do for this agent.

    cd backend && python scripts/dakshina_probe.py [--keep DIR]

The dataset is one 2.0 GB tar of 12 languages. This script reads the tar's headers with HTTP range
requests and downloads only the Hindi lexicon files and the romanised sentence file (about 5 MB),
into a temporary folder (or `--keep DIR`). It then prints the two checks that decided how the data
is NOT used:

  1. Romanisation key. How many attested spelling variants of one Hindi word does the key behind
     `Lexicon.respell` merge, and how many other Hindi words does it wrongly respell onto one of our
     listed words? (Finding: the key is precise; widening it only adds wrong matches.)
  2. Word list. Which real brand names would a "known Hindi word" list hide from the unknown-word
     detector? (Finding: Gucci, Tata and Amazon are among the words, so no frequency threshold
     separates Hindi words from brands.)

Standard library only. The data is untrusted input: it is only read as text and split on tabs.
"""
import argparse
import collections
import itertools
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anticipatory.lexicon import Lexicon, transliteration_key  # noqa: E402
from anticipatory.tokens import english_words  # noqa: E402

URL = "https://storage.googleapis.com/gresearch/dakshina/dakshina_dataset_v1.0.tar"
TOTAL = 2008340480
WANT = ("dakshina_dataset_v1.0/hi/lexicons/", "dakshina_dataset_v1.0/hi/romanized/hi.romanized.rejoined.tsv")
BRANDS = ("nike", "adidas", "puma", "levis", "zara", "reebok", "fila", "wrangler", "samsung", "apple",
          "sony", "honda", "google", "gucci", "boat", "bose", "tata", "amazon", "rolex", "casio")


def _get(a: int, b: int) -> bytes:
    request = urllib.request.Request(URL, headers={"Range": f"bytes={a}-{b}"})
    return urllib.request.urlopen(request, timeout=60).read()


def fetch(out: Path) -> None:
    """Walk the tar headers and write the wanted members under `out`."""
    pos = 0
    while pos < TOTAL:
        header = _get(pos, pos + 511)
        if len(header) < 512 or not header.strip(b"\0"):
            break
        name = header[:100].split(b"\0")[0].decode("utf-8", "replace")
        size = int(header[124:136].split(b"\0")[0].strip() or b"0", 8)
        if name.startswith(WANT) and header[156:157] in (b"0", b"\0"):
            target = (out / name).resolve()
            if out.resolve() not in target.parents:
                raise ValueError(f"unsafe path in archive: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_get(pos + 512, pos + 511 + size))
        pos += 512 + ((size + 511) // 512) * 512


def load(root: Path):
    base = root / "dakshina_dataset_v1.0" / "hi"
    natives, count = collections.defaultdict(set), collections.Counter()
    pairs = collections.defaultdict(set)
    for split in ("train", "dev", "test"):
        for line in (base / "lexicons" / f"hi.translit.sampled.{split}.tsv").read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[1].isalpha() and parts[1].isascii():
                natives[parts[1].lower()].add(parts[0])
                pairs[parts[0]].add(parts[1].lower())
    sentences = collections.Counter()
    for line in (base / "romanized" / "hi.romanized.rejoined.tsv").read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            sentences.update(w.lower() for w in re.findall(r"[A-Za-z]+", parts[1]))
    return natives, pairs, sentences


def key_check(natives, pairs, sentences) -> None:
    lexicon, english = Lexicon.from_catalogue(), english_words()
    variant_pairs = [(a, b) for rs in pairs.values() for a, b in itertools.combinations(sorted(rs), 2)]
    merged = sum(1 for a, b in variant_pairs if transliteration_key(a) == transliteration_key(b))
    print(f"variant pairs of one Hindi word: {len(variant_pairs)}; merged by our key: {merged / len(variant_pairs):.1%}")
    listed = {k[0]: e for k, e in lexicon._table.items() if len(k) == 1 and e.kind == "synonym"
              and len(k[0]) >= 4 and (english.rank(k[0]) is None or english.rank(k[0]) > 20000)}
    by_key = collections.defaultdict(set)
    for word in listed:
        by_key[transliteration_key(word)].add(word)
    right = wrong = unknown = 0
    for word in set(natives) | set(sentences):
        if len(word) < 4 or word in lexicon.known_words or transliteration_key(word) not in by_key:
            continue
        target = sorted(by_key[transliteration_key(word)])[0]
        if natives.get(word) and natives.get(target):
            right, wrong = right + bool(natives[word] & natives[target]), wrong + (not natives[word] & natives[target])
        else:
            unknown += 1
    print(f"respelled onto one of our {len(listed)} listed words: same Hindi word {right}, "
          f"a different word {wrong}, cannot tell {unknown}")


def brand_check(sentences) -> None:
    print("real brand names in the romanised sentences (count):",
          {b: sentences[b] for b in BRANDS if sentences[b]})
    for threshold in (2, 4, 8):
        words = {w for w, c in sentences.items() if c >= threshold}
        print(f"  list of words seen >= {threshold} times: {len(words)} words; hides brands: "
              f"{[b for b in BRANDS if b in words]}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep", help="download into this folder and keep it")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(args.keep or tmp)
        if not (root / "dakshina_dataset_v1.0").exists():
            root.mkdir(parents=True, exist_ok=True)
            fetch(root)
        natives, pairs, sentences = load(root)
        print(f"Hindi lexicon: {len(natives)} romanised words; sentences: {len(sentences)} word types")
        key_check(natives, pairs, sentences)
        brand_check(sentences)
    return 0


if __name__ == "__main__":
    sys.exit(main())
