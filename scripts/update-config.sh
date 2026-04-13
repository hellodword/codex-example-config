#!/usr/bin/env bash
set -euo pipefail

source_url="https://developers.openai.com/codex/config-sample"
output_path="config.toml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      source_url="${2:?missing value for --source}"
      shift 2
      ;;
    --output)
      output_path="${2:?missing value for --output}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

output_dir="$(dirname "$output_path")"
mkdir -p -- "$output_dir"
tmp_output="$(mktemp "${output_dir}/.$(basename "$output_path").tmp.XXXXXX")"
trap 'rm -f -- "$tmp_output"' EXIT

case "$source_url" in
  http://*|https://*|file://*) curl --fail --silent --show-error --location "$source_url" ;;
  *) cat -- "$source_url" ;;
esac | htmlq --text '#mainContent > .astro-code' >"$tmp_output"

grep -q '[^[:space:]]' "$tmp_output"
chmod 0644 -- "$tmp_output"
mv -- "$tmp_output" "$output_path"
