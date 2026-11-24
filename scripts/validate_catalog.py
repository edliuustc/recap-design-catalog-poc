#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


POINTER_LIMIT = 4 * 1024
MANIFEST_LIMIT = 32 * 1024
DESIGN_LIMIT = 64 * 1024
RELEASE_LIMIT = 512 * 1024
MAX_DEPTH = 8
PROFILES = ("cowork-native", "bizchat-rich-text")
FORMS = (
    "decision",
    "comparison",
    "ideation",
    "sequence",
    "tasks",
    "status_table",
    "set",
    "findings",
    "metrics",
    "route",
    "qa",
    "open_questions",
    "points",
)
RELEASE_RE = re.compile(r"^v(?!000)[0-9]{3}$")
DESIGN_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
VERSION_RE = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TITLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,:;()&/+_-]{0,79}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GUID_RE = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-"
    r"[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}"
)
URL_RE = re.compile(r'\b[A-Za-z][A-Za-z0-9+.-]*://[^\s)>\"]+')
MARKDOWN_LINK_RE = re.compile(r"\]\(([^)\s]+)")
ALLOWED_README_URL = (
    "https:" + "//github.com/edliuustc/recap-design-catalog-poc"
)
TEXT_FORBIDDEN = (
    "gim" + "-home",
    "SOX" + "-Design-Workspace",
    "dev." + "azure.com",
    "visualstudio." + "com",
    "BEGIN " + "PRIVATE KEY",
    "ghp" + "_",
    "github_pat" + "_",
    "ado" + "_",
)
REQUIRED_PATHS = {
    "README.md",
    "SECURITY.md",
    ".github/CODEOWNERS",
    ".github/workflows/validate.yml",
    "scripts/validate_catalog.py",
    "tests/test_validate_catalog.py",
    "schemas/catalog-pointer.schema.json",
    "schemas/release.schema.json",
    "schemas/design.schema.json",
    "catalog/current.json",
    "examples/status-actions-request.json",
    "examples/status-actions-response.json",
}
SCHEMA_HASHES = {
    "catalog-pointer.schema.json": "1836ea2a68154fbb3cfa089575a855a53925362aed17c7cdbccff1257e0ce3bb",
    "release.schema.json": "c1ed4b99a5c2fbe6b6ae795af63815fbcf4fd948aacfa3a82cd0b7a3f1e7132b",
    "design.schema.json": "192a902358ff3818b087d0675c66961a418e6fc5a2d730aa21e0fe1ebd3af328",
}


class ValidationError(Exception):
    def __init__(self, message, category="validation"):
        super().__init__(message)
        self.category = category


def fail(message, category="validation"):
    raise ValidationError(message, category)


def require(condition, message, category="validation"):
    if not condition:
        fail(message, category)


def exact_keys(value, expected, label):
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == set(expected), f"{label} keys are not closed")


def reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            fail("duplicate JSON key", "json")
        value[key] = item
    return value


def reject_nonfinite(value):
    fail("non-finite JSON number", "json")


def json_depth(value):
    if isinstance(value, dict):
        return 1 if not value else 1 + max(json_depth(item) for item in value.values())
    if isinstance(value, list):
        return 1 if not value else 1 + max(json_depth(item) for item in value)
    return 0


def validate_json_numbers(value):
    if isinstance(value, float):
        require(math.isfinite(value), "non-finite JSON number", "json")
    elif isinstance(value, dict):
        for item in value.values():
            validate_json_numbers(item)
    elif isinstance(value, list):
        for item in value:
            validate_json_numbers(item)


def iter_json_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from iter_json_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_strings(item)


def validate_safe_string(value):
    require(isinstance(value, str), "value must be a string")
    for char in value:
        code = ord(char)
        require(
            code >= 32 and code not in range(0x7F, 0xA0),
            "string contains a control character",
            "scan",
        )
        require(
            not (0x202A <= code <= 0x202E or 0x2066 <= code <= 0x2069),
            "string contains a bidi character",
            "scan",
        )


def load_json(path, max_bytes, max_depth=MAX_DEPTH):
    path = Path(path)
    require(path.stat().st_size <= max_bytes, "JSON byte limit exceeded", "limit")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("JSON is not UTF-8", "json")
    try:
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except ValidationError:
        raise
    except (ValueError, json.JSONDecodeError, RecursionError):
        fail("malformed JSON", "json")
    validate_json_numbers(value)
    require(json_depth(value) <= max_depth, "JSON depth limit exceeded", "limit")
    for string in iter_json_strings(value):
        validate_safe_string(string)
        require("://" not in string, "forbidden URL-like JSON string", "scan")
        require(not EMAIL_RE.search(string), "forbidden email-like JSON string", "scan")
        require(not GUID_RE.search(string), "forbidden GUID-like JSON string", "scan")
    return value


def validate_release_id(value):
    require(isinstance(value, str) and RELEASE_RE.fullmatch(value), "invalid release id")


def validate_design_id(value):
    require(isinstance(value, str) and DESIGN_RE.fullmatch(value), "invalid design id")


def validate_design_path(design_id, value):
    require(isinstance(value, str), "design path must be a string")
    require("%" not in value and "\\" not in value, "invalid design path")
    require(not value.startswith("/") and ":" not in value, "invalid design path")
    parts = PurePosixPath(value).parts
    require("." not in parts and ".." not in parts, "invalid design path")
    require(value == f"designs/{design_id}/design.json", "invalid design path identity")


def validate_pointer_shape(pointer):
    exact_keys(pointer, ("schemaVersion", "current", "previous"), "pointer")
    require(
        pointer["schemaVersion"] == "recap-catalog-pointer/1.0",
        "unsupported pointer schema",
        "schema",
    )
    validate_release_id(pointer["current"])
    previous = pointer["previous"]
    require(previous is None or isinstance(previous, str), "invalid previous release")
    if previous is not None:
        validate_release_id(previous)
        require(previous != pointer["current"], "previous release must differ")


def validate_manifest_shape(manifest):
    exact_keys(manifest, ("schemaVersion", "id", "status", "designs"), "manifest")
    require(
        manifest["schemaVersion"] == "recap-design-release/1.0",
        "unsupported release schema",
        "schema",
    )
    validate_release_id(manifest["id"])
    require(manifest["status"] == "approved", "release is not approved")
    designs = manifest["designs"]
    require(isinstance(designs, list) and 1 <= len(designs) <= 30, "invalid design count")
    seen = set()
    for entry in designs:
        exact_keys(entry, ("id", "path", "sha256"), "manifest design")
        validate_design_id(entry["id"])
        require(entry["id"] not in seen, "duplicate design id")
        seen.add(entry["id"])
        validate_design_path(entry["id"], entry["path"])
        require(
            isinstance(entry["sha256"], str) and SHA_RE.fullmatch(entry["sha256"]),
            "invalid design hash",
        )


def validate_title(title):
    require(isinstance(title, dict), "title must be an object")
    kind = title.get("kind")
    if kind == "block-title":
        exact_keys(title, ("kind",), "block title")
        return
    require(kind == "literal", "invalid title kind")
    exact_keys(title, ("kind", "value"), "literal title")
    value = title["value"]
    require(isinstance(value, str) and TITLE_RE.fullmatch(value), "invalid literal title")
    lowered = value.lower()
    require("://" not in lowered, "literal title contains a URL")
    require(
        not lowered.startswith(("http:", "https:", "mailto:", "file:", "data:")),
        "literal title contains a URI scheme",
    )


def validate_design_shape(design):
    exact_keys(
        design,
        (
            "schemaVersion",
            "id",
            "version",
            "status",
            "priority",
            "appliesWhen",
            "profiles",
        ),
        "design",
    )
    require(
        design["schemaVersion"] == "recap-design/1.0",
        "unsupported design schema",
        "schema",
    )
    validate_design_id(design["id"])
    require(
        isinstance(design["version"], str) and VERSION_RE.fullmatch(design["version"]),
        "invalid design version",
    )
    require(design["status"] == "approved", "design is not approved")
    priority = design["priority"]
    require(type(priority) is int and 0 <= priority <= 1000, "invalid design priority")
    applies = design["appliesWhen"]
    exact_keys(
        applies,
        ("requiredForms", "minimumUnits", "maximumUnits"),
        "appliesWhen",
    )
    required_forms = applies["requiredForms"]
    require(
        isinstance(required_forms, list) and 1 <= len(required_forms) <= len(FORMS),
        "invalid required form count",
    )
    require(
        all(isinstance(form, str) for form in required_forms)
        and len(required_forms) == len(set(required_forms))
        and all(form in FORMS for form in required_forms),
        "invalid required forms",
    )
    minimum = applies["minimumUnits"]
    maximum = applies["maximumUnits"]
    require(
        type(minimum) is int
        and type(maximum) is int
        and 1 <= minimum <= maximum <= 30,
        "invalid unit range",
    )
    require(len(required_forms) <= minimum, "required forms exceed minimum units")
    profiles = design["profiles"]
    exact_keys(profiles, PROFILES, "profiles")
    for profile_name in PROFILES:
        profile = profiles[profile_name]
        exact_keys(profile, ("rules",), "profile")
        rules = profile["rules"]
        require(isinstance(rules, list) and 1 <= len(rules) <= 14, "invalid rule count")
        seen_forms = set()
        remaining_count = 0
        for index, rule in enumerate(rules):
            require(isinstance(rule, dict), "rule must be an object")
            if rule.get("kind") == "form":
                exact_keys(rule, ("kind", "form", "title"), "form rule")
                require(rule["form"] in FORMS, "invalid form rule")
                require(rule["form"] not in seen_forms, "duplicate form rule")
                seen_forms.add(rule["form"])
            elif rule.get("kind") == "remaining":
                exact_keys(rule, ("kind", "title"), "remaining rule")
                remaining_count += 1
                require(index == len(rules) - 1, "remaining rule must be final")
            else:
                fail("invalid rule kind")
            validate_title(rule["title"])
        require(remaining_count == 1, "profile must have one remaining rule")


def validate_request(request):
    exact_keys(
        request,
        ("schemaVersion", "requestNonce", "requestedProfiles", "units"),
        "request",
    )
    require(request["schemaVersion"] == "recap-design-request/1.0", "invalid request schema")
    require(
        isinstance(request["requestNonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", request["requestNonce"]),
        "invalid request nonce",
    )
    require(request["requestedProfiles"] == list(PROFILES), "invalid requested profiles")
    units = request["units"]
    require(isinstance(units, list) and 1 <= len(units) <= 30, "invalid unit count")
    for index, unit in enumerate(units, 1):
        exact_keys(unit, ("id", "form"), "request unit")
        require(unit["id"] == f"u{index}", "invalid unit id sequence")
        require(unit["form"] in FORMS, "invalid unit form")


def validate_response(response, request, expected_release):
    exact_keys(
        response,
        ("schemaVersion", "requestNonce", "status", "release", "design", "plans"),
        "response",
    )
    require(response["schemaVersion"] == "recap-design-response/1.0", "invalid response schema")
    require(response["requestNonce"] == request["requestNonce"], "nonce mismatch")
    require(response["status"] == "selected", "response is not selected")
    require(response["release"] == expected_release, "response release mismatch")
    validate_design_id(response["design"])
    exact_keys(response["plans"], PROFILES, "response plans")
    expected_unit_ids = [unit["id"] for unit in request["units"]]
    for profile_name in PROFILES:
        plan = response["plans"][profile_name]
        exact_keys(plan, ("sections",), "response plan")
        sections = plan["sections"]
        require(len(sections) == len(expected_unit_ids), "response section count mismatch")
        found = []
        for index, section in enumerate(sections, 1):
            exact_keys(section, ("id", "unitId", "title"), "response section")
            require(section["id"] == f"s{index}", "response section id mismatch")
            require(section["unitId"] in expected_unit_ids, "unknown response unit")
            found.append(section["unitId"])
            validate_title(section["title"])
        require(sorted(found) == sorted(expected_unit_ids), "response units are incomplete")


def validate_examples(request, response, expected_release, design):
    validate_request(request)
    validate_response(response, request, expected_release)
    require(response["design"] == design["id"], "example design identity mismatch")
    applies = design["appliesWhen"]
    require(
        applies["minimumUnits"] <= len(request["units"]) <= applies["maximumUnits"],
        "example request does not match design range",
    )
    request_forms = {unit["form"] for unit in request["units"]}
    require(
        all(form in request_forms for form in applies["requiredForms"]),
        "example request does not match required forms",
    )
    require(
        response["plans"] == generate_plans(design, request["units"]),
        "example plans do not match generated plans",
    )


def generate_plans(design, units):
    plans = {}
    for profile_name in PROFILES:
        unmatched = list(units)
        ordered = []
        for rule in design["profiles"][profile_name]["rules"]:
            if rule["kind"] == "form":
                selected = [unit for unit in unmatched if unit["form"] == rule["form"]]
            else:
                selected = list(unmatched)
            for unit in selected:
                ordered.append((unit, rule["title"]))
                unmatched.remove(unit)
        require(not unmatched and len(ordered) == len(units), "plan generation was incomplete")
        plans[profile_name] = {
            "sections": [
                {"id": f"s{index}", "unitId": unit["id"], "title": title}
                for index, (unit, title) in enumerate(ordered, 1)
            ]
        }
    return plans


def make_units(forms):
    return [{"id": f"u{index}", "form": form} for index, form in enumerate(forms, 1)]


def build_publication_probes(design):
    applies = design["appliesWhen"]
    required = list(applies["requiredForms"])
    minimum = applies["minimumUnits"]
    maximum = applies["maximumUnits"]
    probes = []

    def add(forms):
        units = make_units(forms)
        signature = tuple(unit["form"] for unit in units)
        if signature not in {tuple(unit["form"] for unit in probe) for probe in probes}:
            probes.append(units)

    add(required + [required[0]] * (minimum - len(required)))
    add(required + [required[0]] * (maximum - len(required)))
    if maximum > len(required):
        target = max(minimum, len(required) + 1)
        add(required + [required[0]] * (target - len(required)))
    for profile_name in PROFILES:
        explicit = {
            rule["form"]
            for rule in design["profiles"][profile_name]["rules"]
            if rule["kind"] == "form"
        }
        if any(form not in explicit for form in required):
            continue
        candidate = next(
            (form for form in FORMS if form not in required and form not in explicit),
            None,
        )
        if candidate is not None and maximum > len(required):
            target = max(minimum, len(required) + 1)
            add(required + [candidate] + [required[0]] * (target - len(required) - 1))
    return probes


def validate_publication_probes(design):
    for units in build_publication_probes(design):
        plans = generate_plans(design, units)
        expected = sorted(unit["id"] for unit in units)
        for profile_name in PROFILES:
            sections = plans[profile_name]["sections"]
            require(len(sections) == len(units), "publication probe section count mismatch")
            require(
                [section["id"] for section in sections]
                == [f"s{index}" for index in range(1, len(units) + 1)],
                "publication probe section ids are invalid",
            )
            require(
                sorted(section["unitId"] for section in sections) == expected,
                "publication probe units are incomplete",
            )


def is_allowed_path(relative):
    if relative in REQUIRED_PATHS:
        return True
    if re.fullmatch(r"examples/[^/]+\.json", relative):
        return True
    if re.fullmatch(r"schemas/[^/]+\.schema\.json", relative):
        return True
    if re.fullmatch(r"catalog/releases/v(?!000)[0-9]{3}/manifest\.json", relative):
        return True
    return bool(
        re.fullmatch(
            r"catalog/releases/v(?!000)[0-9]{3}/designs/"
            r"[a-z][a-z0-9-]{0,63}/design\.json",
            relative,
        )
    )


def is_allowed_directory(relative):
    if relative in {
        ".github",
        ".github/workflows",
        "catalog",
        "catalog/releases",
        "examples",
        "schemas",
        "scripts",
        "tests",
    }:
        return True
    return bool(
        re.fullmatch(r"catalog/releases/v(?!000)[0-9]{3}", relative)
        or re.fullmatch(r"catalog/releases/v(?!000)[0-9]{3}/designs", relative)
        or re.fullmatch(
            r"catalog/releases/v(?!000)[0-9]{3}/designs/"
            r"[a-z][a-z0-9-]{0,63}",
            relative,
        )
    )


def repository_files(root):
    root = Path(root)
    files = []
    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            fail("repository contains a symlink", "path")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            require(
                is_allowed_directory(relative),
                "repository directory is not allowed",
                "path",
            )
        if path.is_file():
            require(is_allowed_path(relative), "repository path is not allowed", "path")
            files.append((relative, path))
    require(REQUIRED_PATHS.issubset({relative for relative, _ in files}), "required path missing")
    return files


def scan_text_files(files):
    for relative, path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            fail("repository file is not UTF-8 text", "scan")
        lowered = text.lower()
        for term in TEXT_FORBIDDEN:
            require(term.lower() not in lowered, "forbidden repository text", "scan")
        require(not EMAIL_RE.search(text), "forbidden email-like repository text", "scan")
        require(not GUID_RE.search(text), "forbidden GUID-like repository text", "scan")
        urls = URL_RE.findall(text) + MARKDOWN_LINK_RE.findall(text)
        for url in urls:
            allowed = relative == "README.md" and url == ALLOWED_README_URL
            require(allowed, "forbidden repository URL", "scan")


def enforce_json_file_limits(files):
    for relative, path in files:
        limit = None
        if relative == "catalog/current.json":
            limit = POINTER_LIMIT
        elif re.fullmatch(r"catalog/releases/v(?!000)[0-9]{3}/manifest\.json", relative):
            limit = MANIFEST_LIMIT
        elif relative.endswith(".json"):
            limit = DESIGN_LIMIT
        if limit is not None:
            require(path.stat().st_size <= limit, "JSON byte limit exceeded", "limit")


def validate_schema_artifacts(root):
    for name, expected_hash in SCHEMA_HASHES.items():
        path = root / "schemas" / name
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash,
            "schema artifact differs from the approved grammar",
            "schema",
        )
    pointer = load_json(root / "schemas/catalog-pointer.schema.json", DESIGN_LIMIT)
    release = load_json(root / "schemas/release.schema.json", DESIGN_LIMIT)
    design = load_json(root / "schemas/design.schema.json", DESIGN_LIMIT)
    for schema in (pointer, release, design):
        require(
            isinstance(schema, dict)
            and schema.get("type") == "object"
            and schema.get("additionalProperties") is False
            and isinstance(schema.get("required"), list)
            and isinstance(schema.get("properties"), dict),
            "schema artifact is incomplete",
            "schema",
        )
    require(
        isinstance(release["properties"]["designs"]["items"]["properties"]["path"].get("pattern"), str),
        "schema artifact release path is incomplete",
        "schema",
    )
    require(
        isinstance(design.get("$defs"), dict)
        and design["properties"]["appliesWhen"].get("additionalProperties") is False
        and design["properties"]["profiles"].get("additionalProperties") is False,
        "schema artifact design grammar is incomplete",
        "schema",
    )


def git(root, *arguments, check=True):
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        fail("git immutable-release check timed out", "immutable")
    if check and completed.returncode:
        fail("git immutable-release check failed", "immutable")
    return completed


def validate_immutable_releases(root, base_ref):
    root = Path(root)
    parent = git(root, "rev-parse", "--verify", "HEAD^", check=False)
    if parent.returncode != 0:
        return
    require(base_ref and str(base_ref).strip(), "base ref is required", "immutable")
    base_ref = str(base_ref)
    if base_ref.startswith("origin/"):
        branch = base_ref[len("origin/") :]
        require(bool(branch) and not branch.startswith("-"), "invalid origin base ref", "immutable")
        git(root, "fetch", "--no-tags", "origin", branch)
    base = git(root, "merge-base", "HEAD", base_ref).stdout.strip()
    require(bool(base), "merge base is unavailable", "immutable")
    listing = git(root, "ls-tree", "-r", "--name-only", base, "--", "catalog/releases").stdout
    base_paths = [line for line in listing.splitlines() if line]
    worktree_files = {
        path.relative_to(root).as_posix(): path
        for path in (root / "catalog" / "releases").rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    for relative in base_paths:
        require(relative in worktree_files, "immutable release path was deleted or renamed", "immutable")
        comparison = git(
            root,
            "diff",
            "--no-ext-diff",
            "--quiet",
            base,
            "--",
            relative,
            check=False,
        )
        require(
            comparison.returncode == 0,
            "immutable release file changed",
            "immutable",
        )


def validate_repository(root, base_ref=None):
    root = Path(root).resolve()
    files = repository_files(root)
    enforce_json_file_limits(files)
    scan_text_files(files)
    validate_schema_artifacts(root)
    for relative, path in files:
        if relative.endswith(".json"):
            load_json(path, DESIGN_LIMIT)
    pointer = load_json(root / "catalog/current.json", POINTER_LIMIT)
    validate_pointer_shape(pointer)
    release_summaries = {}
    releases_root = root / "catalog/releases"
    release_directories = sorted(path for path in releases_root.iterdir() if path.is_dir())
    require(bool(release_directories), "catalog has no releases")
    for release_directory in release_directories:
        release_id = release_directory.name
        validate_release_id(release_id)
        manifest_path = release_directory / "manifest.json"
        manifest = load_json(manifest_path, MANIFEST_LIMIT)
        validate_manifest_shape(manifest)
        require(manifest["id"] == release_id, "release identity mismatch")
        total_bytes = manifest_path.stat().st_size
        designs = []
        expected_design_paths = {entry["path"] for entry in manifest["designs"]}
        actual_design_paths = {
            path.relative_to(release_directory).as_posix()
            for path in (release_directory / "designs").rglob("design.json")
            if path.is_file() and not path.is_symlink()
        }
        require(
            actual_design_paths == expected_design_paths,
            "orphan or missing design file",
        )
        for entry in manifest["designs"]:
            design_path = release_directory / entry["path"]
            require(
                design_path.is_file() and not design_path.is_symlink(),
                "design path missing",
            )
            total_bytes += design_path.stat().st_size
            require(total_bytes <= RELEASE_LIMIT, "release byte limit exceeded", "limit")
            digest = hashlib.sha256(design_path.read_bytes()).hexdigest()
            require(digest == entry["sha256"], "design hash mismatch")
            design = load_json(design_path, DESIGN_LIMIT)
            validate_design_shape(design)
            require(design["id"] == entry["id"], "design identity mismatch")
            validate_publication_probes(design)
            designs.append(design)
        require(
            len({design["id"] for design in designs}) == len(designs),
            "duplicate parsed design id",
        )
        release_summaries[release_id] = (len(designs), total_bytes)
    require(pointer["current"] in release_summaries, "current release is missing")
    request = load_json(root / "examples/status-actions-request.json", DESIGN_LIMIT)
    response = load_json(root / "examples/status-actions-response.json", DESIGN_LIMIT)
    current_manifest = load_json(
        root / "catalog/releases" / pointer["current"] / "manifest.json",
        MANIFEST_LIMIT,
    )
    current_designs = {
        entry["id"]: load_json(
            root / "catalog/releases" / pointer["current"] / entry["path"],
            DESIGN_LIMIT,
        )
        for entry in current_manifest["designs"]
    }
    require(isinstance(response, dict), "response must be an object")
    require(response.get("design") in current_designs, "example design is not in current release")
    validate_examples(
        request,
        response,
        expected_release=pointer["current"],
        design=current_designs[response["design"]],
    )
    if base_ref is not None:
        validate_immutable_releases(root, base_ref)
    design_count, total_bytes = release_summaries[pointer["current"]]
    return {
        "status": "ok",
        "release": pointer["current"],
        "designs": design_count,
        "releaseBytes": total_bytes,
        "files": len(files),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    arguments = parser.parse_args(argv)
    try:
        summary = validate_repository(Path(__file__).resolve().parents[1], arguments.base_ref)
    except (
        ValidationError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        print(
            json.dumps(
                {"status": "error", "error": "validation-failed"},
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
