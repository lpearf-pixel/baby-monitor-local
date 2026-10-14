import json
from pathlib import Path


def test_m7_15_matrix_is_frozen_and_uses_explicit_configuration():
    path = Path(__file__).parents[1] / "fixtures" / "m7_architecture_matrix_v1.json"
    matrix = json.loads(path.read_text(encoding="utf-8"))
    assert matrix["version"] == "m7-15-architecture-v1"
    assert [model["id"] for model in matrix["models"]] == ["A", "B", "C"]
    assert len(matrix["tasks"]) == 20
    assert len({task["id"] for task in matrix["tasks"]}) == 20
    assert matrix["models"][2]["deterministic_routing"] is True
    assert matrix["models"][2]["sensitive_routing"] is True
    assert matrix["models"][0]["deterministic_routing"] is False
    assert matrix["models"][1]["deterministic_routing"] is False
