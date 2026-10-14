"""Reuse installed dependencies in a dedicated venv; normal setup uses uv sync."""

import argparse
import importlib.metadata
import re
import shutil
import sys
import sysconfig
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--from-site", action="append", required=True)
args = parser.parse_args()
if sys.prefix == sys.base_prefix:
    raise SystemExit("Run inside a dedicated virtual environment")
target = Path(sysconfig.get_paths()["purelib"])


def normalize(s):
    return re.sub(r"[-_.]+", "-", s).lower()


available = {}
for directory in args.from_site:
    for dist in importlib.metadata.distributions(path=[directory]):
        available.setdefault(normalize(dist.metadata["Name"]), dist)
needed = [
    "pydantic",
    "pyyaml",
    "typer",
    "rich",
    "httpx",
    "beautifulsoup4",
    "jinja2",
    "pypdf",
    "pytest",
    "ruff",
]
done = set()
while needed:
    name = normalize(needed.pop())
    if name in done:
        continue
    if name not in available:
        raise SystemExit(f"No installed distribution available for {name}")
    dist = available[name]
    for filename in dist.files or []:
        if ".." in filename.parts:
            if filename.parts[-1] == "ruff" and Path(dist.locate_file(filename)).is_file():
                shutil.copy2(dist.locate_file(filename), Path(sys.executable).parent / "ruff")
            continue
        source, destination = Path(dist.locate_file(filename)), target / filename
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for requirement in dist.requires or []:
        if ";" in requirement and (
            "extra" in requirement.split(";", 1)[1] or "win32" in requirement
        ):
            continue
        dependency = normalize(re.match(r"[\w.-]+", requirement).group())
        if dependency in available:
            needed.append(dependency)
    done.add(name)
root = Path(__file__).resolve().parents[1]
(target / "career_ops.pth").write_text(str(root / "src") + "\n")
entry = Path(sys.executable).parent / "careerops"
entry.write_text(f"#!{sys.executable}\nfrom career_ops.cli.main import main\nmain()\n")
entry.chmod(0o755)
print(f"Reused {len(done)} installed distributions in {sys.prefix}")
