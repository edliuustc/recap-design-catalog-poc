#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import zlib


POINTER_LIMIT = 4 * 1024
MANIFEST_LIMIT = 32 * 1024
DESIGN_LIMIT = 64 * 1024
IMAGE_LIMIT = 192 * 1024
RELEASE_LIMIT = 4 * 1024 * 1024
MAX_DEPTH = 8
EXAMPLE_LIMIT = 128 * 1024
EXAMPLE_MAX_DEPTH = 16
SCHEMA_LIMIT = 256 * 1024
SCHEMA_MAX_DEPTH = 32
REPOSITORY_FILE_LIMIT = 100
REPOSITORY_BYTE_LIMIT = 8 * 1024 * 1024
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
WEB_ADDRESS_RE = re.compile(
    r"(?:www\.|://|(?:https?|mailto|file|data|javascript|ssh):)",
    re.IGNORECASE,
)
CREDENTIAL_RE = re.compile(
    r"(?:\bbearer\s+[A-Za-z0-9._~+/\-=]{8,}"
    r"|\b(?:password|secret|token|api[_-]?key)\s*[:=])",
    re.IGNORECASE,
)
DRIVE_PREFIX_RE = re.compile(r"(?:^|[\s\"'(])[A-Za-z]:", re.IGNORECASE)
FILE_PATH_RE = re.compile(
    r"(?:[A-Za-z0-9._-]+/){1,}[A-Za-z0-9._-]+\.[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
BASE64_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/]{24,}|"
    r"[A-Za-z0-9+/]{22,}==|[A-Za-z0-9+/]{23,}=)(?![A-Za-z0-9+/=])"
)
PATH_PREFIXES = (
    "skills/", "src/", "source/", "tests/", "catalog/", "references/",
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
GUID_RE = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[1-5][0-9A-Fa-f]{3}-"
    r"[89ABab][0-9A-Fa-f]{3}-[0-9A-Fa-f]{12}"
)
URL_RE = re.compile(r'\b[A-Za-z][A-Za-z0-9+.-]*://[^\s)>\"]+')
MARKDOWN_INLINE_DESTINATION_RE = re.compile(
    r"\]\(\s*(?:<([^>\r\n]*)>|([^\s)>\r\n]*))"
)
MARKDOWN_REFERENCE_DESTINATION_RE = re.compile(
    r"(?m)^[ \t]{0,3}\[(?:\\.|[^\]\\\r\n])+\]:[ \t]*"
    r"(?:\r?\n[ \t]{1,3})?"
    r"(?:<([^>\r\n]*)>|([^\s\r\n]*))"
)
PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:(?:[A-Z0-9]+ )*)PRIVATE KEY-----"
)
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
    ".gitattributes",
    "README.md",
    "SECURITY.md",
    ".github/workflows/validate.yml",
    "scripts/validate_catalog.py",
    "tests/test_validate_catalog.py",
    "schemas/catalog-pointer.schema.json",
    "schemas/release.schema.json",
    "schemas/design.schema.json",
    "catalog/current.json",
    "examples/summit-readiness-request.json",
    "examples/summit-readiness-response.json",
}
SCHEMA_HASHES = {
    "catalog-pointer.schema.json": "5a0b13bc18d78ef2ff4cb90794a14396c624a6bfc8a6d3208afbd9aa990dda73",
    "release.schema.json": "57ad87d7531168289f48308e81d481583e4206b9737e0f834b9ccf4c7bd431c4",
    "design.schema.json": "e406099224557eabee68911a975c8d31df75ff77a7b1dda788873732705e5649",
}
LF_HASH_MIGRATION_MANIFEST_PATH = "catalog/releases/v001/manifest.json"
REVIEWED_BOOTSTRAP_COMMIT = "c4213d051263810bbdfa0793d2d8f2192258ed50"
PUBLISHED_RELEASE = "v003"
LF_HASH_MIGRATION_BASE_COMMIT = REVIEWED_BOOTSTRAP_COMMIT
LF_HASH_MIGRATION_DESIGN_PATH = (
    "catalog/releases/v001/designs/status-actions/design.json"
)
LF_HASH_MIGRATION_BASE_MANIFEST_SHA256 = (
    "fb015aa803d47779b691d55cdffe6664d5debeae91c04567b5e8513c3a8bc65d"
)
LF_HASH_MIGRATION_FIXED_MANIFEST_SHA256 = (
    "b7140b0aa561171509162c2dd60727fe0416e0baf5c3591f9fc9c53945508842"
)
LF_HASH_MIGRATION_DESIGN_SHA256 = (
    "78533a7c60f9d2d0d9508f7382989d9904bf4e6a9f9fd2a38bf5b70ab2e8ed48"
)


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
            code not in {0x202A, 0x202B, 0x202D, 0x202E}
            and not (0x2066 <= code <= 0x2069),
            "string contains a bidi character",
            "scan",
        )


def validate_json_tree(value, max_depth):
    root_depth = 1 if isinstance(value, (dict, list)) else 0
    stack = [(value, root_depth)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, dict):
            require(depth <= max_depth, "JSON depth limit exceeded", "limit")
            for key, child in item.items():
                validate_safe_string(key)
                child_depth = depth + 1 if isinstance(child, (dict, list)) else depth
                stack.append((child, child_depth))
        elif isinstance(item, list):
            require(depth <= max_depth, "JSON depth limit exceeded", "limit")
            for child in item:
                child_depth = depth + 1 if isinstance(child, (dict, list)) else depth
                stack.append((child, child_depth))
        elif isinstance(item, str):
            validate_safe_string(item)
            require("://" not in item, "forbidden URL-like JSON string", "scan")
            if "@" in item:
                require(not EMAIL_RE.search(item), "forbidden email-like JSON string", "scan")
            if "-" in item:
                require(not GUID_RE.search(item), "forbidden GUID-like JSON string", "scan")
        elif isinstance(item, float):
            require(math.isfinite(item), "non-finite JSON number", "json")


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
    validate_json_tree(value, max_depth)
    return value


def validate_release_id(value):
    require(isinstance(value, str) and RELEASE_RE.fullmatch(value), "invalid release id")


def validate_design_id(value):
    require(isinstance(value, str) and DESIGN_RE.fullmatch(value), "invalid design id")


def version_tuple(value):
    require(
        isinstance(value, str) and VERSION_RE.fullmatch(value),
        "invalid design version",
    )
    return tuple(int(part) for part in value.split("."))


def validate_design_path(design_id, value):
    require(isinstance(value, str), "design path must be a string")
    require("%" not in value and "\\" not in value, "invalid design path")
    require(not value.startswith("/") and ":" not in value, "invalid design path")
    parts = PurePosixPath(value).parts
    require("." not in parts and ".." not in parts, "invalid design path")
    require(value == f"designs/{design_id}/design.json", "invalid design path identity")


def validate_asset_path(asset_id, value):
    require(isinstance(value, str), "asset path must be a string")
    require("%" not in value and "\\" not in value, "invalid asset path")
    require(not value.startswith("/") and ":" not in value, "invalid asset path")
    parts = PurePosixPath(value).parts
    require("." not in parts and ".." not in parts, "invalid asset path")
    require(value == f"assets/{asset_id}.png", "invalid asset path identity")


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
    schema = manifest["schemaVersion"]
    require(
        schema in {"recap-design-release/1.0", "recap-design-release/1.1"},
        "unsupported release schema",
        "schema",
    )
    validate_release_id(manifest["id"])
    require(manifest["status"] == "approved", "release is not approved")
    designs = manifest["designs"]
    require(isinstance(designs, list) and 1 <= len(designs) <= 30, "invalid design count")
    seen = set()
    asset_paths = set()
    for entry in designs:
        expected = (
            ("id", "path", "sha256", "assets")
            if schema == "recap-design-release/1.1"
            else ("id", "path", "sha256")
        )
        exact_keys(entry, expected, "manifest design")
        validate_design_id(entry["id"])
        require(entry["id"] not in seen, "duplicate design id")
        seen.add(entry["id"])
        validate_design_path(entry["id"], entry["path"])
        require(
            isinstance(entry["sha256"], str) and SHA_RE.fullmatch(entry["sha256"]),
            "invalid design hash",
        )
        if schema == "recap-design-release/1.1":
            assets = entry["assets"]
            require(
                isinstance(assets, list) and len(assets) <= 1,
                "invalid manifest assets",
            )
            asset_ids = set()
            for asset in assets:
                exact_keys(
                    asset,
                    ("id", "path", "sha256", "mimeType", "byteLength", "width", "height"),
                    "manifest asset",
                )
                validate_design_id(asset["id"])
                require(asset["id"] not in asset_ids, "duplicate asset id")
                asset_ids.add(asset["id"])
                validate_asset_path(asset["id"], asset["path"])
                require(asset["path"] not in asset_paths, "duplicate asset path")
                asset_paths.add(asset["path"])
                require(
                    isinstance(asset["sha256"], str) and SHA_RE.fullmatch(asset["sha256"]),
                    "invalid asset hash",
                )
                require(asset["mimeType"] == "image/png", "invalid asset MIME type")
                require(
                    type(asset["byteLength"]) is int
                    and 1 <= asset["byteLength"] <= IMAGE_LIMIT,
                    "invalid asset byte length",
                )
                width, height = asset["width"], asset["height"]
                require(
                    type(width) is int
                    and type(height) is int
                    and 256 <= width <= 2048
                    and 256 <= height <= 2048
                    and width * height <= 3_145_728,
                    "invalid asset dimensions",
                )
    return schema


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


def validate_guidance(value, maximum_bytes, label):
    require(isinstance(value, str), f"{label} must be a string")
    trimmed = value.strip()
    lowered = trimmed.lower()
    require(bool(trimmed), f"{label} must not be blank")
    require(len(value.encode("utf-8")) <= maximum_bytes, f"{label} is too large")
    validate_safe_string(value)
    require("```" not in trimmed, f"{label} contains a code fence")
    require(not WEB_ADDRESS_RE.search(trimmed), f"{label} contains a web address")
    require(not CREDENTIAL_RE.search(trimmed), f"{label} contains a credential")
    require("\\" not in trimmed, f"{label} contains a path")
    require(not DRIVE_PREFIX_RE.search(trimmed), f"{label} contains a drive path")
    require(not FILE_PATH_RE.search(trimmed), f"{label} contains a file path")
    require(not BASE64_RE.search(trimmed), f"{label} contains base64-shaped content")
    require(
        not trimmed.startswith(("/", "./", "../")),
        f"{label} contains an absolute or relative path",
    )
    require(
        not any(prefix in lowered for prefix in PATH_PREFIXES),
        f"{label} contains a repository path",
    )
    return trimmed


def validate_design_shape(design):
    schema = design.get("schemaVersion")
    exact_keys(
        design,
        (
            "schemaVersion", "id", "version", "status", "priority",
            "appliesWhen", "profiles", "renderGuidance",
        )
        if schema == "recap-design/1.1"
        else (
            "schemaVersion", "id", "version", "status", "priority",
            "appliesWhen", "profiles",
        ),
        "design",
    )
    require(
        schema in {"recap-design/1.0", "recap-design/1.1"},
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
    reference_asset_id = None
    if schema == "recap-design/1.1":
        guidance = design["renderGuidance"]
        require(isinstance(guidance, dict), "renderGuidance must be an object")
        has_image = "referenceImage" in guidance
        exact_keys(
            guidance,
            ("description", "prompt", "referenceImage")
            if has_image
            else ("description", "prompt"),
            "renderGuidance",
        )
        validate_guidance(guidance["description"], 4000, "description")
        validate_guidance(guidance["prompt"], 4000, "prompt")
        if has_image:
            image = guidance["referenceImage"]
            exact_keys(image, ("assetId", "alt"), "referenceImage")
            validate_design_id(image["assetId"])
            validate_guidance(image["alt"], 240, "image alt")
            reference_asset_id = image["assetId"]
    return schema, reference_asset_id


def validate_request(request):
    has_response_schema = "responseSchemaVersion" in request
    exact_keys(
        request,
        (
            "schemaVersion", "responseSchemaVersion", "requestNonce",
            "requestedProfiles", "units",
        )
        if has_response_schema
        else ("schemaVersion", "requestNonce", "requestedProfiles", "units"),
        "request",
    )
    require(request["schemaVersion"] == "recap-design-request/1.0", "invalid request schema")
    if has_response_schema:
        require(
            request["responseSchemaVersion"] == "recap-design-response/1.1",
            "invalid requested response schema",
        )
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
    response_schema = request.get(
        "responseSchemaVersion",
        "recap-design-response/1.0",
    )
    exact_keys(
        response,
        (
            "schemaVersion", "requestNonce", "status", "release", "design",
            "plans", "renderGuidance",
        )
        if response_schema == "recap-design-response/1.1"
        else ("schemaVersion", "requestNonce", "status", "release", "design", "plans"),
        "response",
    )
    require(response["schemaVersion"] == response_schema, "invalid response schema")
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
        require(isinstance(sections, list), "response sections must be an array")
        require(len(sections) == len(expected_unit_ids), "response section count mismatch")
        found = []
        for index, section in enumerate(sections, 1):
            exact_keys(section, ("id", "unitId", "title"), "response section")
            require(section["id"] == f"s{index}", "response section id mismatch")
            require(section["unitId"] in expected_unit_ids, "unknown response unit")
            found.append(section["unitId"])
            validate_title(section["title"])
        require(sorted(found) == sorted(expected_unit_ids), "response units are incomplete")
    if response_schema == "recap-design-response/1.1":
        guidance = response["renderGuidance"]
        require(isinstance(guidance, dict), "response guidance must be an object")
        has_image = "referenceImage" in guidance
        exact_keys(
            guidance,
            ("description", "prompt", "referenceImage")
            if has_image
            else ("description", "prompt"),
            "response guidance",
        )
        validate_guidance(guidance["description"], 4000, "response description")
        validate_guidance(guidance["prompt"], 4000, "response prompt")
        if has_image:
            image = guidance["referenceImage"]
            exact_keys(
                image,
                ("id", "mimeType", "sha256", "alt", "width", "height"),
                "response image",
            )
            validate_design_id(image["id"])
            require(image["mimeType"] == "image/png", "invalid response image MIME")
            require(
                isinstance(image["sha256"], str)
                and SHA_RE.fullmatch(image["sha256"]),
                "invalid response image hash",
            )
            validate_guidance(image["alt"], 240, "response image alt")
            require(
                type(image["width"]) is int
                and type(image["height"]) is int
                and 256 <= image["width"] <= 2048
                and 256 <= image["height"] <= 2048
                and image["width"] * image["height"] <= 3_145_728,
                "invalid response image dimensions",
            )


def validate_examples(request, response, expected_release, design, manifest_entry):
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
    if design["schemaVersion"] == "recap-design/1.1":
        guidance = design["renderGuidance"]
        expected_guidance = {
            "description": guidance["description"],
            "prompt": guidance["prompt"],
        }
        if "referenceImage" in guidance:
            asset = manifest_entry["assets"][0]
            expected_guidance["referenceImage"] = {
                "id": asset["id"],
                "mimeType": asset["mimeType"],
                "sha256": asset["sha256"],
                "alt": guidance["referenceImage"]["alt"],
                "width": asset["width"],
                "height": asset["height"],
            }
        require(
            response["renderGuidance"] == expected_guidance,
            "example guidance does not match design and manifest",
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


def validate_png(path, asset):
    data = Path(path).read_bytes()
    require(len(data) == asset["byteLength"], "asset byte length mismatch")
    require(len(data) <= IMAGE_LIMIT, "asset exceeds image limit", "limit")
    require(hashlib.sha256(data).hexdigest() == asset["sha256"], "asset hash mismatch")
    require(data.startswith(b"\x89PNG\r\n\x1a\n"), "invalid PNG signature")
    offset = 8
    chunks = []
    idat = bytearray()
    state = "before"
    while offset < len(data):
        require(offset + 12 <= len(data), "truncated PNG chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        start = offset + 8
        end = start + length
        require(end + 4 <= len(data), "truncated PNG data")
        payload = data[start:end]
        expected_crc = struct.unpack(">I", data[end:end + 4])[0]
        require(
            zlib.crc32(kind + payload) & 0xFFFFFFFF == expected_crc,
            "PNG CRC mismatch",
        )
        if kind == b"IHDR":
            require(state == "before" and not chunks and length == 13, "invalid PNG IHDR")
        elif kind == b"IDAT":
            require(state in {"before-idat", "idat"} and length > 0, "invalid PNG IDAT sequence")
            state = "idat"
            idat.extend(payload)
        elif kind == b"IEND":
            require(state == "idat" and length == 0, "invalid PNG IEND")
            state = "done"
        else:
            fail("unsupported PNG chunk")
        chunks.append((kind, payload))
        if kind == b"IHDR":
            state = "before-idat"
        offset = end + 4
        if kind == b"IEND":
            break
    require(offset == len(data), "PNG trailing data")
    require(
        len(chunks) >= 3
        and chunks[0][0] == b"IHDR"
        and chunks[-1] == (b"IEND", b"")
        and state == "done",
        "invalid PNG chunk order",
    )
    ihdr = chunks[0][1]
    require(len(ihdr) == 13, "invalid PNG IHDR")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    require(
        width == asset["width"]
        and height == asset["height"]
        and depth == 8
        and color in {2, 6}
        and compression == 0
        and filtering == 0
        and interlace == 0,
        "unsupported PNG profile",
    )
    pixel_bytes = 3 if color == 2 else 4
    stride = width * pixel_bytes + 1
    try:
        expected_length = stride * height
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(bytes(idat), expected_length + 1)
    except zlib.error:
        fail("invalid PNG compression")
    require(
        decompressor.eof
        and not decompressor.unused_data
        and not decompressor.unconsumed_tail,
        "invalid PNG compressed stream",
    )
    require(len(raw) == expected_length, "invalid PNG scanline length")
    require(
        all(raw[index * stride] <= 4 for index in range(height)),
        "invalid PNG filter",
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
    if re.fullmatch(
        r"catalog/releases/v(?!000)[0-9]{3}/assets/"
        r"[a-z][a-z0-9-]{0,63}\.png",
        relative,
    ):
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
        or re.fullmatch(r"catalog/releases/v(?!000)[0-9]{3}/assets", relative)
        or re.fullmatch(
            r"catalog/releases/v(?!000)[0-9]{3}/designs/"
            r"[a-z][a-z0-9-]{0,63}",
            relative,
        )
    )


def repository_files(root):
    root = Path(root)
    files = []
    total_bytes = 0
    for current, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current)
        directory_names[:] = sorted(
            name for name in directory_names if name != ".git"
        )
        file_names.sort()
        for name in directory_names:
            path = current_path / name
            if path.is_symlink():
                fail("repository contains a symlink", "path")
            relative = path.relative_to(root).as_posix()
            require(
                is_allowed_directory(relative),
                "repository directory is not allowed",
                "path",
            )
        for name in file_names:
            path = current_path / name
            if path.is_symlink():
                fail("repository contains a symlink", "path")
            relative = path.relative_to(root).as_posix()
            require(is_allowed_path(relative), "repository path is not allowed", "path")
            files.append((relative, path))
            require(
                len(files) <= REPOSITORY_FILE_LIMIT,
                "repository file-count limit exceeded",
                "limit",
            )
            total_bytes += path.stat().st_size
            require(
                total_bytes <= REPOSITORY_BYTE_LIMIT,
                "repository byte limit exceeded",
                "limit",
            )
    require(REQUIRED_PATHS.issubset({relative for relative, _ in files}), "required path missing")
    return files


def scan_text_files(files):
    for relative, path in files:
        if path.suffix.lower() == ".png":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            fail("repository file is not UTF-8 text", "scan")
        lowered = text.lower()
        for term in TEXT_FORBIDDEN:
            require(term.lower() not in lowered, "forbidden repository text", "scan")
        require(
            not PEM_PRIVATE_KEY_RE.search(text),
            "forbidden private-key header",
            "scan",
        )
        if "@" in text:
            require(not EMAIL_RE.search(text), "forbidden email-like repository text", "scan")
        if "-" in text:
            require(not GUID_RE.search(text), "forbidden GUID-like repository text", "scan")
        urls = URL_RE.findall(text) if "://" in text else []
        for url in urls:
            allowed = relative == "README.md" and url == ALLOWED_README_URL
            require(allowed, "forbidden repository URL", "scan")
        destinations = []
        for pattern in (
            MARKDOWN_INLINE_DESTINATION_RE,
            MARKDOWN_REFERENCE_DESTINATION_RE,
        ):
            for match in pattern.finditer(text):
                destination = (
                    match.group(1)
                    if match.group(1) is not None
                    else match.group(2)
                )
                destinations.append((destination, match.group(1) is not None))
        for destination, angle_wrapped in destinations:
            allowed = (
                relative == "README.md"
                and not angle_wrapped
                and destination == ALLOWED_README_URL
            )
            require(allowed, "forbidden Markdown destination", "scan")


def enforce_repository_limits(files):
    require(
        len(files) <= REPOSITORY_FILE_LIMIT,
        "repository file-count limit exceeded",
        "limit",
    )
    total_bytes = sum(path.stat().st_size for _, path in files)
    require(
        total_bytes <= REPOSITORY_BYTE_LIMIT,
        "repository byte limit exceeded",
        "limit",
    )


def json_file_policy(relative):
    if relative == "catalog/current.json":
        return POINTER_LIMIT, MAX_DEPTH
    if re.fullmatch(r"catalog/releases/v(?!000)[0-9]{3}/manifest\.json", relative):
        return MANIFEST_LIMIT, MAX_DEPTH
    if re.fullmatch(
        r"catalog/releases/v(?!000)[0-9]{3}/designs/"
        r"[a-z][a-z0-9-]{0,63}/design\.json",
        relative,
    ):
        return DESIGN_LIMIT, MAX_DEPTH
    if relative.startswith("examples/"):
        return EXAMPLE_LIMIT, EXAMPLE_MAX_DEPTH
    if relative.startswith("schemas/"):
        return SCHEMA_LIMIT, SCHEMA_MAX_DEPTH
    return None


def enforce_json_file_limits(files):
    for relative, path in files:
        policy = json_file_policy(relative)
        if policy is not None:
            limit, _ = policy
            require(path.stat().st_size <= limit, "JSON byte limit exceeded", "limit")


def validate_schema_artifacts(root):
    for name, expected_hash in SCHEMA_HASHES.items():
        path = root / "schemas" / name
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash,
            "schema artifact differs from the approved grammar",
            "schema",
        )
    pointer = load_json(
        root / "schemas/catalog-pointer.schema.json",
        SCHEMA_LIMIT,
        SCHEMA_MAX_DEPTH,
    )
    release = load_json(
        root / "schemas/release.schema.json",
        SCHEMA_LIMIT,
        SCHEMA_MAX_DEPTH,
    )
    design = load_json(
        root / "schemas/design.schema.json",
        SCHEMA_LIMIT,
        SCHEMA_MAX_DEPTH,
    )
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


def git_bytes(root, *arguments):
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        fail("git immutable-release check timed out", "immutable")
    if completed.returncode:
        fail("git immutable-release check failed", "immutable")
    return completed.stdout


def is_exact_lf_hash_migration(root, base, relative):
    if (
        base != LF_HASH_MIGRATION_BASE_COMMIT
        or relative != LF_HASH_MIGRATION_MANIFEST_PATH
    ):
        return False
    base_manifest = git_bytes(root, "show", f"{base}:{relative}")
    fixed_manifest = git_bytes(root, "show", f":{relative}")
    if (root / relative).read_bytes() != fixed_manifest:
        return False
    if (
        hashlib.sha256(base_manifest).hexdigest()
        != LF_HASH_MIGRATION_BASE_MANIFEST_SHA256
        or hashlib.sha256(fixed_manifest).hexdigest()
        != LF_HASH_MIGRATION_FIXED_MANIFEST_SHA256
    ):
        return False
    design_path = root / LF_HASH_MIGRATION_DESIGN_PATH
    staged_design = git_bytes(root, "show", f":{LF_HASH_MIGRATION_DESIGN_PATH}")
    if (
        not design_path.is_file()
        or design_path.read_bytes() != staged_design
        or hashlib.sha256(staged_design).hexdigest()
        != LF_HASH_MIGRATION_DESIGN_SHA256
    ):
        return False
    base_design = git_bytes(
        root,
        "show",
        f"{base}:{LF_HASH_MIGRATION_DESIGN_PATH}",
    )
    return hashlib.sha256(base_design).hexdigest() == LF_HASH_MIGRATION_DESIGN_SHA256


def validate_immutable_releases(root, base_ref):
    root = Path(root)
    ancestry = git(
        root,
        "rev-list",
        "--parents",
        "-n",
        "1",
        "HEAD",
        check=False,
    )
    require(
        ancestry.returncode == 0,
        "git immutable-release ancestry check failed",
        "immutable",
    )
    ancestry_parts = ancestry.stdout.strip().split()
    require(bool(ancestry_parts), "git HEAD is unavailable", "immutable")
    if len(ancestry_parts) == 1:
        require(
            ancestry_parts[0] == REVIEWED_BOOTSTRAP_COMMIT,
            "unrecognized root commit cannot skip immutable comparison",
            "immutable",
        )
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
        if comparison.returncode == 0:
            continue
        require(
            comparison.returncode == 1,
            "git immutable-release comparison failed",
            "immutable",
        )
        require(
            is_exact_lf_hash_migration(root, base, relative),
            "immutable release file changed",
            "immutable",
        )


def validate_pointer_transition(root, pointer, base_ref):
    base = git(root, "merge-base", "HEAD", str(base_ref)).stdout.strip()
    require(bool(base), "pointer merge base is unavailable", "publication")
    try:
        base_pointer = json.loads(
            git_bytes(root, "show", f"{base}:catalog/current.json").decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        fail("base pointer is malformed", "publication")
    validate_pointer_shape(base_pointer)
    if pointer["current"] != base_pointer["current"]:
        require(
            pointer["previous"] == base_pointer["current"],
            "previous release must equal the base revision current release",
            "publication",
        )
    else:
        require(
            pointer == base_pointer,
            "pointer metadata must not change without publishing a new release",
            "publication",
        )


def _validate_repository(root, base_ref=None):
    root = Path(root).resolve()
    files = repository_files(root)
    enforce_repository_limits(files)
    enforce_json_file_limits(files)
    scan_text_files(files)
    validate_schema_artifacts(root)
    for relative, path in files:
        policy = json_file_policy(relative)
        if policy is not None:
            load_json(path, *policy)
    pointer = load_json(root / "catalog/current.json", POINTER_LIMIT)
    validate_pointer_shape(pointer)
    if root == Path(__file__).resolve().parents[1]:
        require(
            pointer["current"] == PUBLISHED_RELEASE,
            "catalog pointer publication requires a separately reviewed validator change",
            "publication",
        )
    release_summaries = {}
    prior_designs = {}
    releases_root = root / "catalog/releases"
    release_directories = sorted(path for path in releases_root.iterdir() if path.is_dir())
    require(bool(release_directories), "catalog has no releases")
    for release_directory in release_directories:
        release_id = release_directory.name
        validate_release_id(release_id)
        manifest_path = release_directory / "manifest.json"
        manifest = load_json(manifest_path, MANIFEST_LIMIT)
        manifest_schema = validate_manifest_shape(manifest)
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
        expected_asset_paths = {
            asset["path"]
            for entry in manifest["designs"]
            for asset in entry.get("assets", [])
        }
        assets_root = release_directory / "assets"
        actual_asset_paths = (
            {
                path.relative_to(release_directory).as_posix()
                for path in assets_root.rglob("*.png")
                if path.is_file() and not path.is_symlink()
            }
            if assets_root.exists()
            else set()
        )
        require(
            actual_asset_paths == expected_asset_paths,
            "orphan or missing asset file",
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
            design_schema, reference_asset_id = validate_design_shape(design)
            require(
                (manifest_schema, design_schema)
                in {
                    ("recap-design-release/1.0", "recap-design/1.0"),
                    ("recap-design-release/1.1", "recap-design/1.1"),
                },
                "release and design schema mismatch",
            )
            require(design["id"] == entry["id"], "design identity mismatch")
            prior = prior_designs.get(design["id"])
            if prior is not None and digest != prior["digest"]:
                require(
                    version_tuple(design["version"]) > version_tuple(prior["version"]),
                    "changed design must increment its version",
                    "version",
                )
            prior_designs[design["id"]] = {
                "digest": digest,
                "version": design["version"],
            }
            assets = entry.get("assets", [])
            require(
                (not assets and reference_asset_id is None)
                or (
                    len(assets) == 1
                    and reference_asset_id == assets[0]["id"]
                ),
                "design asset reference mismatch",
            )
            for asset in assets:
                asset_path = release_directory / asset["path"]
                require(
                    asset_path.is_file() and not asset_path.is_symlink(),
                    "asset path missing",
                )
                total_bytes += asset_path.stat().st_size
                require(
                    total_bytes <= RELEASE_LIMIT,
                    "release byte limit exceeded",
                    "limit",
                )
                validate_png(asset_path, asset)
            validate_publication_probes(design)
            designs.append(design)
        require(
            len({design["id"] for design in designs}) == len(designs),
            "duplicate parsed design id",
        )
        release_summaries[release_id] = (len(designs), total_bytes)
    require(pointer["current"] in release_summaries, "current release is missing")
    if pointer["previous"] is not None:
        require(
            pointer["previous"] in release_summaries,
            "previous release is missing",
        )
    if base_ref is not None:
        validate_pointer_transition(root, pointer, base_ref)
    request = load_json(
        root / "examples/summit-readiness-request.json",
        EXAMPLE_LIMIT,
        EXAMPLE_MAX_DEPTH,
    )
    response = load_json(
        root / "examples/summit-readiness-response.json",
        EXAMPLE_LIMIT,
        EXAMPLE_MAX_DEPTH,
    )
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
    current_entries = {
        entry["id"]: entry for entry in current_manifest["designs"]
    }
    require(isinstance(response, dict), "response must be an object")
    require(response.get("design") in current_designs, "example design is not in current release")
    validate_examples(
        request,
        response,
        expected_release=pointer["current"],
        design=current_designs[response["design"]],
        manifest_entry=current_entries[response["design"]],
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


def validate_repository(root, base_ref=None):
    try:
        return _validate_repository(root, base_ref)
    except ValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        fail("malformed repository data", "validation")


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
