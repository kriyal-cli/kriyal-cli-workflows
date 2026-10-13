#!/usr/bin/env python3
"""Emit the loom lanes of a cargo workspace as JSON: one entry per package, with the libtest filter of each loom model.

A loom model is a `*_loom_tests.rs` file. It is usually declared as `#[path = "x_loom_tests.rs"] mod loom_tests;`, so its tests are
named after the DECLARING module (`<host>::loom_tests::...`), not after the file; the filter is therefore `<host module>::<module>::`.
Stdlib only. Usage: loom_lanes.py <workspace-dir>   ->   [{"package", "dir", "filters": [...]}]
"""
import json
import os
import re
import sys
from pathlib import Path

SUFFIX = "_loom_tests.rs"
SKIP = {"target", ".git", "node_modules"}


def package_of(path):
    for parent in path.parents:
        manifest = parent / "Cargo.toml"
        if manifest.is_file():
            in_package = False
            for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped.startswith("["):
                    in_package = stripped == "[package]"
                elif in_package:
                    match = re.match(r'name\s*=\s*"([^"]+)"', stripped)
                    if match:
                        return match.group(1), parent
    return None


def fragment(path):
    stem = path.name[: -len(".rs")]
    attr = re.compile(
        r'#\[path\s*=\s*"' + re.escape(path.name) + r'"\]\s*(?:#\[[^\]]*\]\s*)*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;'
    )
    plain = re.compile(r"\bmod\s+" + re.escape(stem) + r"\s*;")
    for sibling in sorted(path.parent.glob("*.rs")):
        if sibling == path or sibling.name.endswith(SUFFIX):
            continue
        text = sibling.read_text(encoding="utf-8", errors="replace")
        match = attr.search(text)
        module = match.group(1) if match else (stem if plain.search(text) else None)
        if module is None:
            continue
        host = sibling.parent.name if sibling.stem == "mod" else ("" if sibling.stem in ("lib", "main") else sibling.stem)
        return f"{host}::{module}::" if host else f"{module}::"
    return stem


def main():
    root = Path(sys.argv[1]).resolve()
    lanes = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP and not d.startswith("target")]
        for name in filenames:
            if not name.endswith(SUFFIX):
                continue
            path = Path(dirpath) / name
            found = package_of(path)
            if found is None:
                continue
            package, package_dir = found
            entry = lanes.setdefault(package, {"package": package, "dir": str(package_dir.relative_to(root)) or ".", "filters": []})
            entry["filters"].append(fragment(path))
    for entry in lanes.values():
        entry["filters"] = sorted(set(entry["filters"]))
    print(json.dumps(sorted(lanes.values(), key=lambda e: e["package"]), separators=(",", ":")))


if __name__ == "__main__":
    main()
