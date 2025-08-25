from __future__ import annotations

import re
from typing import List, Optional, Tuple, TYPE_CHECKING

# ``PositionedWord`` is light-weight and importing it at runtime keeps this
# helper self contained.  The TYPE_CHECKING block avoids circular imports when
# building docs while still providing type hints during development.
if TYPE_CHECKING:
    from check_register.models import PositionedWord
else:  # pragma: no cover - imported lazily for runtime use
    from check_register.models import PositionedWord

_AMOUNT_RE = re.compile(r"\$-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")


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

    if not line_words:
        return None

    # Skip tokens until we encounter the ``Payable`` marker on the first line,
    # since everything before it is check metadata (number, date, status, etc.).
    tokens: List[PositionedWord] = []
    found_payable = False
    first_line = line_words[0]
    for w in first_line:
        if not found_payable:
            if w.text.upper() == 'PAYABLE':
                found_payable = True
            continue
        tokens.append(w)

    if not found_payable:
        return None

    # Include all subsequent lines as they belong to payee/description/amount.
    for lw in line_words[1:]:
        tokens.extend(lw)

    if not tokens:
        return None

    # Drop trailing amount token to avoid picking the wide gap before it.
    if _AMOUNT_RE.fullmatch(tokens[-1].text):
        tokens = tokens[:-1]
    if not tokens:
        return None

    # Merge any single-letter runs to avoid artificial gaps (e.g. ``P E R S``).
    tokens = _squeeze_letters(tokens)

    # Determine the column boundary by finding the split that minimises the
    # within-cluster variance of x positions.  This 1D k-means approach is
    # robust against uneven gaps and does not assume a particular number of
    # unique x values.
    xs = sorted(t.x0 for t in tokens)
    if len(xs) < 2:
        return None

    best_cost = float("inf")
    best_thresh = None
    for i in range(1, len(xs)):
        left = xs[:i]
        right = xs[i:]
        mean_l = sum(left) / len(left)
        mean_r = sum(right) / len(right)
        cost = sum((x - mean_l) ** 2 for x in left) + sum((x - mean_r) ** 2 for x in right)
        if cost < best_cost:
            best_cost = cost
            best_thresh = (xs[i - 1] + xs[i]) / 2.0

    if best_thresh is None:
        return None
    threshold = best_thresh

    payee_tokens = [t.text for t in tokens if t.x0 <= threshold]
    desc_tokens = [t.text for t in tokens if t.x0 > threshold]

    payee = " ".join(payee_tokens).rstrip(',').strip()
    desc = " ".join(desc_tokens).strip()

    if not payee and not desc:
        return None

    return payee, desc
