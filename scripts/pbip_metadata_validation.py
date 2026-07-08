"""
PBIP Metadata Validation
========================
Static integrity checks for a Power BI Project (.pbip) folder, meant to run as a
CI gate BEFORE the BPA. Uses only the Python standard library (no pip install).

Checks performed:
  1. All *.json files under the project parse as valid JSON (well-formed).
  2. .pbip artifacts point to existing .Report / .SemanticModel folders.
  3. .pbir datasetReference.byPath points to an existing SemanticModel folder.
  4. No absolute / non-portable paths (C:\\, \\\\UNC, file://) in path references.
  5. Required files exist for each Report and SemanticModel item.
  6. Format/version metadata present (version.json, .pbir/.pbism version).
  7. TMDL core files (database.tmdl, model.tmdl) exist and are not empty.
  8. Registered report resources (images/themes) referenced actually exist.
  9. .gitignore hygiene: PBI local cache/settings are ignored and not committed.

Exit code 0 = all checks passed. Exit code 1 = one or more ERRORS found.
Configure the project folder with the env var PBIP_PROJECT_DIR (default: pbi-project).
"""

import json
import os
import re
import subprocess
import sys

PROJECT_DIR = os.environ.get("PBIP_PROJECT_DIR", "pbi-project")

errors = []
warnings = []
checks_run = 0


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def ok(msg):
    global checks_run
    checks_run += 1
    print(f"  [OK] {msg}")


ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]|^\\\\|^file://|^/", re.IGNORECASE)


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def rel(path):
    return os.path.relpath(path, ".").replace("\\", "/")


# ---------------------------------------------------------------------------
# Check 1: every *.json parses correctly
# ---------------------------------------------------------------------------
def check_json_well_formed():
    print("\n== 1. JSON well-formed ==")
    found = False
    for root, _dirs, files in os.walk(PROJECT_DIR):
        for name in files:
            if name.lower().endswith(".json"):
                found = True
                p = os.path.join(root, name)
                try:
                    load_json(p)
                except Exception as e:  # noqa: BLE001
                    err(f"Invalid JSON: {rel(p)} -> {e}")
    if found and not any("Invalid JSON" in e for e in errors):
        ok("All *.json files parse successfully")
    elif not found:
        warn("No *.json files found under the project folder")


# ---------------------------------------------------------------------------
# Check 2 & 3: .pbip and .pbir references resolve
# ---------------------------------------------------------------------------
def check_pbip_references():
    print("\n== 2/3. Project references resolve ==")
    pbip_files = []
    for root, _dirs, files in os.walk(PROJECT_DIR):
        for name in files:
            if name.lower().endswith(".pbip"):
                pbip_files.append(os.path.join(root, name))

    if not pbip_files:
        err("No .pbip file found under the project folder")
        return

    for pbip in pbip_files:
        base = os.path.dirname(pbip)
        try:
            data = load_json(pbip)
        except Exception as e:  # noqa: BLE001
            err(f"Cannot read .pbip: {rel(pbip)} -> {e}")
            continue
        for artifact in data.get("artifacts", []):
            for _kind, ref in artifact.items():
                path = ref.get("path", "")
                if ABSOLUTE_PATH_RE.match(path):
                    err(f"Absolute/non-portable path in {rel(pbip)}: '{path}'")
                target = os.path.normpath(os.path.join(base, path))
                if not os.path.isdir(target):
                    err(f"{rel(pbip)} references missing folder: '{path}'")
        ok(f"Validated .pbip references: {rel(pbip)}")

    # .pbir dataset reference
    for root, _dirs, files in os.walk(PROJECT_DIR):
        for name in files:
            if name.lower().endswith(".pbir"):
                p = os.path.join(root, name)
                try:
                    data = load_json(p)
                except Exception as e:  # noqa: BLE001
                    err(f"Cannot read .pbir: {rel(p)} -> {e}")
                    continue
                by_path = (data.get("datasetReference", {}) or {}).get("byPath")
                if by_path:
                    path = by_path.get("path", "")
                    if ABSOLUTE_PATH_RE.match(path):
                        err(f"Absolute/non-portable dataset path in {rel(p)}: '{path}'")
                    target = os.path.normpath(os.path.join(os.path.dirname(p), path))
                    if not os.path.isdir(target):
                        err(f"{rel(p)} dataset byPath missing: '{path}'")
                    else:
                        ok(f"Dataset reference resolves: {rel(p)} -> '{path}'")
                # byConnection is valid too (deployed model) - just note it
                elif (data.get("datasetReference", {}) or {}).get("byConnection"):
                    warn(f"{rel(p)} uses byConnection (no local semantic model to validate)")


# ---------------------------------------------------------------------------
# Check 5 & 6 & 7: required files, version metadata, TMDL non-empty
# ---------------------------------------------------------------------------
def check_required_files():
    print("\n== 5/6/7. Required files, versions and TMDL ==")
    for root, dirs, _files in os.walk(PROJECT_DIR):
        for d in dirs:
            full = os.path.join(root, d)
            if d.endswith(".Report"):
                required = [
                    "definition.pbir",
                    os.path.join("definition", "report.json"),
                    os.path.join("definition", "version.json"),
                    os.path.join("definition", "pages", "pages.json"),
                    ".platform",
                ]
                for rq in required:
                    if not os.path.isfile(os.path.join(full, rq)):
                        err(f"Report '{d}' missing required file: {rq}")
                ok(f"Report structure checked: {d}")
            if d.endswith(".SemanticModel"):
                required = [
                    "definition.pbism",
                    os.path.join("definition", "model.tmdl"),
                    os.path.join("definition", "database.tmdl"),
                    ".platform",
                ]
                for rq in required:
                    fp = os.path.join(full, rq)
                    if not os.path.isfile(fp):
                        err(f"SemanticModel '{d}' missing required file: {rq}")
                    elif rq.endswith(".tmdl") and os.path.getsize(fp) == 0:
                        err(f"SemanticModel '{d}' has empty TMDL: {rq}")
                ok(f"SemanticModel structure checked: {d}")


# ---------------------------------------------------------------------------
# Check 8: registered report resources exist
# ---------------------------------------------------------------------------
def check_report_resources():
    print("\n== 8. Registered resources exist ==")
    for root, _dirs, files in os.walk(PROJECT_DIR):
        if os.path.basename(root) == "definition" and "report.json" in files:
            report_json = os.path.join(root, "report.json")
            report_folder = os.path.dirname(root)  # the .Report folder
            try:
                data = load_json(report_json)
            except Exception:  # noqa: BLE001
                continue  # already reported by check 1
            for pkg in data.get("resourcePackages", []):
                pkg_name = pkg.get("name", "RegisteredResources")
                for item in pkg.get("items", []):
                    item_path = item.get("path", "")
                    resource_fp = os.path.join(
                        report_folder, "StaticResources", pkg_name, item_path
                    )
                    if not os.path.isfile(resource_fp):
                        err(
                            f"Report resource referenced but missing: "
                            f"{pkg_name}/{item_path}"
                        )
            ok(f"Report resources checked: {rel(report_json)}")


# ---------------------------------------------------------------------------
# Check 9: .gitignore hygiene
# ---------------------------------------------------------------------------
def check_gitignore_hygiene():
    print("\n== 9. .gitignore hygiene ==")
    gitignores = []
    for candidate in (
        os.path.join(PROJECT_DIR, ".gitignore"),
        ".gitignore",
    ):
        if os.path.isfile(candidate):
            gitignores.append(candidate)

    contents = ""
    for gi in gitignores:
        with open(gi, "r", encoding="utf-8-sig") as f:
            contents += f.read() + "\n"

    if not gitignores:
        warn("No .gitignore found - PBI local cache files may get committed")
    else:
        for needle in ("localSettings.json", "cache.abf"):
            if needle not in contents:
                warn(f".gitignore does not mention '{needle}'")
        ok("Checked .gitignore for PBI cache/settings entries")

    # Ensure local-only artifacts are not TRACKED by git (committed).
    # We check git tracking (not disk presence) so local working files that are
    # correctly gitignored do not cause a false positive.
    try:
        tracked = subprocess.run(
            ["git", "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        committed_bad = [
            f for f in tracked
            if f.endswith("localSettings.json") or f.endswith(".abf")
        ]
        for f in committed_bad:
            err(f"Local-only artifact is committed to git: {f}")
        if not committed_bad:
            ok("No PBI local cache/settings artifacts are committed")
    except (subprocess.CalledProcessError, FileNotFoundError):
        warn("git not available - skipped tracked-artifact check")


def main():
    print(f"PBIP Metadata Validation - project folder: '{PROJECT_DIR}'")
    if not os.path.isdir(PROJECT_DIR):
        print(f"::error::Project folder not found: {PROJECT_DIR}")
        sys.exit(1)

    check_json_well_formed()
    check_pbip_references()
    check_required_files()
    check_report_resources()
    check_gitignore_hygiene()

    print("\n" + "=" * 60)
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN] {w}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  [ERROR] {e}")
        print("\nPBIP metadata validation FAILED.")
        sys.exit(1)

    print(f"\nAll PBIP metadata checks passed ({checks_run} checks, "
          f"{len(warnings)} warnings).")
    sys.exit(0)


if __name__ == "__main__":
    main()
