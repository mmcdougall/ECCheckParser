# Reference documents

This collection holds standalone public records and source-backed background
that do not belong to a recurring meeting-document or parser-output series.

- [City finance](city-finance/README.md): Financial Advisory Board enabling
  legislation and history, and California State Auditor correspondence and reports.

Use descriptive topic directories and date-prefixed filenames when a document
has a known date. For undated documents, use a retrieval-date prefix and identify
it as a snapshot. Retain original downloaded bytes, a source URL, retrieval date,
and SHA-256 checksum in the topic's manifest. Keep text extractions and editorial
background clearly identified. Preserve superseded reference copies and record
their relationship if a source changes.

Meeting agendas, packets, minutes, and work plans remain under
`data/originals/<meeting-type>/YYYY/`. Parser outputs and one-off analysis remain
under `data/artifacts/`, including `data/artifacts/investigations/`. The existing
`--audit-originals` and `--audit-archive` commands do not cover this reference
collection; its integrity metadata lives in its own manifests.

Downloaded public records retain their original source and rights status; see
the repository's [notice](../../NOTICE.md).
