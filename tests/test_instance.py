from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.instance import (
    InstanceError,
    init_instance,
    relock_instance,
    validate_instance_directory,
    validate_instance_document,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "team-instance" / "input" / "instance.json"


def load_example() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class InstanceFactoryTests(unittest.TestCase):
    def test_init_is_atomic_valid_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            summary = init_instance(EXAMPLE, first)
            init_instance(EXAMPLE, second)

            self.assertEqual(summary["errors"], 0)
            self.assertEqual(tree_digest(first), tree_digest(second))
            self.assertEqual(validate_instance_directory(first), [])
            self.assertTrue((first / "AI-BOOTSTRAP.md").is_file())
            self.assertTrue((first / ".agent-team" / "instance.lock.json").is_file())

    def test_init_never_overwrites_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "owned"
            output.mkdir()
            marker = output / "preserve.txt"
            marker.write_text("preserve\n", encoding="utf-8")
            with self.assertRaises(InstanceError):
                init_instance(EXAMPLE, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")

    def test_factory_repository_cannot_be_an_instance_output(self) -> None:
        with self.assertRaises(InstanceError):
            init_instance(EXAMPLE, ROOT)

    def test_bootstrap_rejects_excess_autonomy_and_nonhuman_production(self) -> None:
        document = load_example()
        document["autonomy"]["maximum"] = "A3"
        document["autonomy"]["production_requires_human"] = False
        messages = {finding.message for finding in validate_instance_document(document)}
        self.assertIn("Factory bootstrap cannot exceed A2", messages)
        self.assertIn("initial Factory instances require human production approval", messages)

    def test_owner_must_control_both_approval_gates(self) -> None:
        document = load_example()
        document["approvals"]["plan_approvers"] = ["human.someone-else"]
        findings = validate_instance_document(document)
        self.assertTrue(any("owner must be an approver" in finding.message for finding in findings))

    def test_unknown_team_pack_version_is_rejected(self) -> None:
        document = load_example()
        document["team_pack"]["version"] = "99.0.0"
        findings = validate_instance_document(document)
        self.assertTrue(
            any("not provided by this Factory" in finding.message for finding in findings)
        )

    def test_inline_secret_field_and_credential_value_are_rejected(self) -> None:
        document = load_example()
        document["adapters"][0]["config"] = {"auth_token": "not-even-a-real-token"}
        findings = validate_instance_document(document)
        self.assertTrue(any("inline secret field" in finding.message for finding in findings))

        document = load_example()
        document["adapters"][0]["config"] = {"endpoint": "ghp_" + ("A" * 24)}
        findings = validate_instance_document(document)
        self.assertTrue(any("credential-like value" in finding.message for finding in findings))

    def test_unsafe_runtime_path_is_rejected(self) -> None:
        document = load_example()
        document["runtime"]["workspace_root"] = "../../production"
        findings = validate_instance_document(document)
        self.assertTrue(any("safe relative path" in finding.message for finding in findings))

    def test_runtime_state_cannot_overlap_instance_authority(self) -> None:
        document = load_example()
        document["runtime"]["state_location"] = ".agent-team/instance.json"
        findings = validate_instance_document(document)
        self.assertTrue(any("reserved runtime" in finding.message for finding in findings))

    def test_managed_drift_fails_but_seeded_drift_warns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "instance"
            init_instance(EXAMPLE, instance)
            (instance / "AI-BOOTSTRAP.md").write_text("changed\n", encoding="utf-8")
            (instance / "README.md").write_text("customized\n", encoding="utf-8")
            findings = validate_instance_directory(instance)
            self.assertTrue(any(f.severity == "ERROR" and "managed" in f.message for f in findings))
            self.assertTrue(
                any(f.severity == "WARNING" and "customized" in f.message for f in findings)
            )

    def test_configuration_change_requires_explicit_relock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "instance"
            init_instance(EXAMPLE, instance)
            config_path = instance / ".agent-team" / "instance.json"
            document = json.loads(config_path.read_text(encoding="utf-8"))
            document["limits"]["max_budget_units"] = 101
            write_json(config_path, document)
            findings = validate_instance_directory(instance)
            self.assertTrue(any("relock" in finding.message for finding in findings))
            relock_instance(instance)
            self.assertEqual(validate_instance_directory(instance), [])

    def test_relock_refuses_managed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "instance"
            init_instance(EXAMPLE, instance)
            (instance / "AGENTS.md").write_text("redirect elsewhere\n", encoding="utf-8")
            with self.assertRaises(InstanceError):
                relock_instance(instance)

    def test_duplicate_adapter_slot_is_rejected(self) -> None:
        document = load_example()
        document["adapters"].append(copy.deepcopy(document["adapters"][0]))
        findings = validate_instance_document(document)
        self.assertTrue(
            any("adapter slots must be unique" in finding.message for finding in findings)
        )


if __name__ == "__main__":
    unittest.main()
