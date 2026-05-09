#!/usr/bin/env bash
set -euo pipefail

release_api_url="https://api.github.com/repos/openai/codex/releases/latest"
raw_base_url="https://raw.githubusercontent.com/openai/codex"
schema_path="codex-rs/core/config.schema.json"
output_path="config.schema.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-api)
      release_api_url="${2:?missing value for --release-api}"
      shift 2
      ;;
    --raw-base)
      raw_base_url="${2:?missing value for --raw-base}"
      shift 2
      ;;
    --schema-path)
      schema_path="${2:?missing value for --schema-path}"
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

tag_name="$(
  curl --fail --silent --show-error --location "$release_api_url" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"])'
)"

schema_url="${raw_base_url%/}/${tag_name}/${schema_path#/}"
output_dir="$(dirname "$output_path")"
mkdir -p -- "$output_dir"
tmp_output="$(mktemp "${output_dir}/.$(basename "$output_path").tmp.XXXXXX")"
trap 'rm -f -- "$tmp_output"' EXIT

curl --fail --silent --show-error --location "$schema_url" >"$tmp_output"
python3 -m json.tool "$tmp_output" >/dev/null
chmod 0644 -- "$tmp_output"
mv -- "$tmp_output" "$output_path"
