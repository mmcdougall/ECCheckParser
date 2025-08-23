"""Core payee/description splitting logic.

Heavy heuristics live in :mod:`heuristics`, leaving this module to focus on
tokenisation, voting and a bit of post-processing.  Keeping the heuristics
separate makes the core easier for humans to read.
"""

import re
from typing import List, Tuple

from .constants import PREFIX_SET
from .heuristics import HEURISTICS


def split_payee_desc_block(block: str) -> Tuple[str, str]:
    """Split a block containing payee and description using weighted votes.

    The input ``block`` is tokenised and each heuristic votes on where the
    payee/description boundary should fall.  The boundary with the highest
    total weight wins.  ``heuristics.py`` contains the individual voting rules.
    """

    block = (
        block.replace("\r", " ")
        .replace("\n", " ")
        .replace(" ,", ",")
        .strip()
    )
    block = re.sub(",(?=[A-Za-z])", ", ", block)
    if not block:
        return ("", "")

    tokens = block.split()
    if not tokens:
        return ("", "")

    # Merge single-letter prefixes such as ``A B C`` -> ``ABC`` when recognised.
    i = 0
    letters: List[str] = []
    while i < len(tokens):
        tok = tokens[i]
        stripped = tok.rstrip(".,")
        if len(stripped) == 1 and stripped.isalpha():
            letters.append(stripped.upper())
            i += 1
        else:
            break
    if len(letters) > 1:
        joined = "".join(letters)
        if joined in PREFIX_SET:
            tokens = [joined] + tokens[i:]

    if len(tokens) == 1:
        return (tokens[0], "")

    scores = [0] * len(tokens)

    def vote(idx: int, weight: int) -> None:
        if 1 <= idx < len(tokens):
            scores[idx] += weight

    for _name, weight, func in HEURISTICS:
        idx = func(tokens, block)
        if idx is not None:
            vote(idx, weight)

    best_idx = max(range(1, len(tokens)), key=lambda i: (scores[i], -i))

    payee = " ".join(tokens[:best_idx]).rstrip(",").strip()
    desc = " ".join(tokens[best_idx:]).strip()

    # Convert "LAST, FIRST" into a nicer upper-case form.
    if "," in payee:
        parts = [p.strip() for p in payee.split(",")]
        if len(parts) == 2 and parts[0].istitle() and parts[1].istitle():
            payee = " ".join(parts).upper()

    return (payee, desc)

