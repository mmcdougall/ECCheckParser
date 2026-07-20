#!/usr/bin/env bash
set -euo pipefail

# Generate register artifacts for canonical agenda packet PDFs under each
# originals year directory. Artifacts are stored under
# data/artifacts by default. Outputs include register PDFs, CSVs, chunk JSON,
# payee quadtree HTML, and extracted quarterly financial report PDFs.

if [[ $# -gt 2 ]]; then
  echo "Usage: $0 [originals-dir] [archive-dir]" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
originals_dir="${1:-$repo_root/data/originals}"
archive_dir="${2:-$repo_root/data/artifacts}"
parser="$repo_root/check_register_parser.py"
fund_update_parser="$repo_root/fund_update_parser.py"
python_bin="${PYTHON_BIN:-python}"

prepare_dirs() {
  pdf_dir="$archive_dir/pdfs"
  csv_dir="$archive_dir/csv"
  chunk_dir="$archive_dir/chunks"
  html_dir="$archive_dir/html"
  fund_update_dir="$archive_dir/fund_updates"
  cash_investment_dir="$archive_dir/cash_investments"
  mkdir -p \
    "$pdf_dir" "$csv_dir" "$chunk_dir" "$html_dir" \
    "$fund_update_dir" "$cash_investment_dir"
}

run_parser() {
  local packet_pdf="$1"
  local tmpdir="$2"
  (
    cd "$tmpdir"
    "$python_bin" "$parser" "$packet_pdf" --pdf --csv --chunks-json --html
  )
}

move_artifacts() {
  local tmpdir="$1"
  local found=0

  while IFS= read -r -d '' csv_path; do
    found=1
    local filename
    local prefix
    filename="$(basename "$csv_path")"
    prefix="${filename%.csv}"
    mv "$tmpdir/${prefix}-register.pdf" "$pdf_dir/"
    mv "$csv_path" "$csv_dir/"
    mv "$tmpdir/${prefix}-chunks.json" "$chunk_dir/"
    mv "$tmpdir/${prefix}-payees.html" "$html_dir/"
    printf 'Archive updated: %s/%s-register.pdf\n' "$pdf_dir" "$prefix"
  done < <(find "$tmpdir" -maxdepth 1 -type f -name '*.csv' -print0)

  if [[ "$found" -eq 0 ]]; then
    return 1
  fi
}

extract_quarterly_report() {
  local packet_pdf="$1"
  local tmpdir="$2"

  local output
  if output=$("$python_bin" "$fund_update_parser" "$packet_pdf" --artifact-dir "$tmpdir" 2>&1); then
    local -a report_pdfs=()
    while IFS= read -r -d '' file; do
      report_pdfs+=("$file")
    done < <(find "$tmpdir" -maxdepth 1 -type f -name '*.pdf' -print0)

    if [[ ${#report_pdfs[@]} -eq 0 ]]; then
      printf 'Quarterly report extraction succeeded but no PDF found for %s\n' "$(basename "$packet_pdf")" >&2
      return 1
    fi

    local source_path="${report_pdfs[0]}"
    local filename
    filename="$(basename "$source_path")"
    local destination_dir="$fund_update_dir"
    if [[ "$filename" == *-cash-investment-report.pdf ]]; then
      destination_dir="$cash_investment_dir"
    fi
    local destination="$destination_dir/$filename"
    mv "$source_path" "$destination"

    local pages=""
    if [[ "$output" =~ \(pages[[:space:]](.+)\) ]]; then
      pages="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$pages" ]]; then
      printf 'Quarterly report archived: %s (pages %s)\n' "$destination" "$pages"
    else
      printf 'Quarterly report archived: %s\n' "$destination"
    fi
  else
    local status=$?
    if [[ "$output" == *"No quarterly financial report pages found"* ]]; then
      printf 'Quarterly report not found; skipping %s\n' "$(basename "$packet_pdf")"
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
    move_artifacts "$tmpdir"
  else
    echo "No register found; skipping"
  fi

  extract_quarterly_report "$packet_pdf" "$tmpdir"

  rm -rf "$tmpdir"
  local elapsed=$(( $(date +%s) - start ))
  printf 'Elapsed: %ss\n' "$elapsed"
}

main() {
  prepare_dirs
  local packets=()
  while IFS= read -r -d '' packet; do
    packets+=("$packet")
  done < <(find "$originals_dir" -type f -path '*/agenda-packets/*.pdf' -print0)
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
