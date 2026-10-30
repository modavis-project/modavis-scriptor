#!/usr/bin/env python3
"""Generate checked TypeScript types and runtime guards from the real API OpenAPI.

Run with the graphics service's locked Python environment. --check fails on API
schema drift or missing response_model wiring, without changing generated files.
Import-time service data is isolated in a temporary directory; no server starts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "lib/graphics/contracts.generated.ts"
RESPONSES = {("/health", "get", "200"): "HealthResponse",
             ("/runs", "get", "200"): "RunListResponse",
             ("/runs/{run_id}", "get", "200"): "RunResponse",
             ("/runs", "post", "202"): "QueuedRunResponse",
             ("/runs/{run_id}/rerun", "post", "202"): "QueuedRunResponse",
             ("/runs/{run_id}/regions/{region_id}/review", "patch", "200"): "GraphicsResult"}
SEMANTICS = {"$ref", "type", "anyOf", "const", "enum", "properties", "required", "additionalProperties",
             "items", "prefixItems", "minItems", "maxItems", "minimum", "maximum", "exclusiveMinimum",
             "exclusiveMaximum", "minLength", "maxLength", "pattern"}
METADATA = {"title", "description", "default", "examples"}


def typename(value):
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def validate_schema(schema):
    if isinstance(schema, bool):
        return
    unknown = set(schema) - SEMANTICS - METADATA
    if unknown:
        raise ValueError(f"Unsupported schema keywords: {sorted(unknown)}; extend generator and validator together")
    for key in ("anyOf", "prefixItems"):
        for child in schema.get(key, []):
            validate_schema(child)
    for child in schema.get("properties", {}).values():
        validate_schema(child)
    for key in ("additionalProperties", "items"):
        if key in schema:
            validate_schema(schema[key])


def typescript(schema):
    if schema is True or schema == {}:
        return "unknown"
    if schema is False:
        return "never"
    if "$ref" in schema:
        return typename(schema["$ref"].split("/")[-1])
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(f"({typescript(v)})" for v in schema["anyOf"])
    kind = schema.get("type")
    if kind == "object":
        required = set(schema.get("required", []))
        fields = [f'{json.dumps(key)}{"" if key in required else "?"}: {typescript(child)};'
                  for key, child in schema.get("properties", {}).items()]
        extra = schema.get("additionalProperties", True)
        if extra is not False:
            fields.append(f'[key: string]: {typescript(extra)};')
        return "{ " + " ".join(fields) + " }"
    if kind == "array":
        if "prefixItems" in schema:
            return "[" + ", ".join(typescript(v) for v in schema["prefixItems"]) + "]"
        return f"Array<{typescript(schema.get('items', True))}>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}[kind]


def generate():
    with tempfile.TemporaryDirectory(prefix="scriptor-contracts-") as temporary:
        os.environ["GRAPHICS_DATA"] = temporary
        sys.path.insert(0, str(ROOT / "services/graphics"))
        from app import app
        from contracts import Config
        document = app.openapi()
        for (path, method, status), name in RESPONSES.items():
            actual = document["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
            if actual != {"$ref": f"#/components/schemas/{name}"}:
                raise ValueError(f"{method.upper()} {path}: expected response_model={name}, got {actual}")
        all_schemas = document["components"]["schemas"]
        roots = set(RESPONSES.values()) | {"ErrorResponse"}
        for path in ("/runs/{run_id}/rerun", "/runs/{run_id}/regions/{region_id}/review"):
            method = "post" if path.endswith("rerun") else "patch"
            roots.add(document["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1])
        def references(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    yield value["$ref"].split("/")[-1]
                for child in value.values():
                    yield from references(child)
            elif isinstance(value, list):
                for child in value:
                    yield from references(child)
        schemas = {}
        pending = list(roots)
        while pending:
            name = pending.pop()
            if name not in schemas:
                schemas[name] = all_schemas[name]
                pending.extend(references(schemas[name]))
        for schema in schemas.values():
            validate_schema(schema)
        names = [typename(name) for name in schemas]
        if len(set(names)) != len(names):
            raise ValueError("Schema names collide after TypeScript identifier conversion")
        content = json.dumps(schemas, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        lines = ["// Generated by scripts/contracts/generate.py from the actual FastAPI OpenAPI; do not edit.",
                 f"// Schema SHA-256: {hashlib.sha256(content.encode()).hexdigest()}",
                 'import { matchesSchema } from "./schema.js";',
                 f"const schemas = {json.dumps(schemas, sort_keys=True, ensure_ascii=False)};", ""]
        for name in sorted(schemas):
            identifier = typename(name)
            lines += [f"export type {identifier} = {typescript(schemas[name])};",
                      f"export function is{identifier}(value: unknown): value is {identifier} {{",
                      f"  return matchesSchema(value, schemas[{json.dumps(name)}], schemas);", "}", ""]
        lines += [f"export const defaultConfig: Config_Output = {json.dumps(Config().model_dump(mode='json'), ensure_ascii=False)};", ""]
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when generated types/validators are stale")
    args = parser.parse_args()
    content = generate()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != content:
            parser.exit(1, "API contract drift: run the generator and inspect the generated diff.\n")
        print("API response models and generated browser contracts match.")
    else:
        TARGET.write_text(content)
        print(f"Generated {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
