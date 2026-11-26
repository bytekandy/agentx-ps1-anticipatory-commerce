"""Anticipatory commerce agent: predicts a shopper's filters word by word and commits early.

Standard library only. Modules, from the bottom up:

    config        all tunable numbers, as frozen dataclasses grouped per area
    tokens        word normalisation (case, punctuation, rupee forms) and English word frequencies
    numbers       price and size numbers: digits, "3.5k", English and Hindi number words
    lexicon       vocabulary built from the catalogue, plus synonyms and cue words
    spelling      noisy-channel spelling correction of the words that name a product
    slots         slot mentions (category, colour, brand, size, prices) from the words so far
    unknown       constraints we cannot represent: unknown brand, size, colour or style
    state         filter state: one belief per slot, revisions, pending corrections and numbers
    risk          how likely a commit is to be wrong: the RiskModel interface, HeuristicRisk
    policy        the catalogue port (counted searches, test stand-in), and when to search and commit
    agent         the orchestrator (kit Agent interface) and its per-word trace record
"""
