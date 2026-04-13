import copy
import json
import sys
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_URL = "https://developers.openai.com/codex/config-schema.json"


# -----------------------------
# Load schema
# -----------------------------
def load_schema(path_or_url: str) -> Dict[str, Any]:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        with urllib.request.urlopen(path_or_url) as resp:
            return json.load(resp)
    with open(path_or_url, "r", encoding="utf-8") as f:
        return json.load(f)


# -----------------------------
# Basic schema normalization
# -----------------------------
def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, dict)
        ):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def resolve_ref(root: Dict[str, Any], ref: str) -> Dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"Only local refs are supported, got: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return copy.deepcopy(node)


def normalize_schema(schema: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve:
    - $ref
    - allOf
    - oneOf / anyOf (pick a reasonable representative)
    """
    schema = copy.deepcopy(schema)

    # resolve $ref
    if "$ref" in schema:
        resolved = normalize_schema(resolve_ref(root, schema["$ref"]), root)
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        schema = deep_merge(resolved, rest)

    # merge allOf
    if "allOf" in schema:
        merged: Dict[str, Any] = {}
        for part in schema["allOf"]:
            merged = deep_merge(merged, normalize_schema(part, root))
        rest = {k: v for k, v in schema.items() if k != "allOf"}
        schema = deep_merge(merged, rest)

    # pick representative oneOf / anyOf branch
    for key in ("oneOf", "anyOf"):
        if key in schema:
            candidates = [normalize_schema(x, root) for x in schema[key]]

            # Prefer:
            # 1) branch with default
            # 2) enum/string branch
            # 3) first branch
            chosen = None
            for c in candidates:
                if "default" in c:
                    chosen = c
                    break
            if chosen is None:
                for c in candidates:
                    if "enum" in c:
                        chosen = c
                        break
            if chosen is None:
                chosen = candidates[0]

            rest = {k: v for k, v in schema.items() if k != key}
            schema = deep_merge(chosen, rest)

    # recurse
    if "properties" in schema and isinstance(schema["properties"], dict):
        schema["properties"] = {
            k: normalize_schema(v, root)
            for k, v in schema["properties"].items()
        }

    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = normalize_schema(schema["items"], root)

    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        schema["additionalProperties"] = normalize_schema(
            schema["additionalProperties"], root)

    return schema


# -----------------------------
# Schema helpers
# -----------------------------
def is_object_schema(schema: Dict[str, Any]) -> bool:
    return schema.get("type") == "object" or "properties" in schema or "additionalProperties" in schema


def is_array_of_objects(schema: Dict[str, Any]) -> bool:
    return schema.get("type") == "array" and isinstance(schema.get("items"), dict) and is_object_schema(schema["items"])


def is_dynamic_object_map(schema: Dict[str, Any]) -> bool:
    """
    object + additionalProperties, especially when there are no fixed properties
    """
    return schema.get("type") == "object" and isinstance(schema.get("additionalProperties"), dict)


def choose_example_name(path: List[str]) -> str:
    joined = ".".join(path)
    if joined == "mcp_servers":
        return "github"
    if joined == "model_providers":
        return "azure"
    if joined == "profiles":
        return "default"
    if joined == "apps":
        return "google_drive"
    if joined == "agents":
        return "reviewer"
    if joined == "projects":
        return "/absolute/path/to/project"
    if joined.endswith(".tools"):
        return "files/delete"
    return "example"


def optional_unset(schema: Dict[str, Any]) -> bool:
    return "default" not in schema and "examples" not in schema and "enum" not in schema


def pick_sample_value(schema: Dict[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    if "examples" in schema and schema["examples"]:
        return schema["examples"][0]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    t = schema.get("type")

    if t == "string":
        return "example"
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "array":
        items = schema.get("items", {})
        if is_object_schema(items):
            return [build_object_sample(items)]
        return [pick_sample_value(items)] if items else []
    if is_object_schema(schema):
        return build_object_sample(schema)

    return "TODO"


def build_object_sample(schema: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, subschema in schema.get("properties", {}).items():
        result[key] = pick_sample_value(subschema)
    return result


# -----------------------------
# TOML rendering
# -----------------------------
def toml_key(key: str) -> str:
    """
    Quote keys when needed, e.g. files/delete or absolute paths
    """
    simple = key.replace("_", "").replace("-", "").isalnum()
    if simple and "/" not in key and "." not in key and " " not in key:
        return key
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toml_literal(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        # inline table for simple dicts
        parts = []
        for k, v in value.items():
            if v is None:
                continue
            if isinstance(v, dict):
                # avoid nested inline-table explosion
                continue
            parts.append(f"{toml_key(k)} = {toml_literal(v)}")
        return "{ " + ", ".join(parts) + " }"
    raise TypeError(f"Unsupported TOML literal: {type(value)}")


def build_comments(schema: Dict[str, Any], required: bool) -> List[str]:
    comments: List[str] = []

    desc = schema.get("description")
    enum = schema.get("enum")
    default = schema.get("default")

    if desc:
        for line in str(desc).splitlines():
            comments.append(f"# {line}")

    if enum:
        comments.append("# Allowed: " + " | ".join(map(str, enum)))

    if "default" in schema:
        comments.append(f"# Default: {default!r}")
    elif required:
        comments.append("# Required")
    else:
        comments.append("# Optional; default: unset")

    return comments


def append_kv(
    lines: List[str],
    key: str,
    schema: Dict[str, Any],
    required: bool,
    comment_out: bool,
) -> None:
    comments = build_comments(schema, required)
    lines.extend(comments)

    value = pick_sample_value(schema)
    rendered = f"{toml_key(key)} = {toml_literal(value)}"
    if comment_out:
        lines.append("# " + rendered)
    else:
        lines.append(rendered)
    lines.append("")


def render_object_body(
    schema: Dict[str, Any],
    root: Dict[str, Any],
    lines: List[str],
    path: List[str],
) -> None:
    properties = schema.get("properties", {})
    required_set = set(schema.get("required", []))

    scalar_fields: List[Tuple[str, Dict[str, Any]]] = []
    table_fields: List[Tuple[str, Dict[str, Any]]] = []
    array_table_fields: List[Tuple[str, Dict[str, Any]]] = []
    dynamic_map_fields: List[Tuple[str, Dict[str, Any]]] = []

    for key, raw_subschema in properties.items():
        subschema = normalize_schema(raw_subschema, root)

        if is_array_of_objects(subschema):
            array_table_fields.append((key, subschema))
        elif is_dynamic_object_map(subschema):
            dynamic_map_fields.append((key, subschema))
        elif is_object_schema(subschema):
            table_fields.append((key, subschema))
        else:
            scalar_fields.append((key, subschema))

    # Root keys / scalar keys first
    for key, subschema in scalar_fields:
        required = key in required_set
        comment_out = (not required) and optional_unset(subschema)
        append_kv(lines, key, subschema, required, comment_out)

    # Regular tables
    for key, subschema in table_fields:
        required = key in required_set
        lines.extend(build_comments(subschema, required))
        table_name = ".".join([toml_key(p) for p in path + [key]])
        if not ((not required) and optional_unset(subschema)):
            lines.append(f"[{table_name}]")
            lines.append("")
            render_object_body(subschema, root, lines, path + [key])
        else:
            lines.append(f"# [{table_name}]")
            lines.append("")
            # emit commented children
            inner: List[str] = []
            render_object_body(subschema, root, inner, path + [key])
            for s in inner:
                lines.append("# " + s if s else "#")
            lines.append("")

    # Dynamic object maps -> emit empty parent + one example child table
    for key, subschema in dynamic_map_fields:
        required = key in required_set
        lines.extend(build_comments(subschema, required))

        parent_name = ".".join([toml_key(p) for p in path + [key]])
        lines.append(f"[{parent_name}]")
        lines.append("")

        child_name = choose_example_name(path + [key])
        child_schema = subschema.get(
            "additionalProperties", {"type": "object"})
        if is_object_schema(child_schema):
            lines.append(f"# Example entry")
            child_table = ".".join([toml_key(p)
                                   for p in path + [key, child_name]])
            lines.append(f"# [{child_table}]")
            example_lines: List[str] = []
            render_object_body(child_schema, root,
                               example_lines, path + [key, child_name])
            for s in example_lines:
                lines.append("# " + s if s else "#")
            lines.append("")

    # Arrays of objects -> emit one example array-of-table
    for key, subschema in array_table_fields:
        required = key in required_set
        lines.extend(build_comments(subschema, required))

        table_name = ".".join([toml_key(p) for p in path + [key]])
        item_schema = subschema["items"]
        lines.append(f"[[{table_name}]]")
        lines.append("")
        render_object_body(item_schema, root, lines, path + [key])
        lines.append("")


def render_schema_to_toml(schema: Dict[str, Any]) -> str:
    normalized = normalize_schema(schema, schema)

    if not is_object_schema(normalized):
        raise ValueError("Root schema must be an object-like schema.")

    lines: List[str] = []
    lines.append("# Generated from schema")
    lines.append("# Notes:")
    lines.append("# - Root keys are rendered before tables.")
    lines.append("# - Optional fields with unset defaults are commented out.")
    lines.append("# - Dynamic maps get an example child table.")
    lines.append("")

    render_object_body(normalized, normalized, lines, [])

    # clean up trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines) + "\n"


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else SCHEMA_URL
    out = sys.argv[2] if len(sys.argv) > 2 else "config.generated.toml"

    schema = load_schema(src)
    text = render_schema_to_toml(schema)

    with open(out, "w", encoding="utf-8") as f:
        f.write("#:schema https://developers.openai.com/codex/config-schema.json\n")
        f.write(text)

if __name__ == "__main__":
    main()
