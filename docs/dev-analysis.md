# Dev data analysis (Stage 1)

Reproduce everything below with:

```
python backend/scripts/analyze_dev.py        # from the repo root, or from backend/
```

The script is read-only and deterministic. It uses a small "lite reader" (exact catalogue words plus hand-mined synonym tables) to find slot mentions and their word positions, and it scores a naive reference agent through the kit's own `evaluate.py`.

**Caveats.** The lite reader's tables were fitted to `dev.jsonl` (it reproduces all 300 gold filters), so its coverage says nothing about unseen wording. The naive agents are analysis references, not our agent. Numbers are on dev only.

---

## 1. Findings that change the plan

**F1. The score is mostly about reading correctly and not wasting searches; earliness is a bonus.**
The baseline's 20.0 comes from accuracy 0.527 (0.4 per correct request). An agent that reads every request correctly and never commits early scores **40.0** (accuracy 1.0, one free search). Perfect early commits add at most about 10 more (ceiling 49.8, slightly higher because `earliest` sits one word late in some requests, see F3). So the order of priority is: (1) read every request right, since 1% accuracy is worth 0.4 points; (2) keep extra searches near zero, since one extra search per request costs 2 points; (3) earliness, with zero wrong commits.

**F2. The oracle ceiling is low and uneven.**
Oracle earliness is 16.3% of a request overall: plain 19.0%, correction 12.2%, late-constraint 9.3%, code-mixed 20.0%. For 34% of requests the target is only pinned at the very last word. Average tail after the pin: 2.2 words.

**F3. `earliest` is the first word where the slots stated so far, with their final values, single out the target.**
In about 17% of requests it points at the marker word that closes a slot phrase ("M **size**", "Pacevo **brand**", "size 6 **UK**"), not at the value. Committing on the value itself is therefore one word earlier than the oracle, with no guessing.

**F4. Which slot completes the pin.** Size 36.7% (plus 11.3% on its marker word), price 18.7%, colour 14.0%, brand 11.3%, category only 1.7%. Slot necessity (removing it leaves more than one product): size 100% of requests that mention it, colour 95.7%, brand 77.8%, price 53.8%, **category only 30.3%**. Colour, brand and size often identify a product without the category. So: do not wait for the category, and price phrases must be parsed correctly and incrementally because they complete about a fifth of pins.

**F5. Searching before the size is known is wasted for sized categories.**
Mean candidates for sized requests as slots are added (category, colour, brand, size, price): 80, 17, 7.9, 1.5, 1.0. None is unique before the size; 61.8% are unique after it. Unsized requests (backpacks, caps, headphones, watches, wallets; 38 of 300): 28.9% unique after the brand. Rule of thumb for the search gate: search only when the size is known or the category has no sizes.

**F6. Only corrections endanger an early commit, not late constraints.**
Every slot value in a request is consistent with the target, so a unique match built from correctly read values can only be overturned by a correction (or a misread). Measured: the naive "commit at first unique product" is wrong in 0 of 177 plain requests and 0 of 50 late-constraint requests, but in 21 of 55 correction requests (7% of all requests). Late constraints cost earliness (their last mention completes the pin in 84% of cases, against 62% for plain requests) but not safety. The earlier assumption in the plan that late constraints invalidate commits was wrong; the plan is corrected.

**F7. Corrections: what they look like.**
55 requests (18%). Slot corrected: size 23, colour 18, brand 13, category 1. No request without the `correction` tag changes a slot value, so the tag is clean. Words between the wrong value and its replacement: 1 word: 6, 2: 13, 3 to 4: 15, 5 to 8: 10, 9 or more: 11. In 11 of 55 the replacement is the very last word.

**F8. Reference agents (scored with the kit's `evaluate.py` on dev).**

| Agent | Accuracy | Requests with wrong commit | Earliness | Searches | Score |
|---|---|---|---|---|---|
| Kit baseline | 0.527 | 0 | 0.0% | 1.53 | 20.0 |
| No early commit, perfect reading (arithmetic) | 1.000 | 0 | 0.0% | 1.00 | 40.0 |
| Naive eager (commit at first unique product) | 1.000 | 22 | 17.2% | 5.96 | 32.7 |
| Marker-aware, gated searches, hold 0 | 1.000 | 22 | 17.0% | 3.38 | 37.8 |
| Marker-aware, gated searches, hold 1 | 1.000 | 8 | 11.8% | 3.38 | 39.6 |
| Marker-aware, gated searches, hold 2 | 1.000 | 3 | 6.6% | 3.38 | 38.2 |
| Marker-aware, gated searches, hold 3 | 1.000 | 2 | 2.1% | 3.38 | 35.8 |

"Marker-aware" cancels a pending commit when a correction word appears; "hold" waits that many unchanged words before committing; "gated" searches only when the size is known or the category is unsized. A plain hold without markers does nothing useful (naive hold 1 to 3 still has 21 wrong requests). Correction requests are where it hurts: naive scores -5.9 on them.

**What this means:** a simple early-commit agent does not yet beat the 40.0 floor. To beat it we need to cut wasted searches (3.4 down to about 1.3 is worth about 4 points) and wrong commits (8 down to about 3 is worth about 2 points) while keeping the earliness (+7 points at 12%).

**F9. Why the marker-aware agent still fails (8 requests).** The marker arrives just after the hold ("size 6 UK, **wait**, I meant size 8"), or the correction follows a price clause ("in navy, within Rs. 1500, **no, change that to** Urbanyx"). Two ideas to test in Stage 6 (hypotheses, not measured): treat clause-ending punctuation on a word ("UK.", "10.") as a risk signal, since corrections and late constraints often start after a period; and use per-slot correction risk (size and colour are corrected most).

**F10. Number words are ambiguous at word level.**
"eight" is a size 8 or the start of "eight hundred" (dev-0122: the naive agent committed on "eight" and was wrong). Price phrases run up to four words ("four thousand five hundred"). Do not act on a number word until the next word shows the number is complete.

**F11. The vocabulary is small but the hidden set has unseen wording.**
300 requests use only 283 distinct tokens. Price wording: English words 77, plain digits 74, "k" form 42, comma digits 26, rupee sign 10, Hindi words 7. Generalisation (plural and singular, spelling variants, unseen number words) matters more than the dev coverage.

---

## 2. Revised targets

- **Gates:** zero wrong commits on dev (each exception documented); accuracy at or above the baseline's 0.527.
- **Floor:** 40.0 on dev (perfect reading, no early commit). Anything below that means the early-commit logic is losing points.
- **Goal:** 43 to 46 on dev. Ceiling about 50.
- **Searches:** about 1.5 per request or fewer.
- **Hidden set:** expect lower accuracy than dev because of unseen wording; every 1% accuracy is 0.4 points.
- **Latency:** well under 5 ms per word (rules only).

---

## 3. Lexicon wish-list for Stage 2

Everything here is what dev shows. Stage 2 must go beyond it (see "Generalise").

**Category synonyms:** bag pack, rucksack (backpacks); headset (headphones); hooded sweatshirt, sweatshirt (hoodies); denims (jeans); jogging shoes, runners, running sneakers (running shoes); floaters, slides (sandals); casual shoes, casual sneakers (sneakers); t shirt, tshirt, tee (t-shirts); joggers, trackpants (track pants); wrist watch, wristwatch (watches). Singular forms of every category ("shirt", "kurta", "dress", "hoodie", "jacket", "cap", "watch", "wallet").

**Colour:** gray (grey), golden (gold), navy blue (navy), olive green (olive); Hindi: kaala (black), laal (red), gulabi (pink), bhura (brown).

**Size:** small, medium, large, extra large, extra small, double XL, 2XL, XXL; number words six to eleven; "UK" before or after the number; "waist" for jeans; Hindi "das number" (10). Both orders ("size M", "M size").

**Price:** markers under, below, less than, not more than, max, up to, within, budget, Hindi "se kam", "tak", "ke andar". Units: Rs, Rs., rupees, the rupee sign, "k", hundred, thousand. Forms: plain digits, comma digits (4,500), "3.5k", "0.8k", English words ("forty five hundred", "one thousand seven hundred", "sixteen hundred"), Hindi words ("satrah sau", "paanch hazaar", "saadhe teen hazaar", "dhai hazaar").

**Correction markers (dev):** oops, sorry, actually, wait, I meant, I mean, no, no no, change that to, make that, make it, or rather, matlab, nahi.

**Late-constraint markers (dev):** and, oh and, and in, and size, also, make sure it's, it has to be, one more thing, aur, ek aur baat.

**Ignore (filler):** hey, hi, um, uh, hmm, please, thanks, "if you have it", "need it this week", "nothing too flashy", occasions and people (wedding, office, gym, gift, dad, brother), Hindi chahiye, dikhao (na), kya aapke paas, mujhe, mere liye, bhaiya, hai, ka, wala, milega.

**Generalise (not in dev, expected in the hidden set):** plural and singular of every word; spelling and hyphen variants (t-shirt, tee shirt, x-large, xxl); other number words and Hindi numbers; other synonyms for the 16 categories; other correction and late-constraint phrasings; possible brand misspellings. Prefer rules and normalisation over memorised strings.

---

## 4. Open questions for later stages

- **Search gating and the runtime rule.** The kit says products must be looked up through counted searches at run time. A gate based on vocabulary-level facts ("size known" or "category has no sizes") is fine. A local copy of the catalogue used to predict uniqueness would not be. Decide the exact gate in Stage 5 and keep it on the right side of that rule.
- **Wasted-search budget versus earliness:** one extra search costs about the same as half a word of earliness. Stage 5 should search at most once or twice per request.
- **Unmeasured ideas:** punctuation as a risk signal, per-slot correction risk, confirmation via a second matching word. Stage 6 measures them.
