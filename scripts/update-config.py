#!/usr/bin/env python3
import argparse
import html
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Optional


SOURCE_URL = "https://developers.openai.com/codex/config-sample"
OUTPUT_PATH = "config.toml"
SCHEMA_URL = "https://raw.githubusercontent.com/hellodword/codex-example-config/refs/heads/master/config.schema.json"
FETCH_TIMEOUT_SECONDS = 30


class ConfigUpdateError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[update-config.py] {message}", file=sys.stderr)


class CodeSampleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.astro_props: list[str] = []
        self.toml_code_blocks: list[str] = []
        self._collecting_code = False
        self._code_depth = 0
        self._code_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attrs_dict = dict(attrs)

        if self._collecting_code:
            self._code_depth += 1
            return

        if tag == "astro-island" and attrs_dict.get("component-export") == "CodeSample":
            props = attrs_dict.get("props")
            if props:
                self.astro_props.append(props)
            return

        if tag == "code" and attrs_dict.get("data-language") == "toml":
            self._collecting_code = True
            self._code_depth = 1
            self._code_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if not self._collecting_code:
            return

        self._code_depth -= 1
        if self._code_depth == 0:
            self._collecting_code = False
            text = "".join(self._code_chunks)
            if text.strip():
                self.toml_code_blocks.append(text)

    def handle_data(self, data: str) -> None:
        if self._collecting_code:
            self._code_chunks.append(data)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update config.toml from the OpenAI Codex config sample page."
    )
    parser.add_argument("--source", default=SOURCE_URL, help="HTML URL, file:// URL, or local HTML path")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Output TOML path")
    parser.add_argument("--schema-url", default=SCHEMA_URL, help="Schema URL written as the TOML header")
    return parser.parse_args(argv)


def read_source(source: str) -> str:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in ("http", "https", "file"):
        request = urllib.request.Request(
            source,
            headers={"User-Agent": "codex-example-config/update-config.py"},
        )
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return body.decode(charset)
        except urllib.error.HTTPError as exc:
            raise ConfigUpdateError(f"failed to fetch {source}: HTTP {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ConfigUpdateError(f"failed to fetch {source}: {exc.reason}") from exc
        except UnicodeDecodeError as exc:
            raise ConfigUpdateError(f"failed to decode response from {source}: {exc}") from exc

    try:
        with open(source, "r", encoding="utf-8") as source_file:
            return source_file.read()
    except OSError as exc:
        raise ConfigUpdateError(f"failed to read {source}: {exc}") from exc


def decode_astro_value(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        return decode_astro_value(value[1])
    if isinstance(value, list):
        return [decode_astro_value(item) for item in value]
    if isinstance(value, dict):
        return {key: decode_astro_value(item) for key, item in value.items()}
    return value


def score_toml_sample(code: str) -> int:
    score = len(code)
    markers = (
        "# Codex example configuration",
        "config.toml",
        "[features]",
        "[mcp_servers]",
        "[model_providers]",
    )
    for marker in markers:
        if marker in code:
            score += 100_000
    return score


def extract_from_astro_props(props_values: list[str]) -> Optional[str]:
    candidates: list[str] = []

    for raw_props in props_values:
        try:
            props = decode_astro_value(json.loads(raw_props))
        except json.JSONDecodeError:
            continue

        language = props.get("language") if isinstance(props, dict) else None
        code = props.get("code") if isinstance(props, dict) else None
        if language == "toml" and isinstance(code, str) and code.strip():
            candidates.append(code)

    if not candidates:
        return None

    return max(candidates, key=score_toml_sample)


def clean_fallback_code_block(code: str) -> str:
    lines = code.splitlines()
    first_content_line = 0
    while first_content_line < len(lines) and lines[first_content_line].strip().isdigit():
        first_content_line += 1
    return "\n".join(lines[first_content_line:]).strip() + "\n"


def extract_config_toml(source_html: str) -> str:
    parser = CodeSampleParser()
    parser.feed(source_html)
    parser.close()

    code = extract_from_astro_props(parser.astro_props)
    if code is not None:
        log("extracted TOML from Astro CodeSample data")
        return code.strip() + "\n"

    if parser.toml_code_blocks:
        log("extracted TOML from rendered code block")
        return clean_fallback_code_block(html.unescape(max(parser.toml_code_blocks, key=score_toml_sample)))

    raise ConfigUpdateError(
        "failed to find a TOML CodeSample or <code data-language=\"toml\"> block in the source HTML"
    )


def write_output(path: str, schema_url: str, config_toml: str) -> None:
    if not config_toml.strip():
        raise ConfigUpdateError("extracted TOML sample is empty")

    output_dir = os.path.dirname(path) or "."
    os.makedirs(output_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.tmp.",
        dir=output_dir,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output_file:
            output_file.write(f"#:schema {schema_url}\n")
            output_file.write(config_toml)
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
        log(f"reading source: {args.source}")
        source_html = read_source(args.source)
        config_toml = extract_config_toml(source_html)
        log(f"writing output: {args.output}")
        write_output(args.output, args.schema_url, config_toml)
        log(f"updated {args.output}")
        return 0
    except ConfigUpdateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(f"  source: {args.source}", file=sys.stderr)
        print(f"  output: {args.output}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: unexpected failure while updating config: {exc}", file=sys.stderr)
        print(f"  source: {args.source}", file=sys.stderr)
        print(f"  output: {args.output}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
