"""Contrato com o modelo de linguagem, regressões do assistente anterior e casos territoriais."""
import json
from unittest.mock import patch

import httpx
import pytest

from conftest import br
from lampiadim.assistant import ConversationState, answer_question
from lampiadim.data import Filters

ENDPOINT = "https://api.openai.com/v1/responses"


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-never-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")


def model_response(*calls, status="completed"):
    output = [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": name, "arguments": json.dumps(args)} for i, (name, args) in enumerate(calls)]
    return httpx.Response(200, request=httpx.Request("POST", ENDPOINT), json={"status": status, "output": output})


TERRITORY = {"tipo": "municipio", "nome": "Americana", "uf": None}


def votes_call(candidates, territory=TERRITORY, metric="votos"):
    return ("consultar_votos", {"candidatos": candidates, "referencia_candidato": "", "territorios": [territory], "referencia_lugar": "", "ano": None, "turno": None, "metrica": metric})


# --------------------------------------------------------------------------- regressões do assistente anterior
def test_state_not_confused_with_capital(data, ref):
    a = answer_question("Qual a votação no estado de São Paulo?", data)
    assert a.filters.uf == "SP" and not a.filters.municipality and "no estado de São Paulo" in a.text
    assert int(a.tables[0][1]["Votos"].sum()) == ref.valid(uf="SP")
    total = answer_question("Quantos votos válidos teve o estado de São Paulo?", data)
    assert br(ref.valid(uf="SP")) in total.text


def test_homonym_requires_state(data):
    a = answer_question("Qual o resultado de Santa Helena?", data)
    assert a.clarification and "MA, PB, PR e SC" in a.text and not a.tables


def test_explicit_state_resolves_homonym(data):
    a = answer_question("Qual o resultado de Santa Helena/PR?", data)
    assert not a.clarification and a.filters.uf == "PR"


def test_homonym_answer_resolves_pending_question(data):
    question = answer_question("Qual o resultado de Santa Helena?", data)
    answer = answer_question("PR", data, question.state)
    assert answer.filters.uf == "PR" and answer.trace


def test_dashboard_filters_seed_the_conversation(data, ref):
    a = answer_question("Quantos votos Lula teve?", data, Filters(uf="SP", municipality="61310"))
    assert br(ref.candidate_votes("LULA", "61310")) in a.text


def test_unsupported_year_and_turn_are_explicit(data):
    for question in ["Votos em 2022", "Votos no segundo turno de 2022"]:
        a = answer_question(question, data)
        assert "base" in a.text and not a.trace


@pytest.mark.parametrize("question,expected", [("Qual a evolução histórica?", "apenas os 1º e 2º turnos de 2026"), ("Quem vai ganhar?", "previsões"),
                                               ("Por que o Lula perdeu em Americana?", "explicações causais"), ("Quem ganhou para governador em SP?", "Presidente")])
def test_missing_measure_never_invented(data, question, expected):
    a = answer_question(question, data)
    assert expected in a.text and not a.tables and not a.trace


def test_profile_by_age_in_context(data):
    first = answer_question("E em Campinas?", data, ConversationState.from_filters(Filters(uf="SP", municipality="61310")))
    second = answer_question("Mostre o perfil por idade", data, first.state)
    assert second.filters.municipality == "62910" and "870.672" in second.text and second.tables


def test_ddd_profile(data):
    a = answer_question("Qual o perfil por sexo no DDD 19?", data)
    assert a.filters.ddd == 19 and "4.310.963" in a.text


def test_region_and_exterior(data, ref):
    nordeste = answer_question("Quantos votos Lula teve no Nordeste?", data)
    ufs = ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"]
    assert br(sum(ref.candidate_votes("LULA", uf=uf) for uf in ufs)) in nordeste.text
    exterior = answer_question("Quantos votos Lula teve no exterior?", data)
    assert "no exterior" in exterior.text and exterior.trace[0]["validacao"] == "aprovada"


def test_works_without_optional_candidate_metadata(tmp_path):
    import shutil
    from lampiadim.data import DATA, ElectoralData
    for source in DATA.iterdir():
        if source.name != "candidatos.parquet":
            shutil.copy(source, tmp_path / source.name)
    reduced = ElectoralData(tmp_path)
    assert "37.768" in answer_question("Quantos votos Lula teve em Americana?", reduced).text
    exterior = answer_question("Quantos votos Lula teve no exterior?", reduced)
    assert "não estão na base preparada" in exterior.text and not exterior.trace


def test_candidate_metadata(data):
    assert "Flavio Bolsonaro (PL) e Lula (PT) foram para o 2º turno" in answer_question("Quem foi para o segundo turno?", data).text
    assert "NOVO" in answer_question("Qual o partido do Zema?", data).text
    assert "12 candidaturas" in answer_question("Quantos candidatos disputaram?", data).text


def test_ranking_of_female_electorate(data, ref):
    a = answer_question("Qual o município paulista com o maior eleitorado feminino?", data)
    expected = ref.profile[(ref.profile.SG_UF == "SP") & (ref.profile.DS_GENERO == "FEMININO")].groupby("CD_MUNICIPIO").QT_ELEITORES.sum().max()
    assert br(expected) in a.text and "São Paulo/SP" in a.text and "eleitoras" in a.text


def test_percentage_ranking_top_ten(data, ref):
    a = answer_question("Quais foram os dez municípios paulistas com maior percentual de votos para Lula?", data)
    table = a.tables[0][1]
    sp = ref.votes[ref.votes.SG_UF == "SP"]
    shares = (sp[sp.NM_URNA_CANDIDATO == "LULA"].set_index("CD_MUNICIPIO").VOTOS / sp.groupby("CD_MUNICIPIO").VOTOS.sum()).sort_values(ascending=False)
    assert len(table) == 10 and list(table["% válidos"].round(6)) == list((100 * shares.head(10)).round(6))


# --------------------------------------------------------------------------- contrato com o provedor
def test_provider_tool_call_is_validated_and_numbers_come_from_engine(data, ref, provider):
    with patch("lampiadim.llm.httpx.post", return_value=model_response(votes_call(["Lula"]))) as post:
        a = answer_question("Lula em Americana, quanto?", data)
    body = post.call_args.kwargs["json"]
    assert body["store"] is False and body["tool_choice"] == "required" and all(t["strict"] for t in body["tools"])
    assert "37.768" not in json.dumps(body) and "votos" not in json.loads(body["input"]).get("contexto", {})
    assert a.mode == "IA · consulta verificada" and br(ref.candidate_votes("LULA", "61310")) in a.text


def test_provider_cannot_introduce_unknown_candidate(data, provider):
    with patch("lampiadim.llm.httpx.post", return_value=model_response(votes_call(["Candidato Inventado"]))):
        a = answer_question("Quantos votos o candidato inventado teve em Americana?", data)
    assert "Não há candidatura" in a.text and not a.trace


def test_provider_followup_uses_structured_context(data, ref, provider):
    first = answer_question("Quantos votos Lula teve em Campinas?", data)  # local, sem provedor configurado no estado
    call = ("continuar_consulta_anterior", {"candidatos": ["Bolsonaro"], "referencia_candidato": "", "territorios": [], "referencia_lugar": "", "ano": None, "turno": None, "metrica": "", "correcao": False})
    with patch("lampiadim.llm.httpx.post", return_value=model_response(call)) as post:
        a = answer_question("E Bolsonaro?", data, first.state)
    context = json.loads(post.call_args.kwargs["json"]["input"])["contexto"]
    assert context["candidaturas_em_foco"] == ["LULA"] and "pergunta" not in context
    assert br(ref.candidate_votes("FLAVIO BOLSONARO", "62910")) in a.text


def test_provider_failure_falls_back_without_leaking_secret(data, provider, ref):
    with patch("lampiadim.llm.httpx.post", side_effect=httpx.ConnectError("secret-failure")):
        a = answer_question("Votos válidos em Americana/SP", data)
    assert "IA indisponível" in a.mode and br(ref.valid("61310")) in a.text and "secret" not in a.text


def test_provider_incomplete_or_invalid_output_falls_back(data, provider):
    for response in [model_response(votes_call(["Lula"]), status="incomplete"), model_response(("ferramenta_inexistente", {}))]:
        with patch("lampiadim.llm.httpx.post", return_value=response):
            a = answer_question("Quantos votos Lula teve em Americana?", data)
        assert "IA indisponível" in a.mode and "37.768" in a.text


def test_guards_run_before_provider(data, provider):
    with patch("lampiadim.llm.httpx.post") as post:
        a = answer_question("Quantas mulheres votaram em Lula?", data)
    assert not post.called and a.text.startswith("Não é possível determinar.")


def test_local_geographic_ambiguity_prevails_over_model_choice(data, provider):
    city = ("consultar_resultado_territorial", {"territorios": [{"tipo": "municipio", "nome": "São Paulo", "uf": "SP"}], "referencia_lugar": "", "ano": None, "turno": None,
                                                "tipo": "vencedor", "posicao": None, "candidato_verificado": None})
    with patch("lampiadim.llm.httpx.post", return_value=model_response(city)):
        a = answer_question("Quem ganhou em São Paulo?", data)
    assert a.clarification and "estado de São Paulo" in a.text


def test_model_limitation_tool(data, provider):
    call = ("informar_limitacao", {"motivo": "inferencia_demografica", "atributo": "a escolaridade"})
    with patch("lampiadim.llm.httpx.post", return_value=model_response(call)):
        a = answer_question("Os universitários preferiram quem?", data)
    assert "não identificam a escolaridade" in a.text and not a.trace
