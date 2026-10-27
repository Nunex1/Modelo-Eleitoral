"""Transporte eleitoral exploratório. Nenhum fluxo é um comportamento observado."""
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .evolution import COMPOSITION, LABELS

FLOW_WARNING = "SIMULAÇÃO HIPOTÉTICA. OS FLUXOS NÃO REPRESENTAM A MIGRAÇÃO REAL E INDIVIDUAL DOS ELEITORES."
DESTINATIONS = [c for c in COMPOSITION if c != "OUTROS"]


class IncompatibleScenario(ValueError):
    pass


@dataclass(frozen=True)
class Assumptions:
    constant_population: bool = False
    lula_retention: float = .8
    flavio_retention: float = .8
    others_to_lula: float | None = None
    abstention_to_lula: float | None = None
    invalid_to_valid_max: float = 1.0
    preference: str = "retencao"


def margins(comparison):
    first, second = comparison["first"], comparison["second"]
    if not first["closed"] or not second["closed"]:
        raise IncompatibleScenario("As categorias não esgotam o eleitorado apto. Categorias técnicas ou ajustes impedem fechar a matriz.")
    a = np.array([first["totals"][c] for c in COMPOSITION], dtype=float)
    b = np.array([second["totals"][c] for c in DESTINATIONS], dtype=float)
    if a.sum() != b.sum():
        raise IncompatibleScenario("O eleitorado apto difere entre turnos neste recorte. Não é defensável fabricar entradas ou saídas para fechar a matriz.")
    if a.sum() <= 0:
        raise IncompatibleScenario("Eleitorado nulo: matriz indisponível.")
    return a, b


def identification_bounds(comparison):
    a, b = margins(comparison)
    total = a.sum()
    return pd.DataFrame([{"Origem": LABELS[origin], "Destino": LABELS[destination],
                          "Limite inferior": max(0, a[i] + b[j] - total), "Limite superior": min(a[i], b[j])}
                         for i, origin in enumerate(COMPOSITION) for j, destination in enumerate(DESTINATIONS)])


def solve(comparison, assumptions=Assumptions()):
    if not assumptions.constant_population:
        raise IncompatibleScenario("Declare a hipótese de composição constante. Totais iguais não comprovam que são as mesmas pessoas.")
    for value in [assumptions.lula_retention, assumptions.flavio_retention, assumptions.others_to_lula,
                  assumptions.abstention_to_lula, assumptions.invalid_to_valid_max]:
        if value is not None and (not np.isfinite(value) or not 0 <= value <= 1):
            raise IncompatibleScenario("As proporções hipotéticas devem estar entre zero e um.")
    if assumptions.preference not in {"retencao", "outros", "abstencao"}:
        raise IncompatibleScenario("Objetivo de otimização desconhecido")
    from scipy.optimize import linprog
    a, b = margins(comparison)
    m, n = len(a), len(b)
    eq = np.zeros((m + n, m * n))
    for i in range(m):
        eq[i, i * n:(i + 1) * n] = 1
    for j in range(n):
        eq[m + j, j::n] = 1
    bounds = [(0, None)] * (m * n)
    bounds[0] = (a[0] * assumptions.lula_retention, None)
    bounds[n + 1] = (a[1] * assumptions.flavio_retention, None)
    for i, value in [(2, assumptions.others_to_lula), (5, assumptions.abstention_to_lula)]:
        if value is not None:
            bounds[i * n] = (a[i] * value, a[i] * value)
    ub = np.zeros((2, m * n))
    for k, i in enumerate([3, 4]):
        ub[k, i * n:i * n + 2] = 1
    limits = a[[3, 4]] * assumptions.invalid_to_valid_max
    cost = np.zeros(m * n)
    if assumptions.preference == "retencao":
        for i, origin in enumerate(COMPOSITION):
            if origin in DESTINATIONS:
                cost[i * n + DESTINATIONS.index(origin)] = -1
    else:
        cost[(2 if assumptions.preference == "outros" else 5) * n] = -1
    result = linprog(cost, A_eq=eq, b_eq=np.r_[a, b], bounds=bounds, A_ub=ub, b_ub=limits, method="highs")
    if not result.success:
        raise IncompatibleScenario("Premissas incompatíveis com as margens oficiais. Reduza as restrições; nenhum Sankey foi produzido.")
    matrix = result.x.reshape(m, n)
    if (matrix < -1e-6).any() or not np.allclose(matrix.sum(axis=1), a, atol=1e-5, rtol=0) or not np.allclose(matrix.sum(axis=0), b, atol=1e-5, rtol=0):
        raise IncompatibleScenario("O solucionador não conservou os totais dentro da tolerância numérica.")
    # Limites identificados condicionais: dois problemas LP, não intervalos de confiança.
    objective = np.zeros(m * n)
    objective[2 * n] = 1
    low = linprog(objective, A_eq=eq, b_eq=np.r_[a, b], bounds=bounds, A_ub=ub, b_ub=limits, method="highs")
    high = linprog(-objective, A_eq=eq, b_eq=np.r_[a, b], bounds=bounds, A_ub=ub, b_ub=limits, method="highs")
    if not low.success or not high.success:
        raise IncompatibleScenario("Não foi possível validar os limites condicionais.")
    return {"matrix": pd.DataFrame(matrix, index=[LABELS[k] for k in COMPOSITION], columns=[LABELS[k] for k in DESTINATIONS]),
            "assumptions": assumptions, "conditional_bounds": (float(low.fun), float(-high.fun)), "warning": FLOW_WARNING}


def sensitivity(comparison, assumptions):
    rows = []
    for value in sorted({max(0, assumptions.lula_retention - .1), assumptions.lula_retention, min(1, assumptions.lula_retention + .1)}):
        for objective in ["retencao", "outros", "abstencao"]:
            try:
                result = solve(comparison, replace(assumptions, lula_retention=value, preference=objective))
                matrix = result["matrix"]
                rows.append({"Retenção mínima Lula": value, "Objetivo": objective, "Compatível": True,
                             "Outros → Lula": matrix.loc["Demais candidatos", "Lula"],
                             "Abstenção → Lula": matrix.loc["Abstenção", "Lula"], "Natureza": "SIMULAÇÃO HIPOTÉTICA"})
            except IncompatibleScenario:
                rows.append({"Retenção mínima Lula": value, "Objetivo": objective, "Compatível": False,
                             "Outros → Lula": None, "Abstenção → Lula": None, "Natureza": "SIMULAÇÃO HIPOTÉTICA"})
    return pd.DataFrame(rows)
