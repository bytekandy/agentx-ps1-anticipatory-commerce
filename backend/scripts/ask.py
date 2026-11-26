"""Ask the agent from the terminal: no server, no UI, no installs.

    cd backend
    python scripts/ask.py "beige Loomsy sneakers size 10 under 3000"
    python scripts/ask.py                        # asks you to type a request
    python scripts/ask.py "..." --agent learned  # hybrid (default), heuristic or learned

Prints one line per word (what the agent understood, how sure it is, and whether it committed to a
product early), then the final answer. Words are fed one at a time exactly as the evaluator does.
"""
import argparse
import importlib
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import evaluate  # noqa: E402  (the kit's scorer: its Tools object counts searches)
from anticipatory.lexicon import load_rows  # noqa: E402

AGENTS = {"hybrid": "agent", "heuristic": "agent_heuristic", "learned": "agent_learned"}


def describe(row) -> str:
    size = f", size {row['size']}" if row["size"] else ""
    return f"{row['title']} ({row['product_id']}, {row['brand']}, {row['colour']}{size}, Rs. {row['price']})"


def ask(text: str, agent: str = "hybrid", out=print) -> None:
    words = text.split()
    if not words:
        out("Nothing to ask.")
        return
    rows = {r["product_id"]: r for r in load_rows()}
    tools = evaluate.Tools()
    bot = importlib.import_module(AGENTS[agent]).Agent(tools)
    bot.start("ask")
    committed = None
    for word in words:
        reply = bot.observe(word)
        record = bot.trace[-1]
        filters = ", ".join(f"{k}={v}" for k, v in record.filters.items() if v is not None) or "nothing yet"
        line = f"{word:<14} sure {record.confidence:.2f}  {filters}"
        if record.unresolved:
            line += f"   [not understood: {', '.join(record.unresolved)}]"
        if "commit" in reply and committed is None:
            committed = (record.index, reply["commit"])
            line += f"\n  >>> COMMIT after word {record.index}: {describe(rows[reply['commit']])}"
        out(line)
    final = bot.finish()
    out("")
    if committed:
        out(f"Committed early after word {committed[0]} of {len(words)}.")
    else:
        out("No early commit (the agent waited until the end).")
    out("Final answer: " + (describe(rows[final]) if final in rows else "no product matched"))
    out(f"Searches used: {tools.searches}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="the request; leave out to be asked")
    parser.add_argument("--agent", choices=sorted(AGENTS), default="hybrid")
    args = parser.parse_args(argv)
    ask(args.text if args.text is not None else input("What do you want? "), args.agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
