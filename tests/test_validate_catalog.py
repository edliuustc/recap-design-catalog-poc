import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import zlib


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_catalog.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_catalog", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("catalog validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def strict_png(width=256, height=256):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    scanline = b"\x00" + bytes((37, 99, 235)) * width
    raw = scanline * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def design_value(design_id="status-actions"):
    return {
        "schemaVersion": "recap-design/1.0",
        "id": design_id,
        "version": "1.0.0",
        "status": "approved",
        "priority": 100,
        "appliesWhen": {
            "requiredForms": ["status_table", "tasks"],
            "minimumUnits": 2,
            "maximumUnits": 30,
        },
        "profiles": {
            "cowork-native": {
                "rules": [
                    {
                        "kind": "form",
                        "form": "status_table",
                        "title": {"kind": "block-title"},
                    },
                    {
                        "kind": "form",
                        "form": "tasks",
                        "title": {"kind": "literal", "value": "Recorded actions"},
                    },
                    {"kind": "remaining", "title": {"kind": "block-title"}},
                ]
            },
            "bizchat-rich-text": {
                "rules": [
                    {
                        "kind": "form",
                        "form": "tasks",
                        "title": {"kind": "literal", "value": "Recorded actions"},
                    },
                    {
                        "kind": "form",
                        "form": "status_table",
                        "title": {"kind": "block-title"},
                    },
                    {"kind": "remaining", "title": {"kind": "block-title"}},
                ]
            },
        },
    }


def request_value():
    return {
        "schemaVersion": "recap-design-request/1.0",
        "requestNonce": "0123456789abcdef0123456789abcdef",
        "requestedProfiles": ["cowork-native", "bizchat-rich-text"],
        "units": [
            {"id": "u1", "form": "status_table"},
            {"id": "u2", "form": "tasks"},
        ],
    }


def response_value():
    return {
        "schemaVersion": "recap-design-response/1.0",
        "requestNonce": "0123456789abcdef0123456789abcdef",
        "status": "selected",
        "release": "v001",
        "design": "status-actions",
        "plans": {
            "cowork-native": {
                "sections": [
                    {
                        "id": "s1",
                        "unitId": "u1",
                        "title": {"kind": "block-title"},
                    },
                    {
                        "id": "s2",
                        "unitId": "u2",
                        "title": {"kind": "literal", "value": "Recorded actions"},
                    },
                ]
            },
            "bizchat-rich-text": {
                "sections": [
                    {
                        "id": "s1",
                        "unitId": "u2",
                        "title": {"kind": "literal", "value": "Recorded actions"},
                    },
                    {
                        "id": "s2",
                        "unitId": "u1",
                        "title": {"kind": "block-title"},
                    },
                ]
            },
        },
    }


def create_valid_tree(root):
    design_path = (
        root
        / "catalog"
        / "releases"
        / "v001"
        / "designs"
        / "status-actions"
        / "design.json"
    )
    write_json(design_path, design_value())
    digest = hashlib.sha256(design_path.read_bytes()).hexdigest()
    write_json(
        root / "catalog" / "current.json",
        {
            "schemaVersion": "recap-catalog-pointer/1.0",
            "current": "v001",
            "previous": None,
        },
    )
    write_json(
        root / "catalog" / "releases" / "v001" / "manifest.json",
        {
            "schemaVersion": "recap-design-release/1.0",
            "id": "v001",
            "status": "approved",
            "designs": [
                {
                    "id": "status-actions",
                    "path": "designs/status-actions/design.json",
                    "sha256": digest,
                }
            ],
        },
    )
    write_json(root / "examples" / "summit-readiness-request.json", request_value())
    write_json(root / "examples" / "summit-readiness-response.json", response_value())
    for name in (
        "catalog-pointer.schema.json",
        "release.schema.json",
        "design.schema.json",
        "component-release.schema.json",
        "component.schema.json",
    ):
        destination = root / "schemas" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "schemas" / name, destination)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".gitattributes").write_text(
        "* text=auto\n"
        "*.json text eol=lf\n"
        "*.py text eol=lf\n"
        "*.yml text eol=lf\n"
        "*.yaml text eol=lf\n"
        "*.md text eol=lf\n"
        "*.txt text eol=lf\n"
        "*.png binary\n"
        ".gitattributes text eol=lf\n",
        encoding="utf-8",
    )
    (root / "scripts" / "validate_catalog.py").write_text("# fixture\n", encoding="utf-8")
    (root / "tests" / "test_validate_catalog.py").write_text("# fixture\n", encoding="utf-8")
    (root / ".github" / "workflows" / "validate.yml").write_text(
        "name: validate\n", encoding="utf-8"
    )


class CatalogValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator()

    def assert_invalid(self, root, contains=None, base_ref=None):
        with self.assertRaises(self.validator.ValidationError) as context:
            self.validator.validate_repository(root, base_ref=base_ref)
        if contains:
            self.assertIn(contains, str(context.exception))

    def with_tree(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        create_valid_tree(root)
        return temporary, root

    def test_published_repository_uses_v003(self):
        summary = self.validator.validate_repository(ROOT)
        self.assertEqual("v003", summary["release"])
        self.assertEqual(1, summary["designs"])

    def test_valid_unpublished_v002_with_reference_image(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        release = root / "catalog" / "releases" / "v002"
        design_path = release / "designs" / "summit-readiness" / "design.json"
        asset_path = release / "assets" / "summit-readiness-layout.png"
        image = strict_png()
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(image)
        design = {
            "schemaVersion": "recap-design/1.1",
            "id": "summit-readiness",
            "version": "1.0.0",
            "status": "approved",
            "priority": 200,
            "appliesWhen": {
                "requiredForms": ["sequence", "tasks", "open_questions"],
                "minimumUnits": 3,
                "maximumUnits": 30,
            },
            "renderGuidance": {
                "description": "A blocked readiness flow followed by actions and open questions.",
                "prompt": "Make the prerequisite chain visually primary and preserve all grounded evidence.",
                "referenceImage": {
                    "assetId": "summit-readiness-layout",
                    "alt": "Reference layout for sequential readiness gates",
                },
            },
            "profiles": {
                "cowork-native": {
                    "rules": [
                        {"kind": "form", "form": "sequence", "title": {"kind": "block-title"}},
                        {"kind": "form", "form": "tasks", "title": {"kind": "literal", "value": "Recorded actions"}},
                        {"kind": "form", "form": "open_questions", "title": {"kind": "literal", "value": "Open questions"}},
                        {"kind": "remaining", "title": {"kind": "block-title"}},
                    ]
                },
                "bizchat-rich-text": {
                    "rules": [
                        {"kind": "form", "form": "sequence", "title": {"kind": "block-title"}},
                        {"kind": "form", "form": "tasks", "title": {"kind": "literal", "value": "Recorded actions"}},
                        {"kind": "form", "form": "open_questions", "title": {"kind": "literal", "value": "Open questions"}},
                        {"kind": "remaining", "title": {"kind": "block-title"}},
                    ]
                },
            },
        }
        write_json(design_path, design)
        write_json(
            release / "manifest.json",
            {
                "schemaVersion": "recap-design-release/1.1",
                "id": "v002",
                "status": "approved",
                "designs": [{
                    "id": "summit-readiness",
                    "path": "designs/summit-readiness/design.json",
                    "sha256": hashlib.sha256(design_path.read_bytes()).hexdigest(),
                    "assets": [{
                        "id": "summit-readiness-layout",
                        "path": "assets/summit-readiness-layout.png",
                        "sha256": hashlib.sha256(image).hexdigest(),
                        "mimeType": "image/png",
                        "byteLength": len(image),
                        "width": 256,
                        "height": 256,
                    }],
                }],
            },
        )
        summary = self.validator.validate_repository(root)
        self.assertEqual("v001", summary["release"])

    def write_component_release(self, root, components, image=None):
        release = root / "catalog" / "releases" / "v002"
        entries = []
        for component in components:
            path = release / "components" / component["id"] / "component.json"
            write_json(path, component)
            entry = {
                "id": component["id"],
                "path": f"components/{component['id']}/component.json",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "assets": [],
            }
            reference = component["renderGuidance"].get("referenceImage")
            if reference and image is not None:
                asset_path = release / "assets" / f"{reference['assetId']}.png"
                asset_path.parent.mkdir(parents=True, exist_ok=True)
                asset_path.write_bytes(image)
                entry["assets"].append({
                    "id": reference["assetId"],
                    "path": f"assets/{reference['assetId']}.png",
                    "sha256": hashlib.sha256(image).hexdigest(),
                    "mimeType": "image/png",
                    "byteLength": len(image),
                    "width": 256,
                    "height": 256,
                })
            entries.append(entry)
        manifest = {
            "schemaVersion": "recap-design-release/2.0",
            "id": "v002",
            "status": "approved",
            "components": entries,
        }
        write_json(release / "manifest.json", manifest)
        return release, manifest

    def component_value(self, component_id="tasks-card", form="tasks"):
        return {
            "schemaVersion": "recap-component/2.0",
            "id": component_id,
            "version": "1.0.0",
            "status": "approved",
            "form": form,
            "renderGuidance": {
                "description": "A compact action list.",
                "prompt": "Show each grounded action as one row.",
            },
        }

    def test_valid_unpublished_v20_component_release(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        tasks = self.component_value()
        tasks["renderGuidance"]["referenceImage"] = {
            "assetId": "tasks-card-layout",
            "alt": "Reference layout for an action list",
        }
        self.write_component_release(
            root,
            [tasks, self.component_value("decision-card", "decision")],
            image=strict_png(),
        )
        summary = self.validator.validate_repository(root)
        self.assertEqual("v001", summary["release"])

    def test_v20_component_release_rejects_invalid_components(self):
        cases = []
        duplicate_form = [
            self.component_value("tasks-a"),
            self.component_value("tasks-b"),
        ]
        cases.append((duplicate_form, "duplicate component form"))
        unknown_form = [self.component_value(form="timeline")]
        cases.append((unknown_form, "invalid component form"))
        template_fields = self.component_value()
        template_fields["priority"] = 100
        cases.append(([template_fields], "component keys are not closed"))
        missing_image = self.component_value()
        missing_image["renderGuidance"]["referenceImage"] = {
            "assetId": "tasks-card-layout",
            "alt": "Reference layout",
        }
        cases.append(([missing_image], "asset reference mismatch"))
        for components, message in cases:
            with self.subTest(message=message):
                temporary, root = self.with_tree()
                self.addCleanup(temporary.cleanup)
                self.write_component_release(root, components)
                self.assert_invalid(root, message)

    def test_v20_component_release_rejects_orphans_and_hash_drift(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        release, _ = self.write_component_release(root, [self.component_value()])
        write_json(
            release / "components" / "extra" / "component.json",
            self.component_value("extra", "decision"),
        )
        self.assert_invalid(root, "orphan or missing component file")
        shutil.rmtree(release / "components" / "extra")
        changed = self.component_value()
        changed["renderGuidance"]["prompt"] = "Changed after hashing."
        write_json(release / "components" / "tasks-card" / "component.json", changed)
        self.assert_invalid(root, "component hash mismatch")

    def test_v20_component_release_cannot_be_published_yet(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        self.write_component_release(root, [self.component_value()])
        write_json(
            root / "catalog" / "current.json",
            {
                "schemaVersion": "recap-catalog-pointer/1.0",
                "current": "v002",
                "previous": "v001",
            },
        )
        self.assert_invalid(root, "component release")

    def test_v11_guidance_rejects_path_base64_and_embedded_uri_forms(self):
        for value in (
            "folder/private/file.txt",
            "private/file.txt",
            "use=private/file.txt",
            "[private/file.txt]",
            "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
            "QWxhZGRpbjpvcGVuIHNlc2FtZQ",
            "QUJDREVGR0hJSktMTU5PUA==",
            "xhttp:payload",
            "prefixwww.example.test",
            "https:payload",
            "mailto:user",
            "file:payload",
            "data:payload",
            "javascript:alert(1)",
            "ssh:private-host",
        ):
            with self.subTest(value=value):
                with self.assertRaises(self.validator.ValidationError):
                    self.validator.validate_guidance(value, 4000, "prompt")

    def test_png_rejects_duplicate_ihdr_and_trailing_zlib_stream_data(self):
        base = strict_png()

        def metadata(data):
            return {
                "sha256": hashlib.sha256(data).hexdigest(),
                "byteLength": len(data),
                "width": 256,
                "height": 256,
            }

        duplicate_ihdr = base[:33] + base[8:33] + base[33:]
        idat_offset = 33
        idat_length = struct.unpack(">I", base[idat_offset:idat_offset + 4])[0]
        idat_type = base[idat_offset + 4:idat_offset + 8]
        idat_data = base[idat_offset + 8:idat_offset + 8 + idat_length] + b"extra"
        idat_chunk = (
            struct.pack(">I", len(idat_data))
            + idat_type
            + idat_data
            + struct.pack(">I", zlib.crc32(idat_type + idat_data) & 0xFFFFFFFF)
        )
        trailing_stream = (
            base[:idat_offset]
            + idat_chunk
            + base[idat_offset + 12 + idat_length:]
        )
        for name, data in (
            ("duplicate-ihdr", duplicate_ihdr),
            ("trailing-zlib", trailing_stream),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "image.png"
                path.write_bytes(data)
                with self.assertRaises(self.validator.ValidationError):
                    self.validator.validate_png(path, metadata(data))

    def test_png_rejects_bad_order_truncated_and_expanding_streams(self):
        base = strict_png()

        def chunks(data):
            values = []
            offset = 8
            while offset < len(data):
                length = struct.unpack(">I", data[offset:offset + 4])[0]
                kind = data[offset + 4:offset + 8]
                payload = data[offset + 8:offset + 8 + length]
                values.append((kind, payload))
                offset += 12 + length
            return values

        def build(values):
            output = bytearray(b"\x89PNG\r\n\x1a\n")
            for kind, payload in values:
                output += struct.pack(">I", len(payload))
                output += kind + payload
                output += struct.pack(
                    ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF
                )
            return bytes(output)

        values = chunks(base)
        ihdr, idat, iend = values
        raw = zlib.decompress(idat[1])
        cases = {
            "idat-before-ihdr": build((idat, ihdr, iend)),
            "iend-before-idat": build((ihdr, iend, idat)),
            "truncated-stream": build(
                (ihdr, (b"IDAT", idat[1][:-1]), iend)
            ),
            "expanded-stream": build(
                (ihdr, (b"IDAT", zlib.compress(raw + b"x", 9)), iend)
            ),
        }
        for name, data in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "image.png"
                path.write_bytes(data)
                asset = {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "byteLength": len(data),
                    "width": 256,
                    "height": 256,
                }
                with self.assertRaises(self.validator.ValidationError):
                    self.validator.validate_png(path, asset)

    def test_pointer_change_requires_separate_publication_change(self):
        pointer = json.loads(
            (ROOT / "catalog/current.json").read_text(encoding="utf-8")
        )
        self.assertEqual(self.validator.PUBLISHED_RELEASE, pointer["current"])
        with mock.patch.object(self.validator, "PUBLISHED_RELEASE", "v999"):
            with self.assertRaisesRegex(
                self.validator.ValidationError,
                "separately reviewed validator change",
            ):
                self.validator.validate_repository(ROOT)

    def test_pointer_transition_requires_base_current_as_previous(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "catalog"
        shutil.copytree(
            ROOT,
            root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.name", "Catalog Test")
        self._git(root, "config", "user.email", "catalog" + "@example.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "-m", "base")
        self._git(root, "commit", "--allow-empty", "-m", "tip")
        shutil.copytree(
            root / "catalog/releases/v003",
            root / "catalog/releases/v005",
        )
        manifest_path = root / "catalog/releases/v005/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "v005"
        write_json(manifest_path, manifest)
        pointer_path = root / "catalog/current.json"
        write_json(
            pointer_path,
            {
                "schemaVersion": "recap-catalog-pointer/1.0",
                "current": "v005",
                "previous": "v003",
            },
        )
        response_path = root / "examples/summit-readiness-response.json"
        response = json.loads(response_path.read_text(encoding="utf-8"))
        response["release"] = "v005"
        write_json(response_path, response)
        summary = self.validator.validate_repository(root, base_ref="HEAD")
        self.assertEqual("v005", summary["release"])
        invalid = json.loads(pointer_path.read_text(encoding="utf-8"))
        invalid["previous"] = "v001"
        write_json(pointer_path, invalid)
        with self.assertRaisesRegex(
            self.validator.ValidationError,
            "previous release must equal",
        ):
            self.validator.validate_repository(root, base_ref="HEAD")
        write_json(
            pointer_path,
            {
                "schemaVersion": "recap-catalog-pointer/1.0",
                "current": "v003",
                "previous": None,
            },
        )
        response["release"] = "v003"
        write_json(response_path, response)
        with self.assertRaisesRegex(
            self.validator.ValidationError,
            "pointer metadata must not change",
        ):
            self.validator.validate_repository(root, base_ref="HEAD")

    def test_v11_example_response_rejects_guidance_and_schema_mismatches(self):
        request = json.loads(
            (ROOT / "examples/summit-readiness-request.json").read_text(
                encoding="utf-8"
            )
        )
        response = json.loads(
            (ROOT / "examples/summit-readiness-response.json").read_text(
                encoding="utf-8"
            )
        )
        design = json.loads(
            (
                ROOT
                / "catalog/releases/v003/designs/summit-readiness/design.json"
            ).read_text(encoding="utf-8")
        )
        manifest_entry = json.loads(
            (
                ROOT / "catalog/releases/v003/manifest.json"
            ).read_text(encoding="utf-8")
        )["designs"][0]
        mutations = []
        missing_guidance = json.loads(json.dumps(response))
        del missing_guidance["renderGuidance"]
        mutations.append((request, missing_guidance))
        extra_guidance = json.loads(json.dumps(response))
        extra_guidance["renderGuidance"]["extra"] = True
        mutations.append((request, extra_guidance))
        malformed_image = json.loads(json.dumps(response))
        del malformed_image["renderGuidance"]["referenceImage"]["sha256"]
        mutations.append((request, malformed_image))
        changed_prompt = json.loads(json.dumps(response))
        changed_prompt["renderGuidance"]["prompt"] = "Use another safe layout."
        changed_hash = json.loads(json.dumps(response))
        changed_hash["renderGuidance"]["referenceImage"]["sha256"] = "f" * 64
        legacy_request = json.loads(json.dumps(request))
        del legacy_request["responseSchemaVersion"]
        mutations.append((legacy_request, response))
        for candidate_request, candidate_response in mutations:
            with self.subTest(response=candidate_response):
                with self.assertRaises(self.validator.ValidationError):
                    self.validator.validate_examples(
                        candidate_request,
                        candidate_response,
                        expected_release="v003",
                        design=design,
                        manifest_entry=manifest_entry,
                    )
        for candidate_response in (changed_prompt, changed_hash):
            with self.subTest(drift=candidate_response["renderGuidance"]):
                with self.assertRaisesRegex(
                    self.validator.ValidationError,
                    "example guidance does not match design and manifest",
                ):
                    self.validator.validate_examples(
                        request,
                        candidate_response,
                        expected_release="v003",
                        design=design,
                        manifest_entry=manifest_entry,
                    )

    def test_changed_design_requires_version_increment(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "catalog"
        shutil.copytree(
            ROOT,
            root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        design_path = (
            root
            / "catalog/releases/v003/designs/summit-readiness/design.json"
        )
        design = json.loads(design_path.read_text(encoding="utf-8"))
        design["version"] = "1.0.0"
        write_json(design_path, design)
        manifest_path = root / "catalog/releases/v003/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["designs"][0]["sha256"] = hashlib.sha256(
            design_path.read_bytes()
        ).hexdigest()
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(
            self.validator.ValidationError,
            "increment its version",
        ):
            self.validator.validate_repository(root)

    def test_schema_artifacts_encode_version_specific_fields(self):
        design_schema = json.loads(
            (ROOT / "schemas/design.schema.json").read_text(encoding="utf-8")
        )
        release_schema = json.loads(
            (ROOT / "schemas/release.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(2, len(design_schema["allOf"]))
        self.assertEqual(2, len(release_schema["allOf"]))
        self.assertEqual(
            ["renderGuidance"],
            design_schema["allOf"][1]["then"]["required"],
        )
        self.assertEqual(
            ["assets"],
            release_schema["allOf"][1]["then"]["properties"]["designs"][
                "items"
            ]["required"],
        )

    def test_lf_git_blob_hashes_are_catalog_authority(self):
        hashed_paths = (
            "catalog/releases/v001/designs/status-actions/design.json",
            "schemas/catalog-pointer.schema.json",
            "schemas/release.schema.json",
            "schemas/design.schema.json",
            "schemas/component-release.schema.json",
            "schemas/component.schema.json",
        )
        manifest_path = "catalog/releases/v001/manifest.json"
        validator_path = "scripts/validate_catalog.py"
        staged_bytes_by_path = {}
        for relative in hashed_paths + (manifest_path, validator_path):
            worktree_bytes = (ROOT / relative).read_bytes()
            index_bytes = subprocess.check_output(
                ["git", "show", f":{relative}"],
                cwd=ROOT,
            )
            self.assertNotIn(b"\r\n", worktree_bytes, relative)
            self.assertEqual(index_bytes, worktree_bytes, relative)
            staged_bytes_by_path[relative] = index_bytes

        manifest = json.loads(
            staged_bytes_by_path[manifest_path].decode("utf-8")
        )
        self.assertEqual(
            hashlib.sha256(
                staged_bytes_by_path[
                    "catalog/releases/v001/designs/status-actions/design.json"
                ]
            ).hexdigest(),
            manifest["designs"][0]["sha256"],
        )
        validator_tree = ast.parse(
            staged_bytes_by_path[validator_path].decode("utf-8")
        )
        schema_hashes = None
        for node in validator_tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "SCHEMA_HASHES"
            ):
                schema_hashes = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(schema_hashes)
        self.assertEqual(
            {
                "catalog-pointer.schema.json": hashlib.sha256(
                    staged_bytes_by_path["schemas/catalog-pointer.schema.json"]
                ).hexdigest(),
                "release.schema.json": hashlib.sha256(
                    staged_bytes_by_path["schemas/release.schema.json"]
                ).hexdigest(),
                "design.schema.json": hashlib.sha256(
                    staged_bytes_by_path["schemas/design.schema.json"]
                ).hexdigest(),
                "component-release.schema.json": hashlib.sha256(
                    staged_bytes_by_path["schemas/component-release.schema.json"]
                ).hexdigest(),
                "component.schema.json": hashlib.sha256(
                    staged_bytes_by_path["schemas/component.schema.json"]
                ).hexdigest(),
            },
            schema_hashes,
        )

    def test_gitattributes_forces_lf_for_hashed_text(self):
        self.assertIn(".gitattributes", self.validator.REQUIRED_PATHS)
        for relative in (
            "catalog/current.json",
            "catalog/releases/v001/manifest.json",
            "catalog/releases/v001/designs/status-actions/design.json",
            "schemas/design.schema.json",
            "scripts/validate_catalog.py",
            ".github/workflows/validate.yml",
        ):
            attribute = subprocess.check_output(
                ["git", "check-attr", "eol", "--", relative],
                cwd=ROOT,
                text=True,
            )
            self.assertIn("eol: lf", attribute, relative)

    def test_personal_repo_governance_has_no_codeowners(self):
        self.assertFalse((ROOT / ".github/CODEOWNERS").exists())
        self.assertNotIn(".github/CODEOWNERS", self.validator.REQUIRED_PATHS)
        self.assertFalse(self.validator.is_allowed_path(".github/CODEOWNERS"))

    def test_repository_has_no_documents(self):
        for relative in ("README.md", "SECURITY.md", "docs/notes.md"):
            self.assertFalse(self.validator.is_allowed_path(relative), relative)
        self.assertEqual([], sorted(p.name for p in ROOT.glob("*.md")))

    def test_closed_schemas(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        pointer_path = root / "catalog" / "current.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["extra"] = True
        write_json(pointer_path, pointer)
        self.assert_invalid(root, "pointer keys")

    def test_hashes(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        design_path = root / "catalog/releases/v001/designs/status-actions/design.json"
        design_path.write_text(design_path.read_text() + " ", encoding="utf-8")
        self.assert_invalid(root, "hash")

    def test_cross_file_identities(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        design_path = root / "catalog/releases/v001/designs/status-actions/design.json"
        design = json.loads(design_path.read_text(encoding="utf-8"))
        design["id"] = "other"
        write_json(design_path, design)
        manifest_path = root / "catalog/releases/v001/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["designs"][0]["sha256"] = hashlib.sha256(
            design_path.read_bytes()
        ).hexdigest()
        write_json(manifest_path, manifest)
        self.assert_invalid(root, "design identity")

    def test_forbidden_files_and_symlinks(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        (root / "notes.txt").write_text("not allowed\n", encoding="utf-8")
        self.assert_invalid(root, "path")
        (root / "notes.txt").unlink()
        if hasattr(os, "symlink"):
            try:
                os.symlink(root / "scripts" / "validate_catalog.py", root / "linked.md")
            except OSError:
                self.skipTest("symlink creation is unavailable")
            self.assert_invalid(root, "symlink")

    def test_private_data_scan(self):
        cases = [
            "https:" + "//private.invalid",
            "HTTPS:" + "//private.invalid",
            "ssh:" + "//private.invalid/repo",
            "person" + "@example.test",
            "12345678" + "-1234-4234-9234-123456789abc",
            "dev." + "azure.com",
            "BEGIN " + "PRIVATE KEY",
            "-----BEGIN " + "RSA PRIVATE KEY-----",
            "-----BEGIN " + "EC PRIVATE KEY-----",
            "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
            "ghp" + "_abcdefghijklmnopqrstuvwxyz",
        ]
        for value in cases:
            with self.subTest(value=value[:8]):
                temporary, root = self.with_tree()
                try:
                    (root / "scripts" / "validate_catalog.py").write_text(
                        value + "\n", encoding="utf-8"
                    )
                    self.assert_invalid(root, "forbidden")
                finally:
                    temporary.cleanup()

    def test_markdown_destination_bypasses_are_rejected(self):
        inline = "]" + "("
        definition = "]" + ":"
        forbidden_destinations = [
            "[label" + inline + "   <https:" + "//private.invalid/path>   )",
            "[label" + inline + "\tssh:" + "//private.invalid/repo)",
            "[label" + inline + " ./relative/path )",
            "[label][target]\n\n[target"
            + definition
            + "   <https:"
            + "//private.invalid/ref>",
            "[label][target]\n[target" + definition + "\t./relative/ref",
            "[label][target]\n[target"
            + definition
            + "\n  ./relative/next-line",
            "[label" + inline + ")",
            "[label" + inline + "<>)",
            "[label][target]\n[target" + definition + " <>",
            "[foo\\]" + definition + " ./private/escaped-label",
            "[catalog"
            + inline
            + "https:"
            + "//github.com/edliuustc/recap-design-catalog-poc)",
            "[catalog" + inline + "./catalog/current.json)",
        ]
        for text in forbidden_destinations:
            with self.subTest(text=text[:16]):
                temporary, root = self.with_tree()
                try:
                    (root / "scripts" / "validate_catalog.py").write_text(
                        text + "\n", encoding="utf-8"
                    )
                    self.assert_invalid(root, "forbidden")
                finally:
                    temporary.cleanup()

    def test_forbidden_empty_directory_and_orphan_design(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        (root / "unapproved").mkdir()
        self.assert_invalid(root, "directory")
        (root / "unapproved").rmdir()
        orphan = root / "catalog/releases/v001/designs/orphan/design.json"
        write_json(orphan, design_value("orphan"))
        self.assert_invalid(root, "orphan")

    def test_release_immutability(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.name", "Catalog Test")
        self._git(root, "config", "user.email", "catalog" + "@example.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "-m", "base")
        base = self._git(root, "rev-parse", "HEAD").strip()
        workflow = root / ".github" / "workflows" / "validate.yml"
        workflow.write_text("name: validate\n# updated\n", encoding="utf-8")
        self._git(root, "add", ".github/workflows/validate.yml")
        self._git(root, "commit", "-m", "tooling")
        self.validator.validate_repository(root, base_ref=base)
        design_path = root / "catalog/releases/v001/designs/status-actions/design.json"
        design_path.write_text(design_path.read_text() + " ", encoding="utf-8")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_immutable_releases(root, base)

    def test_exact_lf_manifest_migration_from_bootstrap_base_is_allowed(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "clone"
        self._git(
            root.parent,
            "clone",
            "--no-hardlinks",
            str(ROOT),
            str(root),
        )
        base = "c4213d051263810bbdfa0793d2d8f2192258ed50"
        self.validator.validate_immutable_releases(root, base)

        manifest_path = root / "catalog/releases/v001/manifest.json"
        corrected_manifest = manifest_path.read_bytes()
        manifest_path.write_bytes(corrected_manifest + b" ")
        self._git(root, "add", "catalog/releases/v001/manifest.json")
        manifest_path.write_bytes(corrected_manifest)
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_immutable_releases(root, base)

        self._git(root, "add", "catalog/releases/v001/manifest.json")
        manifest_path.write_bytes(corrected_manifest + b" ")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_immutable_releases(root, base)

    def test_recreated_legacy_content_on_different_history_is_rejected(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        release = root / "catalog/releases/v001"
        design_source = (
            ROOT
            / "catalog/releases/v001/designs/status-actions/design.json"
        ).read_bytes()
        corrected_manifest = (
            ROOT / "catalog/releases/v001/manifest.json"
        ).read_bytes()
        legacy_manifest = corrected_manifest.replace(
            b"78533a7c60f9d2d0d9508f7382989d9904bf4e6a9f9fd2a38bf5b70ab2e8ed48",
            b"9f4081261f7b102308d7eada1b5c199c9b116dc80c3f0acee87b9a2a8ae17db4",
        )
        design_path = release / "designs/status-actions/design.json"
        design_path.parent.mkdir(parents=True)
        design_path.write_bytes(design_source)
        (release / "manifest.json").write_bytes(legacy_manifest)
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.name", "Catalog Test")
        self._git(root, "config", "user.email", "catalog" + "@example.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "-m", "legacy")
        base = self._git(root, "rev-parse", "HEAD").strip()
        (root / "second.txt").write_text("second commit\n", encoding="utf-8")
        self._git(root, "add", "second.txt")
        self._git(root, "commit", "-m", "branch")

        manifest_path = release / "manifest.json"
        manifest_path.write_bytes(corrected_manifest)
        self._git(root, "add", "catalog/releases/v001/manifest.json")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_immutable_releases(root, base)

    def test_immutable_git_failures_fail_closed(self):
        failed = subprocess.CompletedProcess(
            args=["git"],
            returncode=2,
            stdout="",
            stderr="git failure",
        )
        with mock.patch.object(self.validator, "git", return_value=failed):
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_immutable_releases(ROOT, "main")

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        manifest_path = root / "catalog/releases/v001/manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("{}\n", encoding="utf-8")
        git_results = [
            subprocess.CompletedProcess(["git"], 0, "head parent\n", ""),
            subprocess.CompletedProcess(["git"], 0, "base\n", ""),
            subprocess.CompletedProcess(
                ["git"],
                0,
                "catalog/releases/v001/manifest.json\n",
                "",
            ),
            failed,
        ]
        with mock.patch.object(self.validator, "git", side_effect=git_results):
            with mock.patch.object(
                self.validator,
                "is_exact_lf_hash_migration",
                return_value=True,
            ):
                with self.assertRaises(self.validator.ValidationError):
                    self.validator.validate_immutable_releases(root, "main")

    def test_examples_match_catalog_contract(self):
        manifest_entry = {
            "id": "status-actions",
            "path": "designs/status-actions/design.json",
            "sha256": "0" * 64,
        }
        self.validator.validate_examples(
            request_value(),
            response_value(),
            expected_release="v001",
            design=design_value(),
            manifest_entry=manifest_entry,
        )
        broken = response_value()
        broken["plans"]["cowork-native"]["sections"][0]["id"] = "s2"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                broken,
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        wrong_design = response_value()
        wrong_design["design"] = "other"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                wrong_design,
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        wrong_plan = response_value()
        wrong_plan["plans"]["cowork-native"]["sections"].reverse()
        wrong_plan["plans"]["cowork-native"]["sections"][0]["id"] = "s1"
        wrong_plan["plans"]["cowork-native"]["sections"][1]["id"] = "s2"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                wrong_plan,
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        wrong_nonce = response_value()
        wrong_nonce["requestNonce"] = "f" * 32
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                wrong_nonce,
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        wrong_profiles = request_value()
        wrong_profiles["requestedProfiles"] = ["cowork-native"]
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                wrong_profiles,
                response_value(),
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        missing_profile = response_value()
        del missing_profile["plans"]["bizchat-rich-text"]
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                missing_profile,
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        duplicate_unit = response_value()
        duplicate_unit["plans"]["cowork-native"]["sections"][1]["unitId"] = "u1"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                duplicate_unit,
                expected_release="v001",
                design=design_value(),
                manifest_entry=manifest_entry,
            )
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        write_json(root / "examples/summit-readiness-response.json", [])
        self.assert_invalid(root, "response")
        create_valid_tree(root)
        response_path = root / "examples/summit-readiness-response.json"
        malformed = response_value()
        malformed["plans"]["cowork-native"]["sections"] = {}
        write_json(response_path, malformed)
        self.assert_invalid(root, "sections")

    def test_cli(self):
        completed = subprocess.run(
            ["python", str(VALIDATOR_PATH)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual("ok", summary["status"])
        self.assertEqual("", completed.stderr)

    def test_duplicate_keys_and_nonfinite_values_are_rejected(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        pointer = root / "catalog/current.json"
        pointer.write_text(
            '{"schemaVersion":"recap-catalog-pointer/1.0",'
            '"current":"v001","current":"v002","previous":null}',
            encoding="utf-8",
        )
        self.assert_invalid(root, "duplicate")
        pointer.write_text(
            '{"schemaVersion":"recap-catalog-pointer/1.0",'
            '"current":"v001","previous":NaN}',
            encoding="utf-8",
        )
        self.assert_invalid(root, "non-finite")
        pointer.write_text('{"value":1e999}', encoding="utf-8")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.load_json(pointer, 4096)

    def test_malformed_required_forms_is_controlled_validation_error(self):
        design = design_value()
        design["appliesWhen"]["requiredForms"] = [["tasks"]]
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_design_shape(design)

    def test_schema_artifacts_are_closed_and_complete(self):
        design_schema = json.loads(
            (ROOT / "schemas/design.schema.json").read_text(encoding="utf-8")
        )
        release_schema = json.loads(
            (ROOT / "schemas/release.schema.json").read_text(encoding="utf-8")
        )
        applies = design_schema["properties"]["appliesWhen"]
        self.assertFalse(applies["additionalProperties"])
        self.assertEqual(
            ["requiredForms", "minimumUnits", "maximumUnits"],
            applies["required"],
        )
        profiles = design_schema["properties"]["profiles"]
        self.assertFalse(profiles["additionalProperties"])
        self.assertIn("$defs", design_schema)
        self.assertIn(
            "pattern",
            release_schema["properties"]["designs"]["items"]["properties"]["path"],
        )
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        write_json(root / "schemas/design.schema.json", {})
        self.assert_invalid(root, "schema artifact")
        create_valid_tree(root)
        schema_path = root / "schemas/design.schema.json"
        weakened = json.loads(schema_path.read_text(encoding="utf-8"))
        weakened["properties"]["priority"]["maximum"] = 1001
        write_json(schema_path, weakened)
        self.assert_invalid(root, "schema artifact")
        create_valid_tree(root)
        malformed = json.loads(schema_path.read_text(encoding="utf-8"))
        del malformed["properties"]["profiles"]
        write_json(schema_path, malformed)
        self.assert_invalid(root, "schema artifact")

    def test_identifier_and_path_boundaries(self):
        valid_release_ids = ("v001", "v999")
        invalid_release_ids = ("v000", "v01", "v1000", "V001")
        valid_design_ids = ("a", "a" + "1" * 63, "status-actions")
        invalid_design_ids = ("", "1a", "A", "a" * 65, "a_b")
        for value in valid_release_ids:
            self.validator.validate_release_id(value)
        for value in invalid_release_ids:
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_release_id(value)
        for value in valid_design_ids:
            self.validator.validate_design_id(value)
        for value in invalid_design_ids:
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_design_id(value)
        self.validator.validate_design_path("a", "designs/a/design.json")
        for value in (
            "/designs/a/design.json",
            "designs\\a\\design.json",
            "designs/../a/design.json",
            "designs%2fa/design.json",
            "designs/b/design.json",
        ):
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_design_path("a", value)

    def test_depth_and_byte_boundaries(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for depth in (7, 8):
            value = "leaf"
            for _ in range(depth):
                value = {"a": value}
            path = root / f"depth-{depth}.json"
            write_json(path, value)
            self.validator.load_json(path, 4096)
        value = "leaf"
        for _ in range(9):
            value = {"a": value}
        path = root / "depth-9.json"
        write_json(path, value)
        with self.assertRaises(self.validator.ValidationError):
            self.validator.load_json(path, 4096)
        for limit in (4 * 1024, 32 * 1024, 64 * 1024):
            exact = root / f"exact-{limit}.json"
            payload = '{"a":"' + ("x" * (limit - 8)) + '"}'
            exact.write_text(payload, encoding="utf-8")
            self.assertEqual(limit, exact.stat().st_size)
            self.validator.load_json(exact, limit)
            exact.write_text(payload + " ", encoding="utf-8")
            with self.assertRaises(self.validator.ValidationError):
                self.validator.load_json(exact, limit)

        deeply_nested = root / "deep-malformed.json"
        deeply_nested.write_text(("[" * 1500) + "0" + ("]" * 1500), encoding="utf-8")
        with self.assertRaises(self.validator.ValidationError) as context:
            self.validator.load_json(
                deeply_nested,
                self.validator.EXAMPLE_LIMIT,
                self.validator.EXAMPLE_MAX_DEPTH,
            )
        self.assertIn("JSON", str(context.exception))

    def test_example_and_schema_tooling_limits(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, limit, depth in (
            ("example.json", self.validator.EXAMPLE_LIMIT, self.validator.EXAMPLE_MAX_DEPTH),
            ("schema.json", self.validator.SCHEMA_LIMIT, self.validator.SCHEMA_MAX_DEPTH),
        ):
            path = root / name
            payload = '{"a":"' + ("x" * (limit - 8)) + '"}'
            path.write_text(payload, encoding="utf-8")
            self.validator.load_json(path, limit, depth)
            path.write_text(payload + " ", encoding="utf-8")
            with self.assertRaises(self.validator.ValidationError):
                self.validator.load_json(path, limit, depth)
        nested = "leaf"
        for _ in range(self.validator.EXAMPLE_MAX_DEPTH):
            nested = {"a": nested}
        path = root / "example-depth.json"
        write_json(path, nested)
        self.validator.load_json(
            path,
            self.validator.EXAMPLE_LIMIT,
            self.validator.EXAMPLE_MAX_DEPTH,
        )
        nested = {"a": nested}
        write_json(path, nested)
        with self.assertRaises(self.validator.ValidationError):
            self.validator.load_json(
                path,
                self.validator.EXAMPLE_LIMIT,
                self.validator.EXAMPLE_MAX_DEPTH,
            )

    def test_repository_total_limits(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        files = []
        for index in range(self.validator.REPOSITORY_FILE_LIMIT):
            path = root / f"f{index}"
            path.write_bytes(b"")
            files.append((f"f{index}", path))
        self.validator.enforce_repository_limits(files)
        extra = root / "extra"
        extra.write_bytes(b"")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.enforce_repository_limits(files + [("extra", extra)])

        exact = root / "exact"
        exact.write_bytes(b"x" * self.validator.REPOSITORY_BYTE_LIMIT)
        self.validator.enforce_repository_limits([("exact", exact)])
        exact.write_bytes(exact.read_bytes() + b"x")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.enforce_repository_limits([("exact", exact)])

        temporary2, root2 = self.with_tree()
        self.addCleanup(temporary2.cleanup)
        current_count = len(self.validator.repository_files(root2))
        for index in range(self.validator.REPOSITORY_FILE_LIMIT - current_count):
            write_json(root2 / "examples" / f"extra-{index}.json", {})
        self.validator.validate_repository(root2)
        write_json(root2 / "examples" / "one-too-many.json", {})
        self.assert_invalid(root2, "file-count")

    def test_content_specific_and_release_byte_limits(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        pointer = root / "catalog/current.json"
        pointer.write_bytes(pointer.read_bytes() + b" " * 4096)
        self.assert_invalid(root, "byte limit")

        temporary2, root2 = self.with_tree()
        self.addCleanup(temporary2.cleanup)
        manifest_path = root2 / "catalog/releases/v001/manifest.json"
        manifest_path.write_bytes(manifest_path.read_bytes() + b" " * (32 * 1024))
        self.assert_invalid(root2, "byte limit")

        temporary3, root3 = self.with_tree()
        self.addCleanup(temporary3.cleanup)
        design_path = root3 / "catalog/releases/v001/designs/status-actions/design.json"
        design_path.write_bytes(design_path.read_bytes() + b" " * (64 * 1024))
        manifest_path = root3 / "catalog/releases/v001/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["designs"][0]["sha256"] = hashlib.sha256(
            design_path.read_bytes()
        ).hexdigest()
        write_json(manifest_path, manifest)
        self.assert_invalid(root3, "byte limit")

        temporary4, root4 = self.with_tree()
        self.addCleanup(temporary4.cleanup)
        release_root = root4 / "catalog/releases/v001"
        shutil.rmtree(release_root / "designs")
        source_asset = (
            ROOT
            / "catalog/releases/v002/assets/summit-readiness-layout.png"
        ).read_bytes()
        source_design = json.loads(
            (
                ROOT
                / "catalog/releases/v002/designs/summit-readiness/design.json"
            ).read_text(encoding="utf-8")
        )
        entries = []
        for index in range(26):
            design_id = f"d{index}"
            path = release_root / "designs" / design_id / "design.json"
            asset_id = f"a{index}"
            design = json.loads(json.dumps(source_design))
            design["id"] = design_id
            design["renderGuidance"]["referenceImage"]["assetId"] = asset_id
            write_json(path, design)
            asset_path = release_root / "assets" / f"{asset_id}.png"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(source_asset)
            entries.append(
                {
                    "id": design_id,
                    "path": f"designs/{design_id}/design.json",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "assets": [{
                        "id": asset_id,
                        "path": f"assets/{asset_id}.png",
                        "sha256": hashlib.sha256(source_asset).hexdigest(),
                        "mimeType": "image/png",
                        "byteLength": len(source_asset),
                        "width": 720,
                        "height": 480,
                    }],
                }
            )
        manifest = {
            "schemaVersion": "recap-design-release/1.1",
            "id": "v001",
            "status": "approved",
            "designs": entries,
        }
        write_json(release_root / "manifest.json", manifest)
        self.assert_invalid(root4, "release byte limit")

        temporary5, root5 = self.with_tree()
        self.addCleanup(temporary5.cleanup)
        release_root = root5 / "catalog/releases/v001"
        shutil.rmtree(release_root / "designs")
        design_ids = ["status-actions"] + [f"d{index}" for index in range(1, 8)]
        entries = [
            {
                "id": design_id,
                "path": f"designs/{design_id}/design.json",
                "sha256": "0" * 64,
            }
            for design_id in design_ids
        ]
        manifest_path = release_root / "manifest.json"
        manifest = {
            "schemaVersion": "recap-design-release/1.0",
            "id": "v001",
            "status": "approved",
            "designs": entries,
        }
        write_json(manifest_path, manifest)
        design_total = (512 * 1024) - manifest_path.stat().st_size
        base_size, remainder = divmod(design_total, len(design_ids))
        for index, design_id in enumerate(design_ids):
            path = release_root / "designs" / design_id / "design.json"
            write_json(path, design_value(design_id))
            target_size = base_size + (1 if index < remainder else 0)
            path.write_bytes(path.read_bytes() + b" " * (target_size - path.stat().st_size))
            entries[index]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
        exact_total = manifest_path.stat().st_size + sum(
            (release_root / entry["path"]).stat().st_size for entry in entries
        )
        self.assertEqual(512 * 1024, exact_total)
        self.validator.validate_repository(root5)

    def test_design_count_boundaries(self):
        for count in (0, 1):
            entries = [
                {
                    "id": "d0",
                    "path": "designs/d0/design.json",
                    "sha256": "0" * 64,
                }
            ][:count]
            manifest = {
                "schemaVersion": "recap-design-release/1.0",
                "id": "v001",
                "status": "approved",
                "designs": entries,
            }
            if count == 0:
                with self.assertRaises(self.validator.ValidationError):
                    self.validator.validate_manifest_shape(manifest)
            else:
                self.validator.validate_manifest_shape(manifest)
        for count in (29, 30):
            entries = [
                {
                    "id": f"d{index}",
                    "path": f"designs/d{index}/design.json",
                    "sha256": "0" * 64,
                }
                for index in range(count)
            ]
            self.validator.validate_manifest_shape(
                {
                    "schemaVersion": "recap-design-release/1.0",
                    "id": "v001",
                    "status": "approved",
                    "designs": entries,
                }
            )
        entries = [
            {
                "id": f"d{index}",
                "path": f"designs/d{index}/design.json",
                "sha256": "0" * 64,
            }
            for index in range(31)
        ]
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_manifest_shape(
                {
                    "schemaVersion": "recap-design-release/1.0",
                    "id": "v001",
                    "status": "approved",
                    "designs": entries,
                }
            )
        for bad_hash in ("0" * 63, "0" * 65, "A" * 64):
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_manifest_shape(
                    {
                        "schemaVersion": "recap-design-release/1.0",
                        "id": "v001",
                        "status": "approved",
                        "designs": [
                            {
                                "id": "d0",
                                "path": "designs/d0/design.json",
                                "sha256": bad_hash,
                            }
                        ],
                    }
                )

    def test_allowed_path_pattern_boundaries(self):
        for path in (
            "catalog/releases/v001/manifest.json",
            "catalog/releases/v999/designs/a/design.json",
            "examples/a.json",
            "examples/status_actions.JSON".replace(".JSON", ".json"),
            "examples/Status Actions.json",
            "schemas/a.schema.json",
            "schemas/Response.schema.json",
            ".gitattributes",
        ):
            self.assertTrue(self.validator.is_allowed_path(path), path)
        for path in (
            "catalog/releases/v000/manifest.json",
            "catalog/releases/v1000/manifest.json",
            "catalog/releases/v001/designs/A/design.json",
            "catalog/releases/v001/designs/a/extra.json",
            "examples/a.txt",
            "schemas/a.json",
            "tests/__init__.py",
            ".github/CODEOWNERS",
        ):
            self.assertFalse(self.validator.is_allowed_path(path), path)
        self.assertNotIn("tests/__init__.py", self.validator.REQUIRED_PATHS)
        self.assertFalse((ROOT / "tests" / "__init__.py").exists())

    def test_design_rule_boundaries_and_publication_probes(self):
        design = design_value()
        probes = self.validator.build_publication_probes(design)
        self.assertGreaterEqual(len(probes), 4)
        self.assertTrue(any(len(probe) == 30 for probe in probes))
        for units in probes:
            plans = self.validator.generate_plans(design, units)
            for profile in ("cowork-native", "bizchat-rich-text"):
                sections = plans[profile]["sections"]
                self.assertEqual(len(units), len(sections))
                self.assertEqual(
                    [f"s{index}" for index in range(1, len(units) + 1)],
                    [section["id"] for section in sections],
                )
                self.assertEqual(
                    sorted(unit["id"] for unit in units),
                    sorted(section["unitId"] for section in sections),
                )

    def test_pointer_and_design_boundary_table(self):
        pointer = {
            "schemaVersion": "recap-catalog-pointer/1.0",
            "current": "v001",
            "previous": "v002",
        }
        self.validator.validate_pointer_shape(pointer)
        pointer["previous"] = "v001"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_pointer_shape(pointer)

        valid = design_value()
        for priority in (0, 1000):
            candidate = json.loads(json.dumps(valid))
            candidate["priority"] = priority
            self.validator.validate_design_shape(candidate)
        for priority in (-1, 1001, True):
            candidate = json.loads(json.dumps(valid))
            candidate["priority"] = priority
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_design_shape(candidate)
        for version in ("1.0.0", "999.0.1"):
            candidate = json.loads(json.dumps(valid))
            candidate["version"] = version
            self.validator.validate_design_shape(candidate)
        for version in ("0.1.0", "1.0", "v1.0.0"):
            candidate = json.loads(json.dumps(valid))
            candidate["version"] = version
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_design_shape(candidate)

        for title in ("A", "A" + "z" * 79):
            self.validator.validate_title({"kind": "literal", "value": title})
        for title in (
            "",
            "A" + "z" * 80,
            "http:" + "unsafe",
            "line\nbreak",
            "bidi\u202etext",
        ):
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_title({"kind": "literal", "value": title})

        for minimum, maximum in ((2, 2), (2, 30)):
            candidate = json.loads(json.dumps(valid))
            candidate["appliesWhen"]["minimumUnits"] = minimum
            candidate["appliesWhen"]["maximumUnits"] = maximum
            self.validator.validate_design_shape(candidate)
        for minimum, maximum in ((1, 30), (2, 31), (3, 2)):
            candidate = json.loads(json.dumps(valid))
            candidate["appliesWhen"]["minimumUnits"] = minimum
            candidate["appliesWhen"]["maximumUnits"] = maximum
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_design_shape(candidate)

        thirteen_forms = json.loads(json.dumps(valid))
        thirteen_forms["appliesWhen"] = {
            "requiredForms": list(self.validator.FORMS),
            "minimumUnits": 13,
            "maximumUnits": 30,
        }
        self.validator.validate_design_shape(thirteen_forms)
        fourteen_forms = json.loads(json.dumps(thirteen_forms))
        fourteen_forms["appliesWhen"]["requiredForms"].append("tasks")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_design_shape(fourteen_forms)

        fourteen_rules = json.loads(json.dumps(valid))
        fourteen_rules["profiles"]["cowork-native"]["rules"] = [
            {
                "kind": "form",
                "form": form,
                "title": {"kind": "block-title"},
            }
            for form in self.validator.FORMS
        ] + [{"kind": "remaining", "title": {"kind": "block-title"}}]
        self.validator.validate_design_shape(fourteen_rules)
        fifteen_rules = json.loads(json.dumps(fourteen_rules))
        fifteen_rules["profiles"]["cowork-native"]["rules"].insert(
            0,
            {
                "kind": "form",
                "form": "tasks",
                "title": {"kind": "block-title"},
            },
        )
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_design_shape(fifteen_rules)

    def test_bootstrap_and_release_change_matrix(self):
        scenarios = ("changed", "deleted", "renamed", "added")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                temporary, root = self.with_tree()
                try:
                    self._git(root, "init", "-b", "main")
                    self._git(root, "config", "user.name", "Catalog Test")
                    self._git(
                        root,
                        "config",
                        "user.email",
                        "catalog" + "@example.invalid",
                    )
                    self._git(root, "add", ".")
                    self._git(root, "commit", "-m", "base")
                    base = self._git(root, "rev-parse", "HEAD").strip()
                    origin = root / ".git" / "origin-test"
                    self._git(root, "clone", "--bare", ".", str(origin))
                    self._git(root, "remote", "add", "origin", str(origin))
                    release = root / "catalog/releases/v001"
                    if scenario == "changed":
                        path = release / "designs/status-actions/design.json"
                        path.write_text(path.read_text() + " ", encoding="utf-8")
                    elif scenario == "deleted":
                        shutil.rmtree(release)
                    elif scenario == "renamed":
                        release.rename(root / "catalog/releases/v002")
                    else:
                        added = root / "catalog/releases/v002"
                        shutil.copytree(release, added)
                    self._git(root, "add", "-A")
                    self._git(root, "commit", "-m", scenario)
                    if scenario == "added":
                        self.validator.validate_immutable_releases(root, base)
                        self.validator.validate_immutable_releases(root, "HEAD^")
                        self.validator.validate_immutable_releases(root, "origin/main")
                    else:
                        for base_ref in (base, "HEAD^", "origin/main"):
                            with self.assertRaises(self.validator.ValidationError):
                                self.validator.validate_immutable_releases(root, base_ref)
                finally:
                    temporary.cleanup()

    def test_exact_bootstrap_commit_may_skip_parent_comparison(self):
        ancestry = subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout="c4213d051263810bbdfa0793d2d8f2192258ed50\n",
            stderr="",
        )
        with mock.patch.object(self.validator, "git", return_value=ancestry):
            self.validator.validate_immutable_releases(ROOT, "HEAD^")

    def test_unrelated_root_commit_fails_closed(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.name", "Catalog Test")
        self._git(root, "config", "user.email", "catalog" + "@example.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "-m", "bootstrap")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_repository(root, base_ref="HEAD^")

    def test_previous_release_must_exist(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        pointer_path = root / "catalog/current.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["previous"] = "v999"
        write_json(pointer_path, pointer)
        self.assert_invalid(root, "previous release is missing")

    @staticmethod
    def _git(root, *arguments):
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode:
            raise AssertionError(completed.stderr)
        return completed.stdout


class WorkflowSafetyTests(unittest.TestCase):
    def test_workflow_is_pinned_and_least_privilege(self):
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(
            encoding="utf-8"
        )
        lowered = workflow.lower()
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertRegex(workflow, r"(?m)^on:\s*$")
        self.assertRegex(workflow, r"(?m)^  pull_request:\s*$")
        self.assertRegex(workflow, r"(?m)^  push:\s*$")
        self.assertRegex(workflow, r"(?m)^    branches:\s*\n      - main\s*$")
        self.assertNotIn("pull_request_target", lowered)
        self.assertNotIn("workflow_run", lowered)
        self.assertNotIn("repository_dispatch", lowered)
        self.assertNotIn("workflow_dispatch", lowered)
        self.assertNotIn("schedule:", lowered)
        self.assertNotIn("issue_comment", lowered)
        self.assertNotIn("environment:", lowered)
        self.assertNotIn("secrets.", lowered)
        self.assertNotRegex(lowered, r"\bwrite\b")
        uses = re.findall(r"^\s*uses:\s*(\S+)", workflow, re.MULTILINE)
        self.assertTrue(uses)
        self.assertTrue(all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in uses))
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn(
            "python -B -m unittest discover -s tests -p 'test_*.py'",
            workflow,
        )
        self.assertNotRegex(workflow, r"(?m)^\s*run:.*\s-t(?:\s|$)")
        self.assertIn("BASE_REF_NAME: ${{ github.base_ref }}", workflow)
        run_blocks = "\n".join(
            match.group(1)
            for match in re.finditer(
                r"(?ms)^\s+run:\s*\|\n(.*?)(?=^\s{6}- name:|\Z)",
                workflow,
            )
        )
        self.assertNotIn("${{ github.base_ref }}", run_blocks)
        self.assertIn('git fetch --no-tags origin "$BASE_REF_NAME"', workflow)
        self.assertIn('BASE_REF="origin/$BASE_REF_NAME"', workflow)
        self.assertIn('BASE_REF="HEAD^"', workflow)
        self.assertIn(
            'python scripts/validate_catalog.py --base-ref "$BASE_REF"', workflow
        )
        self.assertNotRegex(lowered, r"python\s+catalog/")


if __name__ == "__main__":
    unittest.main()
