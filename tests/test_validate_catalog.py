import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


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
    write_json(root / "examples" / "status-actions-request.json", request_value())
    write_json(root / "examples" / "status-actions-response.json", response_value())
    for name in (
        "catalog-pointer.schema.json",
        "release.schema.json",
        "design.schema.json",
    ):
        destination = root / "schemas" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "schemas" / name, destination)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "validate_catalog.py").write_text("# fixture\n", encoding="utf-8")
    (root / "tests" / "test_validate_catalog.py").write_text("# fixture\n", encoding="utf-8")
    (root / "README.md").write_text("Synthetic recap design catalog.\n", encoding="utf-8")
    (root / "SECURITY.md").write_text("Report issues without sensitive data.\n", encoding="utf-8")
    (root / ".github" / "CODEOWNERS").write_text("* @cfei_microsoft\n", encoding="utf-8")
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

    def test_valid_v001(self):
        summary = self.validator.validate_repository(ROOT)
        self.assertEqual("v001", summary["release"])
        self.assertEqual(1, summary["designs"])

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
                os.symlink(root / "README.md", root / "linked.md")
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
            "gim" + "-home",
            "GIM" + "-HOME",
            "SOX" + "-Design-Workspace",
            "dev." + "azure.com",
            "BEGIN " + "PRIVATE KEY",
            "ghp" + "_abcdefghijklmnopqrstuvwxyz",
        ]
        for value in cases:
            with self.subTest(value=value[:8]):
                temporary, root = self.with_tree()
                try:
                    (root / "SECURITY.md").write_text(value + "\n", encoding="utf-8")
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
        readme = root / "README.md"
        readme.write_text("Synthetic recap design catalog.\nUpdated.\n", encoding="utf-8")
        self.validator.validate_repository(root, base_ref=base)
        self._git(root, "add", "README.md")
        self._git(root, "commit", "-m", "docs")
        design_path = root / "catalog/releases/v001/designs/status-actions/design.json"
        design_path.write_text(design_path.read_text() + " ", encoding="utf-8")
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_immutable_releases(root, base)

    def test_examples_match_plugin_contract(self):
        self.validator.validate_examples(
            request_value(),
            response_value(),
            expected_release="v001",
            design=design_value(),
        )
        broken = response_value()
        broken["plans"]["cowork-native"]["sections"][0]["id"] = "s2"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                broken,
                expected_release="v001",
                design=design_value(),
            )
        wrong_design = response_value()
        wrong_design["design"] = "other"
        with self.assertRaises(self.validator.ValidationError):
            self.validator.validate_examples(
                request_value(),
                wrong_design,
                expected_release="v001",
                design=design_value(),
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
            )

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
        entries = []
        for index in range(9):
            design_id = f"d{index}"
            path = release_root / "designs" / design_id / "design.json"
            write_json(path, design_value(design_id))
            padding = (60 * 1024) - path.stat().st_size
            path.write_bytes(path.read_bytes() + b" " * padding)
            entries.append(
                {
                    "id": design_id,
                    "path": f"designs/{design_id}/design.json",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        manifest = {
            "schemaVersion": "recap-design-release/1.0",
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
        final_design = release_root / entries[-1]["path"]
        final_design.write_bytes(final_design.read_bytes() + b" ")
        entries[-1]["sha256"] = hashlib.sha256(final_design.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
        self.assert_invalid(root5, "release byte limit")

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
            "schemas/a.schema.json",
            ".github/CODEOWNERS",
        ):
            self.assertTrue(self.validator.is_allowed_path(path), path)
        for path in (
            "catalog/releases/v000/manifest.json",
            "catalog/releases/v1000/manifest.json",
            "catalog/releases/v001/designs/A/design.json",
            "catalog/releases/v001/designs/a/extra.json",
            "examples/a.txt",
            "schemas/a.json",
        ):
            self.assertFalse(self.validator.is_allowed_path(path), path)

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

    def test_root_bootstrap_skips_only_immutable_comparison(self):
        temporary, root = self.with_tree()
        self.addCleanup(temporary.cleanup)
        self._git(root, "init", "-b", "main")
        self._git(root, "config", "user.name", "Catalog Test")
        self._git(root, "config", "user.email", "catalog" + "@example.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "-m", "bootstrap")
        self.validator.validate_repository(root, base_ref="HEAD^")

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
        self.assertIn("python -B -m unittest discover -s tests", workflow)
        self.assertIn('git fetch --no-tags origin "${{ github.base_ref }}"', workflow)
        self.assertIn('BASE_REF="origin/${{ github.base_ref }}"', workflow)
        self.assertIn('BASE_REF="HEAD^"', workflow)
        self.assertIn(
            'python scripts/validate_catalog.py --base-ref "$BASE_REF"', workflow
        )
        self.assertNotRegex(lowered, r"python\s+catalog/")


if __name__ == "__main__":
    unittest.main()
