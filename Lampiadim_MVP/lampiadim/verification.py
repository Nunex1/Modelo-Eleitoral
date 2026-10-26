"""Verificação estatística dos resultados antes de qualquer resposta.

Cada resultado é conferido por invariantes (denominadores, somas, duplicidades,
faixas válidas) e, quando possível, recalculado pelo caminho independente usado
pelo dashboard (``ElectoralData.query``).
"""
from __future__ import annotations

import math

from .data import Filters
from .entities import REGIONS
from .language import numbers_in


class VerificationError(RuntimeError):
    pass


def check(condition, message):
    if not condition:
        raise VerificationError(message)


def _valid_pct(value):
    return value is None or (isinstance(value, float) and math.isnan(value)) or -1e-9 <= value <= 100 + 1e-9


def dashboard_filters(territory, period):
    """Filtros equivalentes do dashboard, quando o território existe nesse contrato."""
    year, turn = period
    if territory.kind == "municipio":
        return Filters(year=year, turn=turn, uf=territory.uf, municipality=territory.code)
    if territory.kind == "uf":
        return Filters(year=year, turn=turn, uf=territory.code)
    if territory.kind == "ddd":
        return Filters(year=year, turn=turn, ddd=int(territory.code))
    if territory.kind == "brasil":
        return Filters(year=year, turn=turn)
    return None


def verify_result(data, result, territory, period):
    rows, total = result["rows"], result["total"]
    check(total >= 0 and (rows.VOTOS >= 0).all(), "votos negativos")
    check(int(rows.VOTOS.sum()) == total, "soma das candidaturas difere do total de válidos")
    check(rows.NM_URNA_CANDIDATO.is_unique, "candidatura duplicada")
    check(all(_valid_pct(p) for p in rows.PERCENTUAL), "percentual fora de 0–100")
    if total:
        check(abs(rows.PERCENTUAL.sum() - 100) < 1e-6, "percentuais não somam 100")
    filters = dashboard_filters(territory, period)
    if filters is not None:
        reference = data.query(filters)
        check(reference["votes"] == total, "total diverge da consulta de referência")
        expected = dict(zip(reference["all_candidates"].NM_URNA_CANDIDATO, reference["all_candidates"].VOTOS))
        check(all(expected.get(r.NM_URNA_CANDIDATO, 0) == r.VOTOS for r in rows.itertuples()), "votos por candidatura divergem da referência")
    elif territory.kind == "regiao":
        parts = [data.query(Filters(year=period[0], turn=period[1], uf=uf))["votes"] for uf in REGIONS[territory.code][1]]
        check(sum(parts) == total, "total da região diverge da soma das UFs")
    elif territory.kind == "total":
        info = data.candidate_info[data.candidate_info.ANO_ELEICAO.eq(period[0]) & data.candidate_info.NR_TURNO.eq(period[1])]
        check(total == int(info.VOTOS_BRASIL.sum() + info.VOTOS_EXTERIOR.sum()), "total com exterior diverge")
    return "aprovada"


def verify_ranking(data, frame, scope, period, numerator_total=None):
    check(not frame.empty or numerator_total in (None, 0), "ranking vazio com dados no escopo")
    key = "CD_MUNICIPIO" if "CD_MUNICIPIO" in frame else "SG_UF"
    check(frame[key].is_unique, "registro territorial duplicado no ranking")
    check((frame.NUMERADOR >= 0).all() and (frame.NUMERADOR <= frame.DENOMINADOR).all(), "numerador maior que o denominador")
    check(all(_valid_pct(p) for p in frame.PERCENTUAL), "percentual fora de 0–100")
    if numerator_total is not None:
        check(int(frame.NUMERADOR.sum()) == numerator_total, "soma do ranking diverge do total do escopo")
    return "aprovada"


def verify_electorate(data, territory, categories, count, total, period_year):
    check(0 <= count <= total, "contagem cadastral fora do total")
    filters = dashboard_filters(territory, (period_year, data.turns(period_year)[0])) if data.turns(period_year) else None
    multi = [name for name, values in categories.items() if len(values) > 1]
    if filters is None or len(multi) > 1:
        return "aprovada (invariantes)"
    base = {name: values[0] for name, values in categories.items() if len(values) == 1}
    if multi:
        name = multi[0]
        expected = sum(data.query(Filters(**{**filters.__dict__, **base, name: value}))["selected_profile"] for value in categories[name])
    else:
        expected = data.query(Filters(**{**filters.__dict__, **base}))["selected_profile"]
    check(expected == count, "contagem cadastral diverge da consulta de referência")
    check(data.query(filters)["registered"] == total, "cadastro total diverge da consulta de referência")
    return "aprovada"


def verify_distribution(rows, total, expected_total):
    check(rows.CATEGORIA.is_unique, "categoria duplicada")
    check(int(rows.QT_ELEITORES.sum()) == total == expected_total, "distribuição não soma o total do recorte")
    if total:
        check(abs(rows.PERCENTUAL.sum() - 100) < 1e-6, "percentuais da distribuição não somam 100")
    return "aprovada"


def verify_grounded_text(text, allowed):
    """Todo número exibido precisa ter sido produzido pelo motor ou pelos parâmetros da consulta."""
    stray = [n for n in numbers_in(text) if n.rstrip(".,") not in allowed]
    check(not stray, "número sem origem verificável: " + ", ".join(stray[:3]))
    return "aprovada"
