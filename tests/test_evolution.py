"""Validação independente dos novos indicadores, proteções e cenários.

Dados artificiais só aparecem nos testes de impossibilidade/zero/transporte.
Os testes de integração leem os JSONs brutos, não a própria fórmula em produção.
"""
from copy import copy, deepcopy
from dataclasses import replace
from fractions import Fraction
from io import BytesIO
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from lampiadim.assistant import answer_question
from lampiadim.data import Filters
from lampiadim.engine import DataUnavailable, Engine, engine_for
from lampiadim.entities import BRASIL, Territory
from lampiadim.evolution import COMPOSITION, Evolution, decompose, evolution_for, export_table, ratio, validate_counts
from lampiadim.evolution_charts import composition, waterfall, sankey, territorial_map
from lampiadim.evolution_exports import export_png, export_pdf
from lampiadim.transfers import Assumptions, FLOW_WARNING, IncompatibleScenario, identification_bounds, sensitivity, solve

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def service(data):
    return evolution_for(engine_for(data))


def raw(turn, uf, city=""):
    election = "6257" if turn == 1 else "6258"
    path = ROOT / "dados/brutos/divulgacao_2026" / election / uf / f"{uf}{city}-c0001-e00{election}-u.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("city", ["61310", "62910"])
@pytest.mark.parametrize("turn", [1, 2])
def test_municipal_counts_against_raw_json(service, city, turn):
    d = raw(turn, "sp", city)
    s = service.snapshot(2026, turn, service.engine.kb.city_by_code[city])
    t = s["totals"]
    for name, section, field in [("ELEITORADO_APTO", "e", "te"), ("COMPARECIMENTO", "e", "c"), ("ABSTENCAO", "e", "a"),
                                 ("VOTOS_BRANCOS", "v", "vb"), ("VOTOS_NULOS", "v", "tvn"), ("VOTOS_VALIDOS", "v", "vv")]:
        assert t[name] == int(d[section][field])
    assert s["rates"]["ABSTENCAO"] == pytest.approx(100 * int(d["e"]["a"]) / int(d["e"]["te"]))
    assert s["rates"]["VOTOS_NULOS"] == pytest.approx(100 * int(d["v"]["tvn"]) / int(d["e"]["c"]))
    votes = {c['n']: int(c['vap']) for g in d['carg'][0]['agr'] for p in g['par'] for c in p['cand']}
    assert t["LULA"] == votes["13"] and t["FLAVIO"] == votes["22"]


@pytest.mark.parametrize("turn", [1, 2])
def test_national_including_exterior_and_tte_not_corrected_twice(service, turn):
    s = service.snapshot(2026, turn, Territory("total"))
    raw_br = raw(turn, "br")
    assert s["totals"]["VOTOS_VALIDOS"] == int(raw_br["v"]["vv"])
    assert s["totals"]["COMPARECIMENTO"] == int(raw_br["e"]["c"])
    assert s["totals"]["APTOS_PUBLICADOS"] == 158745502
    assert s["totals"]["ELEITORADO_APTO"] == 158745463
    assert not s["closed"]
    assert s["totals"]["APTOS_SECOES_NAO_INSTALADAS"] == 423
    assert service.snapshot(2026, turn, Territory("total"))["totals"]["ELEITORADO_APTO"] == 158745463
    domestic = service.snapshot(2026, turn, BRASIL)
    exterior = service.snapshot(2026, turn, Territory("exterior"))
    for name in ["LULA", "FLAVIO", "VOTOS_VALIDOS", "COMPARECIMENTO", "ABSTENCAO"]:
        assert domestic["totals"][name] + exterior["totals"][name] == s["totals"][name]


def test_exact_decomposition_and_zero():
    assert ratio(0, 0) is None and decompose(0, 7, 0, 10) is None
    for values in [(3, 8, 11, 17), (53722151, 64056078, 118969906, 123710622), (8, 3, 17, 11), (0, 0, 10, 10)]:
        d = decompose(*values)
        assert isinstance(d["participacao"], Fraction)
        assert d["participacao"] + d["base"] == values[1] - values[0]
    with pytest.raises(ValueError):
        decompose(20, 1, 10, 10)


def test_aggregations_rates_and_territory_change(service, data):
    sp = service.engine.kb.state("SP")
    table = service.territorial(2026, sp)
    snapshot = service.snapshot(2026, 2, sp)
    assert table.CD_MUNICIPIO.is_unique
    assert table.ABSTENCAO_2.sum() == snapshot["totals"]["ABSTENCAO"]
    assert snapshot["rates"]["ABSTENCAO"] == pytest.approx(100 * table.ABSTENCAO_2.sum() / table.ELEITORADO_APTO_2.sum())
    assert snapshot["rates"]["ABSTENCAO"] != pytest.approx(table.ABSTENCAO_TAXA_2.mean())
    city = service.engine.kb.city_by_code["61310"]
    r = table.set_index("CD_MUNICIPIO").loc[city.code]
    c = service.compare(2026, city)
    assert r.ABSTENCAO_PP == pytest.approx(c["table"].set_index("Chave").loc["ABSTENCAO", "Variação (p.p.)"])
    filters = Filters(turn=2, region="SUDESTE", uf="SP", ddd=19, municipality="61310", sexo="FEMININO")
    codes = tuple(data.geography(filters).CD_MUNICIPIO)
    assert codes == ("61310",)
    assert service.compare(2026, city, codes)["first"]["totals"] == c["first"]["totals"]


@pytest.mark.parametrize("fault", ["duplicate", "null", "negative", "nominal", "coverage", "partial", "fractional", "schema"])
def test_bad_data_blocks_numbers(data, fault):
    d = copy(data)
    d.totalization = data.totalization.copy()
    d.votes = data.votes.copy()
    if fault == "duplicate":
        d.totalization = pd.concat([d.totalization, d.totalization.iloc[:1]])
    elif fault == "null":
        d.totalization.loc[0, "VOTOS_BRANCOS"] = np.nan
    elif fault == "negative":
        d.totalization.loc[0, "VOTOS_NULOS"] = -1
    elif fault == "nominal":
        d.votes.loc[0, "VOTOS"] += 1
    elif fault == "coverage":
        d.totalization = d.totalization.iloc[1:]
    elif fault == "partial":
        d.totalization.loc[0, "TOTALIZACAO_FINAL"] = False
    elif fault == "fractional":
        d.totalization["ABSTENCAO"] = d.totalization.ABSTENCAO.astype(float)
        d.totalization.loc[0, "ABSTENCAO"] += .5
    elif fault == "schema":
        d.totalization = d.totalization.drop(columns="COMPARECIMENTO")
    with pytest.raises(DataUnavailable):
        Evolution(Engine(d)).snapshot(2026, 1, BRASIL)


def artificial_margins():
    a = dict(zip(COMPOSITION, [350, 300, 100, 30, 40, 180]))
    b = dict(zip(COMPOSITION, [450, 400, 0, 20, 30, 100]))
    a["ELEITORADO_APTO"] = b["ELEITORADO_APTO"] = 1000
    return {"first": {"totals": a, "closed": True}, "second": {"totals": b, "closed": True}}


def test_transport_conserves_margins_and_identification_bounds():
    c = artificial_margins()
    assumptions = Assumptions(constant_population=True)
    result = solve(c, assumptions)
    matrix = result["matrix"]
    assert np.allclose(matrix.sum(axis=1), [350, 300, 100, 30, 40, 180])
    assert np.allclose(matrix.sum(axis=0), [450, 400, 20, 30, 100])
    assert matrix.loc["Lula", "Lula"] >= 280
    bounds = identification_bounds(c)
    assert (bounds["Limite inferior"] <= bounds["Limite superior"]).all()
    assert result["warning"] == FLOW_WARNING
    assert "SIMULAÇÃO HIPOTÉTICA" in sankey(result).layout.title.text
    scenarios = sensitivity(c, assumptions)
    assert len(scenarios) == 9 and scenarios["Natureza"].eq("SIMULAÇÃO HIPOTÉTICA").all()
    assert scenarios["Outros → Lula"].nunique() > 1


def test_transport_infeasible_and_open_population_blocked(service):
    c = artificial_margins()
    with pytest.raises(IncompatibleScenario):
        solve(c)
    with pytest.raises(IncompatibleScenario):
        solve(c, Assumptions(True, 1, 1, 1, 1))
    for territory in [BRASIL, service.engine.kb.city_by_code["61310"], service.engine.kb.city_by_code["62910"], Territory("total")]:
        with pytest.raises(IncompatibleScenario):
            solve(service.compare(2026, territory), Assumptions(True))


@pytest.mark.parametrize("question,token", [
    ("Quanto Lula cresceu do primeiro para o segundo turno?", "10.333.927"),
    ("Quantos votos adicionais Lula recebeu em Campinas?", "61.942"),
    ("Qual foi a diferença da abstenção em Americana entre os dois turnos?", "-3.997"),
    ("Quais municípios de São Paulo tiveram maior redução de abstenção?", "Campinas/SP"),
    ("Qual estado registrou a maior taxa de votos nulos?", "TO"),
    ("Em quais cidades Lula apresentou o maior crescimento proporcional?", "Hidrolândia/GO"),
    ("Qual foi a evolução dos votos brancos no Brasil?", "-869.161"),
])
def test_requested_conversations(data, question, token):
    answer = answer_question(question, data, Filters(turn=2))
    assert token in answer.text and not answer.clarification
    assert answer.trace[0]["ferramenta"] == "consultar_indicadores"
    assert answer.trace[0]["validacao"] == "aprovada"
    assert answer.nature == "CÁLCULO ESTATÍSTICO"


@pytest.mark.parametrize("question", [
    "É possível estimar quantos eleitores dos demais candidatos votaram em Lula no segundo turno?",
    "Quantos eleitores que se abstiveram no primeiro turno votaram em Lula no segundo?",
    "Simule a transferência de votos dos outros candidatos para Lula",
    "Quantos votos Lula recebeu depois das 17h?",
    "Em que horário foram computados os votos de Flávio Bolsonaro?",
])
def test_no_unobserved_individual_or_timing_claims(data, question, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key-test-only")
    from lampiadim.llm import ModelInterpreter
    monkeypatch.setattr(ModelInterpreter, "frames", lambda *args: pytest.fail("Proteção local deve impedir chamada externa"))
    answer = answer_question(question, data, Filters(turn=2))
    assert not answer.trace and "Não é possível" in answer.text


def test_official_demographic_totals_and_context(data):
    a = answer_question("Qual a taxa de abstenção das mulheres?", data, Filters(turn=2, municipality="61310", uf="SP", sexo="FEMININO"))
    assert "34.080" in a.text and "não se aplicam" in a.text and "Americana/SP" in a.text
    b = answer_question("E em Campinas?", data, a.state)
    assert "Campinas/SP" in b.text and b.trace[0]["turno"] == 2


@pytest.mark.parametrize("question", ["Quantos votos anulados houve?", "Quantos votos inválidos houve?", "Qual a quantidade de votos anulados sub judice?"])
def test_technical_categories_are_never_reported_as_null_or_turnout(data, question):
    answer = answer_question(question, data, Filters(turn=2))
    assert not answer.trace and "categorias" in answer.text


def test_ddd_crossing_states_keeps_panel_intersection_and_explicit_override(data):
    filters = Filters(turn=2, uf="GO", ddd=61)
    codes = tuple(data.geography(filters).CD_MUNICIPIO)
    rows = data.totalization
    expected = int(rows.loc[rows.NR_TURNO.eq(2) & rows.CD_MUNICIPIO.isin(codes), "ABSTENCAO"].sum())
    first = answer_question("Qual a abstenção?", data, filters)
    assert f"{expected:,}".replace(",", ".") in first.text and "DDD 61 · GO" in first.text
    assert first.filters.uf == "GO"
    followup = answer_question("E no primeiro turno?", data, first.state)
    assert followup.filters.uf == "GO" and followup.trace
    explicit = answer_question("Qual a abstenção no DDD 61?", data, first.state)
    assert explicit.filters.uf == "" and explicit.trace
    votes = answer_question("Quantos votos Lula recebeu?", data, filters)
    assert votes.trace and votes.trace[0]["validacao"] == "aprovada"


def test_figures_export_and_shared_values(service):
    c = service.compare(2026, BRASIL)
    bars = composition(c)
    assert sum(trace.x[0] for trace in bars.data) == pytest.approx(100)
    assert bars.data[2].x[1] == 0  # demais candidatos: zero estrutural, nunca fabricado
    fall = waterfall(c)
    assert fall.data[0].customdata[-1] == c["second"]["totals"]["LULA"]
    table = export_table(c)
    assert {"Fonte 1", "Fonte 2", "Definições", "Aviso", "Natureza", "Território"}.issubset(table)
    png, pdf = export_png(c), export_pdf(c)
    image = Image.open(BytesIO(png))
    assert image.size == (1600, 2300) and pdf.startswith(b"%PDF")
    assert b"/Type /Page" in pdf
    table = service.territorial(2026, BRASIL, "uf")
    fig = territorial_map(service.data, table, "ABSTENCAO_PP", "uf", "p.p.")
    assert sorted(fig.data[-1].marker.color) == sorted(table.ABSTENCAO_PP)


def test_large_data_cached_aggregation(service):
    started = time.perf_counter()
    table = service.territorial(2026, BRASIL)
    assert len(table) == 5571
    cold = time.perf_counter() - started
    started = time.perf_counter()
    for _ in range(100):
        assert service.territorial(2026, BRASIL) is table
    assert time.perf_counter() - started < .2
    assert cold < 5
