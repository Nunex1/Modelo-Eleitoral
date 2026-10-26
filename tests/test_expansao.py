"""Segundo turno, horários das urnas e simulador hipotético: rigor e transparência.

Os cenários sintéticos usam a base de conftest.synthetic; os reais, a base preparada
com o 2º turno e as referências lidas diretamente dos arquivos brutos do TSE.
"""
import io
import json
from pathlib import Path

import pandas as pd
import pytest

from lampiadim import charts
from lampiadim.assistant import ConversationState, answer_question
from lampiadim.data import Filters
from lampiadim.engine import engine_for, largest_remainder
from lampiadim.responses import simulation_table
from lampiadim.tools import SIMULATION, SIMULATION_WARNING, Plan, QueryError, execute
from lampiadim.verification import VerificationError

T2026 = Filters(year=2026, turn=1)


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


def ask(data, questions, filters=T2026):
    state = ConversationState.from_filters(filters)
    answers = []
    for question in questions:
        answer = answer_question(question, data, state)
        state = answer.state
        answers.append(answer)
    return answers


def town(data, code):
    return engine_for(data).kb.city_by_code[code]


# ---------------------------------------------------------------------------- simulador: matemática
def test_mandatory_example_100_votes_60_30_10(synthetic):
    """Exemplo obrigatório: 100 votos, eleitorado 60/30/10 → 60/30/10 votos simulados."""
    result = execute(engine_for(synthetic), Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90005"),), dimensions=("sexo",)))
    rows = result.data["runs"][0]["rows"].set_index("sexo")
    assert rows.loc["FEMININO", "VOTOS_SIMULADOS"] == 60 and rows.loc["MASCULINO", "VOTOS_SIMULADOS"] == 30 and rows.loc["NÃO INFORMADO", "VOTOS_SIMULADOS"] == 10
    assert result.trace["natureza"] == SIMULATION and result.trace["aviso"] == SIMULATION_WARNING


def test_proportional_scenario_matches_composition_and_reconciles(synthetic):
    """Alfaville: 100 votos sobre 30/20/1 eleitores; maiores restos fecham exatamente 100."""
    result = execute(engine_for(synthetic), Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90001"),), dimensions=("sexo",)))
    rows = result.data["runs"][0]["rows"].set_index("sexo")
    assert rows.VOTOS_SIMULADOS.sum() == 100
    assert rows.VOTOS_EXATOS.to_dict() == pytest.approx({"FEMININO": 100 * 30 / 51, "MASCULINO": 100 * 20 / 51, "NÃO INFORMADO": 100 * 1 / 51})
    assert rows.VOTOS_SIMULADOS.to_dict() == {"FEMININO": 59, "MASCULINO": 39, "NÃO INFORMADO": 2}


def test_weighted_scenario_formula(synthetic):
    """Mulheres × 2: pesos 1,2 / 0,3 / 0,1 → 75 / 18,75 / 6,25 → 75 / 19 / 6."""
    plan = Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90005"),), dimensions=("sexo",), factors={"sexo": {"FEMININO": 2.0}})
    rows = execute(engine_for(synthetic), plan).data["runs"][0]["rows"].set_index("sexo")
    assert rows.VOTOS_EXATOS.to_dict() == pytest.approx({"FEMININO": 75.0, "MASCULINO": 18.75, "NÃO INFORMADO": 6.25})
    assert rows.VOTOS_SIMULADOS.to_dict() == {"FEMININO": 75, "MASCULINO": 19, "NÃO INFORMADO": 6}


@pytest.mark.parametrize("exact,total", [([33.4, 33.3, 33.3], 100), ([0.5, 0.5], 1), ([0, 0, 0], 0), ([2.9999, 0.0001], 3), ([1 / 3] * 3, 1)])
def test_largest_remainder_sums_and_stays_within_one(exact, total):
    rounded = largest_remainder(exact, total)
    assert int(rounded.sum()) == total and ((rounded - pd.Series(exact)).abs() < 1).all() and (rounded >= 0).all()


def test_absent_groups_and_zero_votes(synthetic):
    """Deltário: nenhum eleitor 'não informado' e 0 votos — grupo ausente não aparece, soma é zero."""
    rows = execute(engine_for(synthetic), Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90004"),),
                                               dimensions=("sexo",))).data["runs"][0]["rows"]
    assert "NÃO INFORMADO" not in set(rows.sexo) and rows.VOTOS_SIMULADOS.sum() == 0
    assert rows.PARTICIPACAO.sum() == pytest.approx(1)


def test_joint_distribution_uses_official_cross_table(synthetic):
    """Dois recortes usam a tabela conjunta do cadastro, não o produto das marginais."""
    rows = execute(engine_for(synthetic), Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90005"),),
                                               dimensions=("sexo", "idade"))).data["runs"][0]["rows"]
    # No cadastro sintético cada sexo tem uma única faixa: só 3 células existem (independência daria 9).
    assert len(rows) == 3 and rows.VOTOS_SIMULADOS.sum() == 100


def test_invalid_simulations_are_rejected(synthetic):
    engine = engine_for(synthetic)
    with pytest.raises(QueryError):
        execute(engine, Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90005"),), dimensions=("renda",)))
    with pytest.raises(QueryError):
        execute(engine, Plan("simular_distribuicao_demografica", (2026, 1), ("LULA",), territories=(town(synthetic, "90005"),), dimensions=("sexo",), factors={"sexo": {"FEMININO": 50}}))


def test_simulation_verification_catches_wrong_totals():
    from lampiadim.tools import verify_simulation
    rows = pd.DataFrame({"PARTICIPACAO": [.6, .4], "VOTOS_EXATOS": [60.0, 40.0], "VOTOS_SIMULADOS": [61, 40]})
    with pytest.raises(VerificationError):
        verify_simulation({"rows": rows, "votes": 100}, 100, False)


# ---------------------------------------------------------------------------- simulador: transparência
def test_exports_and_charts_always_carry_the_warning(synthetic):
    result = execute(engine_for(synthetic), Plan("simular_distribuicao_demografica", (2026, 1), ("LULA", "ZEFERINO"), territories=(town(synthetic, "90005"),), dimensions=("sexo",)))
    from lampiadim.data import csv_bytes
    for run in result.data["runs"]:
        table = simulation_table(run, ("sexo",))
        assert table.Natureza.eq("SIMULAÇÃO HIPOTÉTICA").all() and table.Aviso.eq(SIMULATION_WARNING).all()
        exported = pd.read_csv(io.BytesIO(csv_bytes(table)), sep=";", decimal=",", encoding="utf-8-sig")
        assert exported.Aviso.eq(SIMULATION_WARNING).all() and exported["Votos simulados"].sum() == run["votes"]
    runs = [{**r, "display": r["candidate"].title()} for r in result.data["runs"]]
    figure = charts.simulation(runs, ("sexo",))
    texts = [a.text.replace("<br>", " ").replace("<b>", "").replace("</b>", "") for a in figure.layout.annotations]
    assert any(SIMULATION_WARNING in t for t in texts) and "HIPOTÉTICO" in texts
    assert all(trace.marker.color == charts.SIM_FILL and trace.marker.pattern.shape for trace in figure.data)
    assert all(trace.marker.color != charts.BLUE for trace in figure.data) and all("votos simulados" in trace.name for trace in figure.data)


def test_chat_simulation_flow_preserves_context(synthetic):
    first, second = ask(synthetic, ["Simule como os votos de Lula foram distribuídos entre homens e mulheres em Exemplopolis",
                                    "Agora faça a mesma simulação para Zeferino."])
    assert first.text.startswith(f"**{SIMULATION_WARNING}**") and first.nature == SIMULATION
    assert "60 votos simulados" in first.text and "30 votos simulados" in first.text and "Hipótese" in first.text
    assert first.tables and first.tables[0][1].Natureza.eq("SIMULAÇÃO HIPOTÉTICA").all()
    assert second.nature == SIMULATION and "Zeferino" in second.text and "50 votos oficiais" in second.text
    assert second.state.dimensions == ("sexo",) and second.state.territories[0].code == "90005"


def test_real_vote_question_is_not_answered_with_simulation(synthetic):
    a = answer_question("Quantas mulheres realmente votaram em Lula em Exemplopolis?", synthetic)
    assert a.text.startswith("Não é possível determinar.") and not a.trace and a.nature == ""
    b = answer_question("Quantas mulheres votaram em Lula em Exemplopolis?", synthetic)
    assert b.text.startswith("Não é possível determinar.") and not b.trace


def test_simulation_by_education_uses_territory_profile(synthetic):
    _, a = ask(synthetic, ["Quantos votos Lula teve em Exemplopolis?", "Simule os votos por escolaridade no primeiro turno."])
    assert a.nature == SIMULATION and a.trace[0]["turno"] == 1 and a.trace[0]["filtros"]["territorios"] == ["Exemplopolis/SP"]
    assert "escolaridade" in a.text


def test_simulation_without_dimension_asks(synthetic):
    a = answer_question("Simule os votos de Lula em Exemplopolis", synthetic)
    assert a.clarification and "recorte" in a.text and not a.trace


# ---------------------------------------------------------------------------- horários
def test_timing_summary_from_logs(synthetic):
    result = execute(engine_for(synthetic), Plan("consultar_horarios", (2026, 1), territories=(town(synthetic, "90005"),), metric="resumo"))
    s = result.data["summary"]
    assert s["urnas"] == 1 and s["estendidas"] == 1 and s["votos_apos_17h"] == 7 and s["ultimo_voto"] == "18:05:12"
    assert result.trace["validacao"] == "aprovada"


def test_hourly_distribution_comes_from_logs(synthetic):
    a = answer_question("Qual a distribuição dos votos por faixa horária em Alfaville?", synthetic)
    assert a.tables and a.tables[0][1]["Votos computados"].sum() == 200
    assert "não a candidatura" in a.text


def test_votes_after_17h_and_extended_urns_in_chat(synthetic):
    after, extended, last = ask(synthetic, ["Quantos votos foram computados depois das 17h em Exemplopolis?",
                                            "Quantas urnas tiveram encerramento tardio em Exemplopolis?", "Qual foi o horário do último voto em Exemplopolis?"])
    assert after.text.startswith("7 votos foram computados depois das 17h")
    assert "1 das 1 urnas" in extended.text and "17h45" in extended.text
    assert "18:05:12" in last.text


@pytest.mark.parametrize("question", ["Quantos votos Lula recebeu depois das 17h?", "Quantos votos Lula recebeu depois das 17h em Exemplopolis?",
                                      "Zeferino ganhou nas urnas estendidas de Alfaville?", "Em quem votaram os eleitores depois das 17h?"])
def test_times_are_never_attributed_to_candidates(synthetic, question):
    a = answer_question(question, synthetic)
    assert a.text.startswith("Não é possível saber.") and not a.trace


def test_timing_tables_have_no_candidate_columns(synthetic, data):
    for d in [synthetic, data]:
        for frame in [d.timing, d.timing_hours]:
            assert frame is None or not ({"NM_URNA_CANDIDATO", "NR_CANDIDATO", "SG_PARTIDO"} & set(frame.columns))


def test_timing_unavailable_is_explicit(synthetic):
    a = answer_question("Qual a distribuição dos votos por faixa horária em Gamalandia?", synthetic)
    assert not a.trace and ("Não há registros de horário" in a.text or "faixa horária exige" in a.text)


# ---------------------------------------------------------------------------- natureza da informação
@pytest.mark.parametrize("question,nature", [("Quantos votos Lula teve em Alfaville?", "DADO OFICIAL"), ("Qual o percentual de Lula em Alfaville?", "CÁLCULO ESTATÍSTICO"),
                                             ("Simule os votos de Lula por sexo em Alfaville", "SIMULAÇÃO HIPOTÉTICA")])
def test_every_answer_declares_its_nature(synthetic, question, nature):
    a = answer_question(question, synthetic)
    assert a.nature == nature and all(t["natureza"] for t in a.trace) and any(nature in s for s in a.sources)


# ---------------------------------------------------------------------------- 2º turno (dados reais)
AMERICANA, CAMPINAS = "61310", "62910"


def test_second_round_reconciles_with_official_files(data, ref):
    """Município, UF e Brasil: motor = arquivos oficiais de divulgação lidos diretamente."""
    engine = engine_for(data)
    kb = engine.kb
    for territory, expected in [(kb.city_by_code[AMERICANA], {c: ref.second_round(c, AMERICANA) for c in ["LULA", "FLAVIO BOLSONARO"]}),
                                (kb.state("SP"), {c: ref.second_round(c, uf="SP") for c in ["LULA", "FLAVIO BOLSONARO"]}),
                                (kb.state("RJ"), {c: ref.second_round(c, uf="RJ") for c in ["LULA", "FLAVIO BOLSONARO"]})]:
        rows = engine.result((2026, 2), territory)["rows"]
        assert dict(zip(rows.NM_URNA_CANDIDATO, rows.VOTOS)) == expected
    brasil = engine.result((2026, 2), kb.state("SP").__class__("brasil"))["rows"]
    assert dict(zip(brasil.NM_URNA_CANDIDATO, brasil.VOTOS)) == {c: ref.second_round(c) for c in ["LULA", "FLAVIO BOLSONARO"]}
    info = data.candidate_info[data.candidate_info.NR_TURNO.eq(2)].set_index("NM_URNA_CANDIDATO")
    assert info.loc["LULA", "DS_SIT_TOT_TURNO"] == "ELEITO" and info.loc["FLAVIO BOLSONARO", "DS_SIT_TOT_TURNO"] == "NÃO ELEITO"
    report = data.manifest["sources"]["divulgacao"]["elections"]["6258"]
    assert report["reconciliado_ufs_e_brasil"] and report["arquivos"] == 5787


def test_second_round_queries_never_use_first_round_records(data):
    engine = engine_for(data)
    second = engine._period_votes((2026, 2))
    assert second.NR_TURNO.eq(2).all() and set(second.NM_URNA_CANDIDATO) == {"LULA", "FLAVIO BOLSONARO"}
    assert len(second) == 2 * second.CD_MUNICIPIO.nunique() == 2 * 5571
    first = engine._period_votes((2026, 1))
    assert first.NR_TURNO.eq(1).all() and int(first.VOTOS.sum()) == 118_969_906
    assert data.candidates_for(2026, 2) == ["FLAVIO BOLSONARO", "LULA"] and len(data.candidates_for(2026, 1)) == 12


def test_first_round_divulgacao_equals_consolidated_file(data):
    """Equivalência das fontes: a divulgação do 1º turno coincide linha a linha com o arquivo consolidado."""
    report = data.manifest["sources"]["divulgacao"]["elections"].get("6257")
    if report is None:
        pytest.skip("coleta da divulgação do 1º turno ainda não integrada")
    assert report["equivalente_ao_consolidado"]["divergencias"] == 0 and report["equivalente_ao_consolidado"]["linhas_comparadas"] == 66852


def test_chat_second_round_and_turn_comparison(data, ref):
    a, b, c = ask(data, ["Quantos votos Lula teve em Americana no segundo turno?", "E Bolsonaro?", "Compare os dois turnos em Americana"])
    assert f"{ref.second_round('LULA', AMERICANA):,}".replace(",", ".") in a.text and "2º turno" in a.text
    assert f"{ref.second_round('FLAVIO BOLSONARO', AMERICANA):,}".replace(",", ".") in b.text
    assert c.trace[0]["ferramenta"] == "comparar_turnos" and "1º turno" in c.text and "2º turno" in c.text
    assert f"{ref.candidate_votes('LULA', AMERICANA):,}".replace(",", ".") in c.text and f"{ref.second_round('LULA', AMERICANA):,}".replace(",", ".") in c.text


def test_without_ui_context_the_turn_is_asked(data):
    a = answer_question("Quantos votos Lula teve em Americana?", data, ConversationState())
    assert a.clarification and "1º e 2º turno" in a.text and not a.trace


def test_mandatory_chat_example_second_round(data, ref):
    """Exemplo do enunciado: Lula em Americana, 2º turno, homens e mulheres, depois Flávio Bolsonaro."""
    first, second = ask(data, ["Lampiadim, simule como os votos de Lula foram distribuídos entre homens e mulheres em Americana no segundo turno.",
                               "Agora faça a mesma simulação para Flávio Bolsonaro."])
    for answer, candidate in [(first, "LULA"), (second, "FLAVIO BOLSONARO")]:
        votes = ref.second_round(candidate, AMERICANA)
        table = answer.tables[0][1]
        assert answer.nature == SIMULATION and answer.text.startswith(f"**{SIMULATION_WARNING}**")
        assert int(table["Votos simulados"].sum()) == votes and answer.trace[0]["turno"] == 2
        shares = ref.profile[ref.profile.CD_MUNICIPIO == AMERICANA].groupby("DS_GENERO").QT_ELEITORES.sum()
        exact = dict(zip(table.Categoria.str.upper(), table["Votos simulados (exatos)"]))
        assert exact["FEMININO"] == pytest.approx(votes * shares["FEMININO"] / shares.sum(), abs=1e-4)
    assert second.state.territories[0].code == AMERICANA and second.state.dimensions == ("sexo",) and second.state.period == (2026, 2)


# ---------------------------------------------------------------------------- horários (dados reais)
def test_timing_matches_urnas_tardias_csv_read_directly(data, ref):
    csv = ref.timing()
    engine = engine_for(data)
    for code in [AMERICANA, CAMPINAS, "60011"]:
        expected = csv[csv.cd_mun == code]
        s = execute(engine, Plan("consultar_horarios", (2026, 2), territories=(engine.kb.city_by_code[code],), metric="resumo")).data["summary"]
        assert s["urnas"] == len(expected) and s["estendidas"] == int(expected.classe.eq("estendida").sum())
        assert s["votos_apos_17h"] == int(expected.votos_apos_17h.sum()) and s["votos_log"] == int(expected.votos_total.sum())
        assert s["ultimo_voto"] == expected.ultimo_voto_brt.dropna().max()
    brasil = execute(engine, Plan("consultar_horarios", (2026, 2), territories=(engine.kb.state("SP").__class__("brasil"),), metric="estendidas")).data["summary"]
    assert brasil["urnas"] == len(csv) == 497882 and brasil["estendidas"] == 7352


def test_own_log_collection_validates_published_csv(data):
    timing = data.manifest["sources"]["timing"]
    assert timing["validacao_cruzada"]["secoes_comparadas"] >= 3000 and timing["validacao_cruzada"]["divergentes"] == 0
    assert set(timing["coleta_propria"]["municipios_cobertos"]["2"]) >= {AMERICANA, CAMPINAS}
    rec = timing["reconciliacao_comparecimento"]["2"]
    assert rec["municipios_com_mais_votos_no_log"] == 0 and rec["votos_nos_logs"] <= rec["comparecimento_oficial"]


def test_hourly_distribution_sums_to_log_votes(data, ref):
    csv = ref.timing()
    a = answer_question("Qual a distribuição dos votos por faixa horária em Americana no segundo turno?", data)
    table = a.tables[0][1]
    assert int(table["Votos computados"].sum()) == int(csv[csv.cd_mun == AMERICANA].votos_total.sum()) and a.nature == "DADO OFICIAL"
    assert "não a candidatura" in a.text


def test_chat_timing_questions_real(data, ref):
    csv = ref.timing()
    rio = csv[csv.cd_mun == "60011"]
    a, b = ask(data, ["Quantos votos foram computados depois das 17h no Rio de Janeiro no segundo turno?", "Quantas urnas estendidas houve no Brasil?"], Filters(year=2026, turn=2))
    if a.clarification:  # "Rio de Janeiro" é ambíguo (estado ou cidade): escolher a cidade
        a = answer_question("a cidade", data, a.state)
    assert f"{int(rio.votos_apos_17h.sum()):,}".replace(",", ".") in a.text
    assert "7.352" in b.text
    refusal = answer_question("Quantos votos Lula recebeu depois das 17h no Rio de Janeiro?", data)
    assert refusal.text.startswith("Não é possível saber.") and not refusal.trace


def test_first_round_timing_only_where_logs_were_collected(data):
    """1º turno: só Americana e Campinas têm logs; um total "Brasil" com dois municípios seria enganoso."""
    raw =Path(__file__).resolve().parents[1] / "dados/brutos/logs_urna_2026/3220/municipios.jsonl"
    if not raw.exists():
        pytest.skip("logs brutos do 1º turno ausentes nesta máquina")
    records = [json.loads(line) for line in raw.read_text(encoding="utf-8").splitlines()]
    # São Paulo está no horário de Brasília: o encerramento local já é o de Brasília.
    logged = [r for r in records if r["cd_mun"] == AMERICANA and not r.get("erro")]
    extended = sum(r["encerramento_local"][-1] >= "17:45:00" for r in logged)
    refusal, town_answer = ask(data, ["Quantas urnas estendidas houve no Brasil no primeiro turno?",
                                      "Quantas urnas estendidas houve em Americana no primeiro turno?"])
    assert not refusal.trace and "Americana/SP" in refusal.text and "Campinas/SP" in refusal.text
    assert town_answer.trace[0]["turno"] == 1 and f"{extended} das {len(logged)} urnas" in town_answer.text
    rec = data.manifest["sources"]["timing"]["reconciliacao_comparecimento"]["1"]
    assert rec["municipios_com_mais_votos_no_log"] == 0 and rec["secoes_sem_log"] == 0
