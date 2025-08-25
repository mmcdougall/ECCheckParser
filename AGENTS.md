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

## Code style

- Favor small, readable functions (roughly 20–40 lines) with descriptive names.
- Split complex logic into helpers rather than relying on heavy comments.

## Tests

Contributions must preserve or improve payee and description extraction accuracy. Run the unit tests:

```bash
python -m unittest discover -s tests
```

Accuracy tests such as `tests/test_june_2025_payees.py`, `tests/test_jul_aug_2025_top_payees.py`, and `tests/test_payee_splitter.py` enforce these thresholds.

## Testing and artifacts

If parser changes might affect output, regenerate sample artifacts:

```bash
for pdf in data/originals/2025/*.pdf; do
  python scripts/build_register_archive.py "$pdf"
done
```

ALWAYS regenerate artifacts in separate pull request from the code changes that triggered them. Never mix code code changes and data artifacts in a pull request.

## Data: originals and artifacts

- `data/originals/` holds agenda packet PDFs downloaded from [www.elcerrito.gov](https://www.elcerrito.gov).
- `data/artifacts/` stores parser outputs such as chunk archives used in tests.

## Running the parser

To generate a CSV from the 2025 statements run:

```bash
check_register_parser.py data/originals/2025/"Agenda Packet (8.19.2025).pdf" --csv out.csv
```

Each PDF should log `✔ reconciled`. The resulting CSV confirms the parser still works. Run the parser when modifying code to verify behavior offline.
