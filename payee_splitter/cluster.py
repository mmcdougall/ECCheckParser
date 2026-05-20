from __future__ import annotations

import re
from typing import List, Optional, Tuple, TYPE_CHECKING

from .core import _tidy_text

# ``PositionedWord`` is light-weight and importing it at runtime keeps this
# helper self contained.  The TYPE_CHECKING block avoids circular imports when
# building docs while still providing type hints during development.
if TYPE_CHECKING:
    from check_register.models import PositionedWord
else:  # pragma: no cover - imported lazily for runtime use
    from check_register.models import PositionedWord

_AMOUNT_RE = re.compile(r"\$?-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")


def _squeeze_letters(tokens: List[PositionedWord]) -> List[PositionedWord]:
    """Merge runs of single letters into a single token.

    Some payees such as ``P E R S`` have their letters extracted as separate
    PDF words.  These individual tokens confuse the column split logic because
    the gaps between letters can exceed the gap to the description column.  We
    merge adjacent single-letter tokens when their x-distance is tiny to
    reconstruct the original word.
    """

    if not tokens:
        return tokens

    squeezed: List[PositionedWord] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if len(t.text) == 1 and t.text.isalpha():
            letters = [t.text]
            x_last = t.x0
            j = i + 1
            while (
                j < len(tokens)
                and len(tokens[j].text) == 1
                and tokens[j].text.isalpha()
                and tokens[j].x0 - x_last <= 6  # small gap indicates same word
            ):
                letters.append(tokens[j].text)
                x_last = tokens[j].x0
                j += 1
            if len(letters) > 1:
                squeezed.append(PositionedWord(text="".join(letters), x0=t.x0))
                i = j
                continue
        squeezed.append(t)
        i += 1
    return squeezed


def _collect_tokens_after_payable(
    line_words: List[List[PositionedWord]],
) -> Optional[List[PositionedWord]]:
    """Gather tokens starting after the ``PAYABLE`` marker.

    The first line holds check metadata followed by the literal marker
    ``PAYABLE``.  Tokens to its right belong to the payee and description
    columns.  All subsequent lines are part of the entry and are appended as
    is.  Returns ``None`` when the marker is absent or no tokens follow it.
    """

    if not line_words:
        return None

    tokens: List[PositionedWord] = []
    found = False
    for w in line_words[0]:
        if not found:
            if w.text.upper() == "PAYABLE":
                found = True
            continue
        tokens.append(w)

    if not found:
        return None

    for lw in line_words[1:]:
        tokens.extend(lw)

    return tokens or None


def _drop_trailing_amount(tokens: List[PositionedWord]) -> List[PositionedWord]:
    """Remove a trailing amount token, if present.

    Amounts follow the description and use a wide preceding gap that could be
    mistaken for the column split.  Trimming that token ensures threshold
    detection only sees payee and description words.
    """

    if tokens and _AMOUNT_RE.fullmatch(tokens[-1].text):
        tokens = tokens[:-1]
        if tokens and tokens[-1].text == "$":
            tokens = tokens[:-1]
    return tokens


def _determine_column_threshold(tokens: List[PositionedWord]) -> Optional[float]:
    """Find the x boundary separating payee and description tokens.

    The algorithm enumerates all potential splits, computing the sum of squared
    distances to each side's mean x position.  The split with the minimal cost
    acts as a 1D k-means clustering and yields the threshold.  ``None`` is
    returned when the search lacks enough distinct positions.
    """

    xs = sorted(t.x0 for t in tokens)
    if len(xs) < 2:
        return None

    best_cost = float("inf")
    best_thresh: Optional[float] = None
    for i in range(1, len(xs)):
        left = xs[:i]
        right = xs[i:]
        mean_l = sum(left) / len(left)
        mean_r = sum(right) / len(right)
        cost = sum((x - mean_l) ** 2 for x in left) + sum((x - mean_r) ** 2 for x in right)
        if cost < best_cost:
            best_cost = cost
            best_thresh = (xs[i - 1] + xs[i]) / 2.0

    return best_thresh


def split_payee_desc_by_x(line_words: List[List[PositionedWord]]) -> Optional[Tuple[str, str]]:
    """Split payee/description using x-coordinate clustering.

    The parser provides ``line_words`` which captures each PDF word and its
    starting ``x`` position.  Typical check register entries show the payee and
    description separated into two vertical columns.  By clustering ``x``
    coordinates we can infer the boundary between the two columns and avoid
    relying on brittle text heuristics.

    Parameters
    ----------
    line_words:
        Tokenised words for each line with their ``x0`` coordinates.

    Returns
    -------
    tuple of (payee, description) or ``None`` if the data doesn't resemble the
    expected pattern.
    """

    tokens = _collect_tokens_after_payable(line_words)
    if not tokens:
        return None

    tokens = _drop_trailing_amount(tokens)
    if not tokens:
        return None

    tokens = _squeeze_letters(tokens)

    threshold = _determine_column_threshold(tokens)
    if threshold is None:
        return None

    payee_tokens = [t.text for t in tokens if t.x0 <= threshold]
    desc_tokens = [t.text for t in tokens if t.x0 > threshold]

    payee = _tidy_text(" ".join(payee_tokens).rstrip(',').strip())
    desc = _tidy_text(" ".join(desc_tokens).strip())

    if not payee and not desc:
        return None

    return payee, desc
