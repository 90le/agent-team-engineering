#!/usr/bin/env python3
"""Fail-closed release metadata, license, provenance, and history audit."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.json_support import loads_strict  # noqa: E402
from core.security import CREDENTIAL_PATTERNS  # noqa: E402

ALLOWED_EVALUATION_LICENSES = {"Apache-2.0", "MIT"}


class ReleaseAuditError(RuntimeError):
    pass


def _json(relative: str) -> dict[str, Any]:
    value = loads_strict((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseAuditError(f"JSON root is not an object: {relative}")
    return value


def validate_release_assets() -> dict[str, Any]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    factory = _json("factory-package.json")
    capability = _json("capability-package.json")
    codex = _json(".agents/plugins/plugins/agent-team/.codex-plugin/plugin.json")
    claude = _json(".agents/plugins/plugins/agent-team/.claude-plugin/plugin.json")
    marketplace = _json(".claude-plugin/marketplace.json")
    observed = {
        "VERSION": version,
        "pyproject": str(pyproject["project"]["version"]),
        "factory": str(factory["version"]),
        "capability": str(capability["version"]),
        "codex_plugin": str(codex["version"]),
        "claude_plugin": str(claude["version"]),
        "claude_marketplace_plugin": str(marketplace["plugins"][0]["version"]),
    }
    if set(observed.values()) != {version}:
        raise ReleaseAuditError(f"release versions differ: {observed}")
    if factory["status"] != "STABLE":
        raise ReleaseAuditError("factory package is not STABLE")
    if "Apache License" not in (ROOT / "LICENSE").read_text(encoding="utf-8"):
        raise ReleaseAuditError("Apache-2.0 license text is missing")

    sbom = _json("sbom/agent-team-engineering.spdx.json")
    if sbom.get("spdxVersion") != "SPDX-2.3" or sbom.get("dataLicense") != "CC0-1.0":
        raise ReleaseAuditError("SPDX document metadata is invalid")
    packages = sbom.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise ReleaseAuditError("SPDX must describe exactly the shipped dependency-free package")
    package = packages[0]
    if (
        not isinstance(package, dict)
        or package.get("versionInfo") != version
        or package.get("licenseDeclared") != "Apache-2.0"
        or package.get("filesAnalyzed") is not False
    ):
        raise ReleaseAuditError("SPDX package differs from release metadata")

    provenance = _json("supply-chain/source-provenance.json")
    if provenance.get("release") != f"v{version}":
        raise ReleaseAuditError("source provenance release differs from VERSION")
    if provenance.get("python_runtime_dependencies") != []:
        raise ReleaseAuditError("unexpected Python runtime dependency in provenance")
    if provenance.get("copied_external_source_files") != []:
        raise ReleaseAuditError("external source copy requires a separate license review")
    upstreams = provenance.get("evaluated_upstreams")
    if not isinstance(upstreams, list) or len(upstreams) < 6:
        raise ReleaseAuditError("evaluated upstream registry is incomplete")
    identities: set[str] = set()
    for record in upstreams:
        if not isinstance(record, dict):
            raise ReleaseAuditError("evaluated upstream entry is malformed")
        identity = str(record.get("id"))
        if identity in identities:
            raise ReleaseAuditError(f"duplicate evaluated upstream: {identity}")
        identities.add(identity)
        if record.get("license") not in ALLOWED_EVALUATION_LICENSES:
            raise ReleaseAuditError(f"unreviewed upstream license: {identity}")
        revision = str(record.get("revision", ""))
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise ReleaseAuditError(f"upstream revision is not an immutable commit: {identity}")
        if record.get("runtime_dependency") is not False:
            raise ReleaseAuditError(f"upstream unexpectedly became a runtime dependency: {identity}")
    return {
        "version": version,
        "metadata_sources": len(observed),
        "spdx_packages": len(packages),
        "evaluated_upstreams": len(upstreams),
    }


def scan_git_history(since_tag: str) -> int:
    try:
        listed = subprocess.run(
            ["git", "rev-list", "--objects", f"{since_tag}..HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ReleaseAuditError(f"cannot enumerate Git history since {since_tag}") from None
    scanned = 0
    for line in listed.stdout.splitlines():
        object_id, _, path = line.partition(" ")
        if not path:
            continue
        kind = subprocess.run(
            ["git", "cat-file", "-t", object_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        ).stdout.strip()
        if kind != "blob":
            continue
        size = int(
            subprocess.run(
                ["git", "cat-file", "-s", object_id],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            ).stdout.strip()
        )
        if size > 10 * 1024 * 1024:
            raise ReleaseAuditError(f"history contains an oversized blob: {path}")
        content = subprocess.run(
            ["git", "cat-file", "blob", object_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            timeout=10,
            shell=False,
        ).stdout
        scanned += 1
        if any(pattern.search(content.decode("utf-8", errors="ignore")) for pattern in CREDENTIAL_PATTERNS):
            raise ReleaseAuditError(
                f"history since {since_tag} contains a high-confidence credential pattern in {path}"
            )
    return scanned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-tag", default="v0.7.0")
    arguments = parser.parse_args()
    try:
        report = validate_release_assets()
        report["history_blobs_scanned"] = scan_git_history(arguments.since_tag)
    except ReleaseAuditError as error:
        print(f"release audit failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
