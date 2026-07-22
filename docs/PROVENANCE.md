# Provenance and durable attribution

In this project, provenance means a checkable account of how an output was
produced. It is closer to a receipt or chain of custody than a watermark.

Useful provenance answers these questions:

- Which City document supplied the information?
- Where did that exact document come from?
- Which document bytes and pages were processed?
- Which parser version and settings produced the result?
- Did the extracted checks reconcile to the published total?
- What warnings, corrections, or known limitations applied?
- Who created the original tool and who modified the version in use?

## Current foundations

The archive already preserves canonical source files, source URLs, publication
metadata, file identifiers, checksums, revisions, and standard artifact names.
The parser also reports whether a register reconciles. These pieces make many
results auditable, but not every output is yet self-describing.

## Direction for generated outputs

Future output work should make attribution and provenance travel with the
result:

- Human-facing HTML and project-generated PDF reports should visibly identify
  the project, creator, parser version, source document, and limitations.
- CSV and JSON output should remain easy to consume and be accompanied by a
  small provenance manifest when the format cannot carry the information
  cleanly.
- Provenance manifests should record source URLs, source and artifact
  checksums, relevant page ranges, parser release or commit identifier,
  generation time, reconciliation status, and warnings.
- Modified versions should identify their maintainers and changes without
  implying endorsement by the original creator or the City.

No technical measure can prevent someone from deleting attribution. Making
legitimate outputs consistently self-identifying raises the effort required to
remove their history and makes intact, reproducible results easier to
recognize.
