"""Regressão do conjunto de referência: toda falha encontrada deve virar um caso em avaliacao/referencias.json."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from avaliar_lampiadim import DIMENSIONS, evaluate


def test_reference_set_has_no_failures(data):
    result = evaluate(data)
    failed = [d for d in result["detalhes"] if not d["ok"]]
    assert not failed, failed
    for dimension in DIMENSIONS:
        assert result["resumo"][dimension]["taxa"] == 100.0, dimension
    assert result["resumo"]["desempenho_ms"]["p95"] < 2000
