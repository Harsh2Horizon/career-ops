"""Run the installed official validator plus check local resources/UI metadata."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

parser = argparse.ArgumentParser()
parser.add_argument(
    "--validator",
    type=Path,
    default=Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py",
)
args = parser.parse_args()
if not args.validator.is_file():
    raise SystemExit(
        "Installed skill validator missing; supply --validator PATH/TO/quick_validate.py"
    )
root = Path(__file__).resolve().parents[1]
results = []
for skill in sorted((root / ".agents/skills").iterdir()):
    validation = subprocess.run(
        [sys.executable, str(args.validator), str(skill)], capture_output=True, text=True
    )
    metadata = yaml.safe_load((skill / "agents/openai.yaml").read_text())
    assert 25 <= len(metadata["interface"]["short_description"]) <= 64
    assert "$" + skill.name in metadata["interface"]["default_prompt"]
    for resource in re.findall(r"\]\(([^)]+)\)", (skill / "SKILL.md").read_text()):
        if "://" not in resource:
            assert (skill / resource).exists(), f"Missing {skill.name}/{resource}"
    assert (skill / "scripts/run.py").is_file()
    results.append(
        {
            "skill": skill.name,
            "valid": validation.returncode == 0,
            "validator_output": validation.stdout.strip(),
        }
    )
print(json.dumps(results, indent=2))
if not all(result["valid"] for result in results):
    raise SystemExit(1)
