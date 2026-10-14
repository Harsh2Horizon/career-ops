from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from career_ops.common.config import Workspace
from career_ops.common.workflow import Workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


@pytest.fixture
def workspace(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / "templates", tmp_path / "templates")
    shutil.copyfile(FIXTURES / "profile.yaml", tmp_path / "resume.yaml")
    # Reuse the already-cached TeX bundle in an isolated writable copy for tests.
    cached = ROOT / "data/resumes/.tectonic-cache"
    if cached.exists():
        shutil.copytree(cached, tmp_path / "data/resumes/.tectonic-cache")
    return Workspace(tmp_path)


@pytest.fixture
def flow(workspace):
    return Workflow(workspace)


@pytest.fixture
def job(flow):
    return flow.import_job(json.loads((FIXTURES / "sample_job.json").read_text()))
