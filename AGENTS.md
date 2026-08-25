# AGENTS guidelines

This repository houses a parser that extracts the City of El Cerrito's monthly check register from council agenda packet PDFs. The project includes source PDFs and generated artifacts used for regression testing.

## Development environment

- Use Python 3.11 or newer. The `.python-version` file selects 3.11 as a local default, not as the only supported version.
- Create a virtual environment and install the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
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
- Keep side effects local: helpers should either mutate state or format output, but not both.

## Comment style

- Describe current behavior in the present tense; avoid references to past implementations.
- Do not restate repository policies or coding practices in code comments.
- Avoid comments that simply repeat prompts or code review feedback.

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

- `data/originals/<meeting-type>/YYYY/agenda-packets/` holds canonical agenda
  packet PDFs downloaded from [www.elcerrito.gov](https://www.elcerrito.gov).
  Use `city-council` and `financial-advisory-board` as the supported meeting
  types.
- Prior packet and agenda versions live under `agenda-packet-revisions/` and
  `agenda-revisions/`; each meeting type/year has a `manifest.json` retaining
  source metadata.
- `data/artifacts/` stores parser outputs such as chunk archives used in tests.
- The number of data artifacts grows as new agenda packets are added; tests should
  reference specific files instead of iterating the entire directory.

Note: originals may be reissued. The CivicClerk archiver preserves superseded
files in the revision directories and keeps only the latest downloaded version
in the canonical directory. Ensure tests reference canonical files and check
that referenced files exist.

### Archive artifact policy

- The archive is the local historical collection of canonical originals, check
  register PDFs, CSVs, chunk JSON, payee HTML, and quarterly financial report
  PDFs. Preserve this layout so it remains useful for browsing records over
  time as well as for regression tests.
- Generate standard check-register artifacts from the newest canonical agenda
  packet only. Do not retain parallel peer artifacts from a superseded packet
  revision. Keep the source revision under `data/originals/`; replace its
  derived artifact when a newer packet contains the same report.
- Standard register artifacts use the register-month stem in all four
  directories: `pdfs/YYYY-MM-register.pdf`, `csv/YYYY-MM.csv`,
  `chunks/YYYY-MM-chunks.json`, and `html/YYYY-MM-payees.html`.
- Before replacing an archived CSV, compare it with the existing CSV. When it
  changes, call out the changed checks, fields, or totals in the PR summary
  and update the matching PDF, chunk JSON, and payee HTML as one artifact
  refresh. Treat this as a minor archive-data update, separate from parser
  code changes.
- Use `check_register_parser.py --audit-archive` to maintain coverage. For
  each reported missing month, first locate or cache its canonical agenda
  packet, then extract and reconcile the register and add the complete
  four-file artifact set. If no source packet or register is available, leave
  the gap visible in the audit until its source can be obtained.
- Store intentionally nonstandard, exploratory, or one-off output beneath
  `data/artifacts/investigations/`; do not mix it with the canonical register
  HTML set. Use a descriptive, date-prefixed filename and do not rely on it in
  regression tests unless it is promoted to a standard artifact.

## Running the parser

To generate a CSV from the 2025 statements run:

```bash
python check_register_parser.py "data/originals/city-council/2025/agenda-packets/2025-08-19 Agenda Packet.pdf" --csv out.csv
```

Each PDF should log `✔ reconciled`. The resulting CSV confirms the parser still works. Run the parser when modifying code that can affect extraction behavior.
