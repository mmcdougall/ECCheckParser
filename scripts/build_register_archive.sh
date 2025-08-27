#!/usr/bin/env bash
set -euo pipefail

# Generate register artifacts for all agenda packet PDFs under the originals
# directory using the check_register_parser CLI. Artifacts are stored under
# data/artifacts by default. Outputs include register PDFs, CSVs, chunk JSON,
# and payee quadtree HTML.

if [[ $# -gt 2 ]]; then
  echo "Usage: $0 [originals-dir] [archive-dir]" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
originals_dir="${1:-$repo_root/data/originals}"
archive_dir="${2:-$repo_root/data/artifacts}"
parser="$repo_root/check_register_parser.py"

pdf_dir="$archive_dir/pdfs"
csv_dir="$archive_dir/csv"
chunk_dir="$archive_dir/chunks"
html_dir="$archive_dir/html"
mkdir -p "$pdf_dir" "$csv_dir" "$chunk_dir" "$html_dir"

find "$originals_dir" -type f -name '*.pdf' -print0 | sort -z | \
  while IFS= read -r -d '' packet_pdf; do
    tmpdir=$(mktemp -d)
    (
      cd "$tmpdir"
      "$parser" "$packet_pdf" --pdf --csv --chunks-json --html
    )

    prefix=$(cd "$tmpdir" && ls *.csv)
    prefix="${prefix%.csv}"

    mv "$tmpdir/${prefix}-register.pdf" "$pdf_dir/"
    mv "$tmpdir/${prefix}.csv" "$csv_dir/"
    mv "$tmpdir/${prefix}-chunks.json" "$chunk_dir/"
    mv "$tmpdir/${prefix}-payees.html" "$html_dir/"
    rm -rf "$tmpdir"

    echo "Archive updated: $pdf_dir/${prefix}-register.pdf"
  done
