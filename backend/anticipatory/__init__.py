"""Anticipatory commerce agent: predicts a shopper's filters word by word and commits early.

Standard library only. Modules, from the bottom up:

    config      all tunable numbers, as frozen dataclasses grouped per area
    tokens      word normalisation (case, punctuation, rupee forms)
    numbers     price and size numbers: digits, "3.5k", English and Hindi number words
    lexicon     vocabulary built from the catalogue, plus synonyms and cue words
"""
