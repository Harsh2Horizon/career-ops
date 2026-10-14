"""Export versioned Pydantic contracts for cross-skill/agent integrations."""

import inspect
from pathlib import Path

from career_ops.common.io import write_json
from career_ops.models import contracts

root = Path(__file__).resolve().parents[1] / "schemas/v1"
for name, model in vars(contracts).items():
    if (
        inspect.isclass(model)
        and issubclass(model, contracts.Artifact)
        and model is not contracts.Artifact
    ):
        write_json(root / (name + ".json"), model.model_json_schema())
print(f"Exported contracts to {root}")
