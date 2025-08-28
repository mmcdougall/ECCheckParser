# AGENTS guidelines

This repository houses an offline parser that extracts the City of El Cerrito's monthly check register from council agenda packet PDFs. The project ships sample data and pre-built wheels so it runs without network access, including in OpenAI's Codex environment.

## Codex environment

- Python 3.11 is pinned via `.python-version`. If `pyenv` lacks it, run `pyenv install -s 3.11`.
- Create a virtual environment with the offline wheels:

```bash
./scripts/codex_setup.sh  # uses python3.11 internally
```

  or manually:

```bash
python -m venv codex-wheel-build
source codex-wheel-build/bin/activate
pip install --no-index --find-links vendor/wheels-linux -r requirements.txt
```

- Keep the working tree clean (`git status --short`) and make small, focused commits.

## Pull requests

- Pull requests are squashed on merge.
- End your PR summaries with a suggested one-line commit message for the squash merge.

## Code style

- Favor small, readable functions (roughly 20–40 lines) with descriptive names.
- Split complex logic into helpers rather than relying on heavy comments.
- When adding code, mimic the style, spacing, separations, line-feeds and line layouts of the surrounding code
- Match existing looping patterns (for-loops, comprehensions) and other common idioms.

## Comment style

- Describe current behavior in the present tense; avoid references to past implementations.

## `TODO` comments

- Flag future work or cleanup. Keep them concise (ideally ≤50 characters) 
- When possible outline scope or challenges (e.g., "large effort", "minor cleanup"). 


## Tests

Contributions must preserve or improve payee and description extraction accuracy. Run the unit tests:

```bash
python -m unittest discover -s tests
```

Accuracy tests such as `tests/test_june_2025_payees.py`, `tests/test_jul_aug_2025_top_payees.py`, and `tests/test_payee_splitter.py` enforce these thresholds.
Do not lower these thresholds without clear justification (e.g., correcting an incorrect prior unit test).

## Testing and artifacts

If parser changes might affect output, regenerate sample artifacts:

```bash
./scripts/build_register_archive.sh
```

When tests most naturally use "heavy" artifacts or originals, consider adding a "TODO" around reducing the time required to run the new test
Test with the smallest artifact possible (or use mocks). 

Regenerate artifacts in a separate pull request from the code changes; never combine code changes and data artifacts in the same PR.

## Data: originals and artifacts

- `data/originals/` holds agenda packet PDFs downloaded from [www.elcerrito.gov](https://www.elcerrito.gov).
- `data/artifacts/` stores parser outputs such as chunk archives used in tests.

## Running the parser

To generate a CSV from the 2025 statements run:

```bash
check_register_parser.py data/originals/2025/"Agenda Packet (8.19.2025).pdf" --csv out.csv
```

Each PDF should log `✔ reconciled`. The resulting CSV confirms the parser still works. Run the parser when modifying code to verify behavior offline.
