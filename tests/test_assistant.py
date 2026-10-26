import json
from unittest.mock import patch
import httpx
import pytest
from lampiadim.assistant import answer_question, local_plan, model_plan
from lampiadim.data import Filters


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)


def test_americana_response_grounded_in_data(data):
    a = answer_question("Compare os votos de Lula e Bolsonaro em Americana/SP", data)
    assert a.filters.municipality == "61310"
    assert "37.768" in a.text and "86.854" in a.text and "49.086" in a.text
    assert len(a.tables[0][1]) == 2 and len(a.sources) == 2


def test_state_not_confused_with_capital(data):
    a = answer_question("Qual a votação no estado de São Paulo?", data)
    assert a.filters.uf == "SP" and not a.filters.municipality
    assert "34.104.226" in a.text


def test_homonym_requires_state(data):
    a = answer_question("Qual o resultado de Santa Helena?", data)
    assert a.clarification and "MA, PB, PR, SC" in a.text and not a.tables


def test_explicit_state_resolves_homonym(data):
    a = answer_question("Qual o resultado de Santa Helena/PR?", data)
    assert not a.clarification and a.filters.uf == "PR"


def test_unknown_city_is_not_replaced_with_brazil(data):
    a = answer_question("Quem recebeu mais votos em Atlantis?", data)
    assert a.clarification and not a.tables


def test_secret_vote_not_inferred(data):
    a = answer_question("Quantas mulheres votaram em Lula em Americana/SP?", data)
    assert "Não é possível atribuir votos" in a.text
    assert "95.958" in a.text and "37.768" in a.text


def test_unsupported_year_and_turn_are_explicit(data):
    assert answer_question("Votos em 2022", data).clarification
    assert answer_question("Votos no segundo turno", data).clarification


@pytest.mark.parametrize("question,expected", [("Qual a abstenção?", "não estão"), ("Qual a evolução histórica?", "somente 2026"), ("Quem vai ganhar?", "prever resultados")])
def test_missing_measure_never_invented(data, question, expected):
    a = answer_question(question, data)
    assert expected in a.text and not a.tables


def test_context_and_geographic_change(data):
    a = answer_question("E em Campinas?", data, Filters(uf="SP", municipality="61310"))
    assert a.filters.municipality == "62910"
    b = answer_question("Mostre o perfil por idade", data, a.filters)
    assert b.filters.municipality == "62910" and "870.672" in b.text


def test_territorial_comparison(data):
    a = answer_question("Compare Americana e Campinas", data)
    assert len(a.tables[0][1]) == 2
    assert a.tables[0][1]["Votos válidos"].tolist() == [136589, 633220]


def test_ddd_query(data):
    a = answer_question("Qual o perfil por sexo no DDD 19?", data)
    assert a.filters.ddd == 19 and "4.310.963" in a.text


def test_city_word_is_not_age_intent(data):
    p = local_plan("Qual o resultado da cidade de Americana?", data)
    assert p["dimension"] == ""


def test_provider_failure_falls_back_without_leaking_secret(data, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-never-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    with patch("lampiadim.assistant.httpx.post", side_effect=httpx.ConnectError("secret-failure")):
        a = answer_question("Votos em Americana/SP", data)
    assert "IA indisponível" in a.mode and "136.589" in a.text and "secret" not in a.text


def test_provider_contract_uses_server_calculations(data, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-never-a-real-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    plan = local_plan("Votos em Americana/SP", data)
    response = httpx.Response(200, request=httpx.Request("POST", "https://api.openai.com/v1/responses"), json={"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(plan)}]}]})
    with patch("lampiadim.assistant.httpx.post", return_value=response) as post:
        a = answer_question("Votos em Americana/SP", data)
        assert post.call_args.kwargs["json"]["store"] is False
    assert a.mode == "IA · consulta verificada" and "136.589" in a.text
