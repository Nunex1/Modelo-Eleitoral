"""Avaliação contínua do Lampiadim sobre o conjunto de perguntas de referência.

Mede separadamente intenção, entidades, consulta, exatidão numérica, contexto,
disciplina de resposta, controle de alucinação, ambiguidade, desempenho e
resiliência. Os números esperados vêm de consultas de referência independentes
(tests/referencia.py); nenhuma avaliação depende do julgamento de um modelo.

    .\\.venv\\Scripts\\python.exe scripts\\avaliar_lampiadim.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Lampiadim_MVP"))
sys.path.insert(0, str(ROOT / "tests"))
from lampiadim.assistant import ConversationState, answer_question  # noqa: E402
from lampiadim.data import ElectoralData, Filters  # noqa: E402
from lampiadim.engine import Engine  # noqa: E402
from referencia import Reference  # noqa: E402

CASES = ROOT / "tests/avaliacao/referencias.json"
DIMENSIONS = ["intencao", "entidades", "consulta", "exatidao_numerica", "contexto", "disciplina", "controle_alucinacao", "ambiguidade", "resiliencia"]


def statistical_numbers(text):
    return re.findall(r"\d", re.sub(r"\b20\d{2}\b|\b[12]º", "", text)) or ("%" in text and ["%"])


def evaluate(data=None, cases_path=CASES):
    os.environ.pop("OPENAI_API_KEY", None)
    data = data or ElectoralData()
    ref = Reference()
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    scores = {d: [] for d in DIMENSIONS}
    latencies, details = [], []
    for case in cases:
        expected = case["esperado"]
        state = ConversationState.from_filters(Filters())  # contexto da interface: 1º turno selecionado
        for question in case["conversa"]:
            started = time.perf_counter()
            answer = answer_question(question, data, state)
            latencies.append(1000 * (time.perf_counter() - started))
            state = answer.state
        trace = answer.trace[-1] if answer.trace else {}
        failures = []

        def score(dimension, ok, why):
            scores[dimension].append(bool(ok))
            if not ok:
                failures.append(f"{dimension}: {why}")

        if "ferramenta" in expected:
            score("intencao", trace.get("ferramenta") == expected["ferramenta"], f"{trace.get('ferramenta')} ≠ {expected['ferramenta']}")
        if any(k in expected for k in ["candidaturas", "territorios", "escopo", "ano", "turno"]):
            filters = trace.get("filtros", {})
            ok = all([sorted(filters.get("candidaturas", [])) == sorted(expected["candidaturas"]) if "candidaturas" in expected else True,
                      filters.get("territorios") == expected["territorios"] if "territorios" in expected else True,
                      filters.get("escopo") == expected["escopo"] if "escopo" in expected else True,
                      trace.get("ano") == expected["ano"] if "ano" in expected else True,
                      trace.get("turno") == expected["turno"] if "turno" in expected else True])
            score("entidades", ok, json.dumps(filters, ensure_ascii=False))
            if len(case["conversa"]) > 1:
                score("contexto", ok, "filtros herdados incorretamente")
        if "referencia" in expected:
            score("consulta", trace.get("validacao", "").startswith("aprovada") and bool(trace.get("fonte")), trace.get("validacao"))
            numbers = ref.expected(expected["referencia"])
            score("exatidao_numerica", all(n in answer.text for n in numbers), f"esperado {numbers}")
        if "max_frases" in expected:
            sentences = len([s for s in re.split(r"(?<=[.!?])\s+", answer.text) if s.strip()])
            score("disciplina", sentences <= expected["max_frases"] + (1 if expected.get("contem") == "Não." else 0) and not answer.tables, f"{sentences} frases, {len(answer.tables)} tabelas")
        if "contem" in expected:
            score("disciplina", expected["contem"] in answer.text, f"sem '{expected['contem']}'")
        if expected.get("sem_numeros"):
            score("controle_alucinacao", not statistical_numbers(answer.text) and not answer.trace, answer.text)
        elif answer.trace:
            # Toda resposta numérica precisa ter consulta executada e verificada.
            score("controle_alucinacao", all(t["validacao"].startswith("aprovada") for t in answer.trace), "consulta sem validação")
        if "esclarecimento" in expected:
            score("ambiguidade", answer.clarification == expected["esclarecimento"], f"esclarecimento={answer.clarification}")
        details.append({"id": case["id"], "ok": not failures, "falhas": failures, "resposta": answer.text})

    # Resiliência: falha simulada do motor nunca produz números.
    def broken(*args, **kwargs):
        raise OSError("falha simulada")
    with patch.object(Engine, "result", broken):
        for question in ["Quantos votos Lula teve em Americana?", "Quem ganhou em Campinas?"]:
            answer = answer_question(question, data)
            scores["resiliencia"].append(not statistical_numbers(answer.text) and "Não consegui consultar" in answer.text)
    answer = answer_question("Quantos votos Lula teve em Americana?", None)
    scores["resiliencia"].append(not statistical_numbers(answer.text))

    summary = {d: {"acertos": sum(v), "total": len(v), "taxa": round(100 * sum(v) / len(v), 1) if v else None} for d, v in scores.items()}
    latencies.sort()
    summary["desempenho_ms"] = {"mediana": round(statistics.median(latencies), 1), "p95": round(latencies[int(0.95 * (len(latencies) - 1))], 1), "maximo": round(latencies[-1], 1)}
    return {"casos": len(cases), "resumo": summary, "detalhes": details}


def main():
    result = evaluate()
    out = ROOT / "resultados"
    out.mkdir(exist_ok=True)
    (out / "avaliacao-lampiadim.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Avaliação do Lampiadim", "", f"Casos de referência: {result['casos']}. Valores esperados calculados por consultas de referência independentes.", "",
             "| Dimensão | Acertos | Total | Taxa |", "|---|---|---|---|"]
    for name in DIMENSIONS:
        s = result["resumo"][name]
        lines.append(f"| {name.replace('_', ' ')} | {s['acertos']} | {s['total']} | {s['taxa']}% |")
    perf = result["resumo"]["desempenho_ms"]
    lines += ["", f"Desempenho (ms por pergunta): mediana {perf['mediana']}, p95 {perf['p95']}, máximo {perf['maximo']}.", ""]
    failed = [d for d in result["detalhes"] if not d["ok"]]
    lines += (["## Falhas", ""] + [f"- `{d['id']}`: {'; '.join(d['falhas'])}" for d in failed]) if failed else ["Nenhuma falha no conjunto de referência."]
    (out / "avaliacao-lampiadim.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
