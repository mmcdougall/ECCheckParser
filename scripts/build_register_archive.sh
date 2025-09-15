#!/usr/bin/env bash
set -euo pipefail

# Generate register artifacts for all agenda packet PDFs under the originals
# directory using the check_register_parser CLI. Artifacts are stored under
# data/artifacts by default. Outputs include register PDFs, CSVs, chunk JSON,
# payee quadtree HTML, and extracted General Fund Budget Update PDFs.

if [[ $# -gt 2 ]]; then
  echo "Usage: $0 [originals-dir] [archive-dir]" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
originals_dir="${1:-$repo_root/data/originals}"
archive_dir="${2:-$repo_root/data/artifacts}"
parser="$repo_root/check_register_parser.py"
fund_update_parser="$repo_root/fund_update_parser.py"
py_version="$(cat "$repo_root/.python-version")"

prepare_dirs() {
  pdf_dir="$archive_dir/pdfs"
  csv_dir="$archive_dir/csv"
  chunk_dir="$archive_dir/chunks"
  html_dir="$archive_dir/html"
  fund_update_dir="$archive_dir/fund_updates"
  mkdir -p "$pdf_dir" "$csv_dir" "$chunk_dir" "$html_dir" "$fund_update_dir"
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

extract_fund_update() {
  local packet_pdf="$1"
  local tmpdir="$2"

  local output
  if output=$(PYENV_VERSION="$py_version" "$fund_update_parser" "$packet_pdf" --artifact-dir "$tmpdir" 2>&1); then
    local -a fund_pdfs=()
    while IFS= read -r -d '' file; do
      fund_pdfs+=("$file")
    done < <(find "$tmpdir" -maxdepth 1 -type f -name '*.pdf' -print0)

    if [[ ${#fund_pdfs[@]} -eq 0 ]]; then
      printf 'Fund update extraction succeeded but no PDF found for %s\n' "$(basename "$packet_pdf")" >&2
      return 1
    fi

    local source_path="${fund_pdfs[0]}"
    local filename="$(basename "$source_path")"
    local destination="$fund_update_dir/$filename"
    mv "$source_path" "$destination"

    local pages=""
    if [[ "$output" =~ \(pages[[:space:]](.+)\) ]]; then
      pages="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$pages" ]]; then
      printf 'Fund update archived: %s (pages %s)\n' "$destination" "$pages"
    else
      printf 'Fund update archived: %s\n' "$destination"
    fi
  else
    local status=$?
    if [[ "$output" == *"No General Fund Budget Update pages found"* ]]; then
      printf 'Fund update not found; skipping %s\n' "$(basename "$packet_pdf")"
      return 0
    fi
    printf '%s\n' "$output" >&2
    return "$status"
  fi
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

  extract_fund_update "$packet_pdf" "$tmpdir"

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
