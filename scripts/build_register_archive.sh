#!/usr/bin/env bash
set -euo pipefail

# Generate register artifacts for a single agenda packet PDF using the
# check_register_parser CLI. Artifacts are stored under data/artifacts by
# default.

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <agenda-packet.pdf> [archive-dir]" >&2
  exit 1
fi

packet_pdf="$1"
archive_dir="${2:-$(dirname "$0")/../data/artifacts}"

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
parser="$repo_root/check_register_parser.py"

pdf_dir="$archive_dir/pdfs"
csv_dir="$archive_dir/csv"
chunk_dir="$archive_dir/chunks"
mkdir -p "$pdf_dir" "$csv_dir" "$chunk_dir"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

(
  cd "$tmpdir"
  "$parser" "$packet_pdf" --pdf --csv --chunks-json
)

prefix=$(cd "$tmpdir" && ls *.csv)
prefix="${prefix%.csv}"

mv "$tmpdir/${prefix}-register.pdf" "$pdf_dir/"
mv "$tmpdir/${prefix}.csv" "$csv_dir/"
mv "$tmpdir/${prefix}-chunks.json" "$chunk_dir/"

echo "Archive updated: $pdf_dir/${prefix}-register.pdf"
