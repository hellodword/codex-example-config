#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


RELEASE_API_URL = "https://api.github.com/repos/openai/codex/releases/latest"
RAW_BASE_URL = "https://raw.githubusercontent.com/openai/codex"
SCHEMA_PATH = "codex-rs/core/config.schema.json"
OUTPUT_PATH = "config.schema.json"
FETCH_TIMEOUT_SECONDS = 30


class SchemaUpdateError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[update-schema.py] {message}", file=sys.stderr)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update config.schema.json from the latest OpenAI Codex release."
    )
    parser.add_argument("--release-api", default=RELEASE_API_URL, help="GitHub release API URL, file:// URL, or local JSON path")
    parser.add_argument("--raw-base", default=RAW_BASE_URL, help="Raw file base URL or local base path")
    parser.add_argument("--schema-path", default=SCHEMA_PATH, help="Schema path inside the release tag")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Output JSON path")
    return parser.parse_args(argv)


def read_bytes(source: str) -> bytes:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https", "file"):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "codex-example-config/update-schema.py"},
        )
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise SchemaUpdateError(f"failed to fetch {source}: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise SchemaUpdateError(f"failed to fetch {source}: {exc.reason}") from exc

    try:
        with open(source, "rb") as source_file:
            return source_file.read()
    except OSError as exc:
        raise SchemaUpdateError(f"failed to read {source}: {exc}") from exc


def load_json(source: str) -> object:
    body = read_bytes(source)
    try:
        return json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SchemaUpdateError(f"failed to decode JSON from {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaUpdateError(f"failed to parse JSON from {source}: {exc}") from exc


def latest_tag_name(release_api_url: str) -> str:
    release = load_json(release_api_url)
    if not isinstance(release, dict):
        raise SchemaUpdateError(f"release metadata is not a JSON object: {release_api_url}")

    tag_name = release.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        raise SchemaUpdateError(f"release metadata has no non-empty tag_name: {release_api_url}")
    return tag_name


def join_schema_source(raw_base_url: str, tag_name: str, schema_path: str) -> str:
    return f"{raw_base_url.rstrip('/')}/{tag_name}/{schema_path.lstrip('/')}"


def validate_schema_json(source: str, body: bytes) -> None:
    try:
        json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SchemaUpdateError(f"downloaded schema is not UTF-8: {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaUpdateError(f"downloaded schema is not valid JSON: {source}: {exc}") from exc


def write_output(path: str, body: bytes) -> None:
    output_dir = os.path.dirname(path) or "."
    os.makedirs(output_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.tmp.",
        dir=output_dir,
    )
    try:
        with os.fdopen(fd, "wb") as output_file:
            output_file.write(body)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        log(f"fetching release metadata: {args.release_api}")
        tag_name = latest_tag_name(args.release_api)
        log(f"latest release tag: {tag_name}")

        schema_source = join_schema_source(args.raw_base, tag_name, args.schema_path)
        log(f"fetching schema: {schema_source}")
        schema_body = read_bytes(schema_source)

        log("validating schema JSON")
        validate_schema_json(schema_source, schema_body)

        log(f"writing output: {args.output}")
        write_output(args.output, schema_body)
        log(f"updated {args.output} from {schema_source}")
        return 0
    except SchemaUpdateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(f"  release-api: {args.release_api}", file=sys.stderr)
        print(f"  raw-base: {args.raw_base}", file=sys.stderr)
        print(f"  schema-path: {args.schema_path}", file=sys.stderr)
        print(f"  output: {args.output}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: unexpected failure while updating schema: {exc}", file=sys.stderr)
        print(f"  release-api: {args.release_api}", file=sys.stderr)
        print(f"  raw-base: {args.raw_base}", file=sys.stderr)
        print(f"  schema-path: {args.schema_path}", file=sys.stderr)
        print(f"  output: {args.output}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
