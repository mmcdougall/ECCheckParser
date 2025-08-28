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
py_version="$(cat "$repo_root/.python-version")"

prepare_dirs() {
  pdf_dir="$archive_dir/pdfs"
  csv_dir="$archive_dir/csv"
  chunk_dir="$archive_dir/chunks"
  html_dir="$archive_dir/html"
  mkdir -p "$pdf_dir" "$csv_dir" "$chunk_dir" "$html_dir"
}

run_parser() {
  local packet_pdf="$1"
  local tmpdir="$2"
  (
    cd "$tmpdir"
    PYENV_VERSION="$py_version" "$parser" "$packet_pdf" --pdf --csv --chunks-json --html
  )
}

move_artifacts() {
  local tmpdir="$1"
  local prefix="$2"
  mv "$tmpdir/${prefix}-register.pdf" "$pdf_dir/"
  mv "$tmpdir/${prefix}.csv" "$csv_dir/"
  mv "$tmpdir/${prefix}-chunks.json" "$chunk_dir/"
  mv "$tmpdir/${prefix}-payees.html" "$html_dir/"
}

process_packet() {
  local packet_pdf="$1"
  local index="$2"
  local total="$3"

  printf '[%d/%d] %s\n' "$index" "$total" "$(basename "$packet_pdf")"
  local start=$(date +%s)
  local tmpdir
  tmpdir=$(mktemp -d)

  if run_parser "$packet_pdf" "$tmpdir"; then
    local prefix
    prefix=$(cd "$tmpdir" && ls *.csv)
    prefix="${prefix%.csv}"
    move_artifacts "$tmpdir" "$prefix"
    printf 'Archive updated: %s/%s-register.pdf\n' "$pdf_dir" "$prefix"
  else
    echo "No register found; skipping"
  fi

  rm -rf "$tmpdir"
  local elapsed=$(( $(date +%s) - start ))
  printf 'Elapsed: %ss\n' "$elapsed"
}

main() {
  prepare_dirs
  local packets=()
  while IFS= read -r -d '' packet; do
    packets+=("$packet")
  done < <(find "$originals_dir" -name '*.pdf' -print0)
  local total=${#packets[@]}
  local overall_start=$(date +%s)

  local idx=0
  for packet in "${packets[@]}"; do
    idx=$((idx + 1))
    process_packet "$packet" "$idx" "$total"
  done

  local overall_elapsed=$(( $(date +%s) - overall_start ))
  printf 'Processed %d packets in %ss\n' "$total" "$overall_elapsed"
}

main "$@"
