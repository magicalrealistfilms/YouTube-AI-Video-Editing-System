# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18"]
# ///
"""Validate every JSON file in examples/ against its schema in schemas/.

Every example must be listed in SCHEMA_FOR or in NO_SCHEMA, so a newly added
example cannot silently go unchecked. Exits 1 on any failure.

    uv run tools/validate_examples.py
"""
import json, sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

# example file -> schema file
SCHEMA_FOR = {
    "take.json": "take.schema.json",
    "edit-plan.json": "edit-plan.schema.json",
    "cut-plan.json": "cut-plan.schema.json",
    "board-timeline.json": "board-timeline.schema.json",
    "design-starters-timeline.json": "board-timeline.schema.json",
}
# Examples that have no published schema yet (see docs/formats.md).
NO_SCHEMA = {"footage.json", "sync.json"}

def validate_examples(root=ROOT):
    """Return (checked, errors): checked is a list of (example, schema) names, errors a list of strings."""
    errors, checked = [], []
    names = {p.name for p in (root / "examples").glob("*.json")}
    for name in sorted(names - SCHEMA_FOR.keys() - NO_SCHEMA):
        errors.append(f"examples/{name}: no schema mapping; add it to SCHEMA_FOR or NO_SCHEMA in tools/validate_examples.py")
    for name in sorted((SCHEMA_FOR.keys() | NO_SCHEMA) - names):
        errors.append(f"examples/{name}: listed in tools/validate_examples.py but missing")
    for name, schema_name in sorted(SCHEMA_FOR.items()):
        if name not in names: continue
        try:
            data = json.loads((root / "examples" / name).read_text(encoding="utf-8"))
            schema = json.loads((root / "schemas" / schema_name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"examples/{name}: {e}"); continue
        Draft202012Validator.check_schema(schema)
        for err in Draft202012Validator(schema).iter_errors(data):
            where = "/".join(map(str, err.absolute_path)) or "(root)"
            errors.append(f"examples/{name} vs schemas/{schema_name} at {where}: {err.message}")
        checked.append((name, schema_name))
    return checked, errors

def main():
    checked, errors = validate_examples()
    for name, schema_name in checked: print(f"checked examples/{name} against schemas/{schema_name}")
    for name in sorted(NO_SCHEMA): print(f"skipped examples/{name} (no schema)")
    for e in errors: print(f"FAIL {e}", file=sys.stderr)
    print(f"{len(checked)} checked, {len(errors)} error(s)")
    return 1 if errors else 0

if __name__ == "__main__": sys.exit(main())
