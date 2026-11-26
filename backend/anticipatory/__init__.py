"""Anticipatory commerce agent: predicts a shopper's filters word by word and commits early.

Standard library only. Modules, from the bottom up:

    config        all tunable numbers, as frozen dataclasses grouped per area
    tokens        word normalisation (case, punctuation, rupee forms)
    numbers       price and size numbers: digits, "3.5k", English and Hindi number words
    lexicon       vocabulary built from the catalogue, plus synonyms and cue words
    words         general English word frequencies (what is a real word, what is a function word)
    spelling      noisy-channel spelling correction of the words that name a product
    slots         slot mentions (category, colour, brand, size, prices) from the words so far
    unknown       constraints we cannot represent: unknown brand, size, colour or style
    state         filter state: one belief per slot, revisions, pending corrections and numbers
    catalog_port  the only door to the catalogue (counted searches), plus a test stand-in
    risk          how likely a commit is to be wrong: the RiskModel interface, HeuristicRisk
    policy        when to search and when to commit (expected-value break-even rule)
    trace         one record per word: reading, action, reason
    agent         the orchestrator that implements the kit's Agent interface
"""
