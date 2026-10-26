"""Orquestração do Lampiadim: compreender → estruturar → validar → consultar → verificar → responder.

1. Interpretação semântica (modelo de linguagem opcional ou intérprete local).
2. Frame estruturado combinado ao contexto da conversa (planner).
3. Validação dos parâmetros contra a base (tools.validate).
4. Execução determinística no motor estatístico (engine).
5. Verificação estatística do resultado (verification).
6. Resposta mínima suficiente, com origem conferida de cada número (responses).

O modelo de linguagem só interpreta: os números vêm sempre das bases locais.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
import re

import httpx

from .context import ConversationState
from .data import Filters
from .engine import DataUnavailable, engine_for
from .interpreter import Interpreter, split_clauses
from .llm import ModelInterpreter, provider_enabled
from .planner import Planner, Reply
from .responses import render, render_reply
from .tools import QueryError, execute
from .verification import VerificationError, verify_grounded_text

LOG = logging.getLogger("lampiadim.assistente")
MAX_QUESTION = 2000
ATTACK = re.compile(r"<\s*/?\s*(script|iframe|img|svg)\b|javascript:|\bdrop\s+table\b|\bdelete\s+from\b|\binsert\s+into\b|\bunion\s+select\b"
                    r"|\bselect\s+[\w*,\s]+\s+from\b|;\s*--|\bupdate\s+\w+\s+set\b|\bexec\s*\(|\bos\.system\b|\bimport\s+os\b", re.I)
# Limitações decididas pelo intérprete local valem mesmo com o modelo habilitado.
GUARDED = {"limitacao", "fora_escopo"}

__all__ = ["Answer", "answer_question", "provider_enabled", "ConversationState"]


@dataclass
class Answer:
    text: str
    filters: Filters
    tables: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    mode: str = "Consulta local"
    clarification: bool = False
    state: ConversationState | None = None
    trace: list = field(default_factory=list)


def _components(engine):
    parts = getattr(engine, "_lampiadim_components", None)
    if parts is None:
        interpreter = Interpreter(engine)
        parts = (interpreter, Planner(engine), ModelInterpreter(engine, interpreter))
        engine._lampiadim_components = parts
    return parts


def _filters(state, kb):
    """Filtros equivalentes do painel para exibir o contexto da conversa."""
    base = state.base
    period = state.period if state.period in kb.periods else (base.year, base.turn)
    territory = state.territories[0] if state.territories else None
    geo = {"uf": base.uf, "municipality": base.municipality, "ddd": base.ddd} if territory is None else {"uf": "", "municipality": "", "ddd": None}
    if territory is not None and territory.kind == "municipio":
        geo = {"uf": territory.uf, "municipality": territory.code, "ddd": None}
    elif territory is not None and territory.kind == "uf":
        geo["uf"] = territory.code
    elif territory is not None and territory.kind == "ddd":
        geo["ddd"] = int(territory.code)
    candidate = state.candidates[0] if len(state.candidates) == 1 else ""
    return Filters(year=period[0], turn=period[1], candidate=candidate, **geo)


def _sources(trace):
    return [f"Fonte: {trace['fonte']} · {trace['versao']}",
            f"Métrica: {trace['metrica']} · denominador: {trace['denominador']}",
            "Filtros: " + (", ".join(f"{k}: {v}" for k, v in trace["filtros"].items()) or "nenhum") + (f" · ano {trace['ano']}" if trace.get("ano") else "") + (f", {trace['turno']}º turno" if trace.get("turno") else ""),
            f"Registros processados: {trace['registros']} · validação: {trace['validacao']}"]


def answer_question(question, data, context=None):
    """Responde a uma mensagem. ``context`` é o ConversationState da conversa (ou Filters do painel)."""
    state = context if isinstance(context, ConversationState) else ConversationState.from_filters(context or Filters())
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
        return Answer("Escreva uma pergunta de até 2.000 caracteres.", state.base, clarification=True, state=state)
    try:
        engine = engine_for(data)
    except DataUnavailable:
        LOG.error("base indisponível")
        return Answer("Não consegui acessar a base de dados eleitorais agora. Nenhum número foi apresentado.", state.base, clarification=True, state=state, mode="Base indisponível")
    interpreter, planner, model = _components(engine)
    kb = engine.kb
    if ATTACK.search(question):
        # Comandos SQL ou marcação executável não são perguntas: nada é interpretado nem consultado.
        LOG.warning("entrada recusada")
        return Answer(render_reply(kb, Reply("limitacao", "injecao")), _filters(state, kb), state=state)
    mode = "Consulta local"
    texts, tables, sources, traces = [], [], [], []
    clarification = False

    pending_frame = planner.resolve_pending(question, state)
    queue = [pending_frame] if pending_frame else None
    if queue is None and provider_enabled():
        local = [interpreter.interpret(clause, state) for clause in split_clauses(question)]
        if any(f.intent in GUARDED for f in local):
            queue = local
        else:
            try:
                queue = model.frames(question, state)
                mode = "IA · consulta verificada"
                # Ambiguidade geográfica detectada localmente prevalece sobre uma escolha do modelo.
                guards = [f for f in local if f.intent == "problema" and f.reason in {"estado_ou_municipio", "municipio_homonimo"}]
                if guards:
                    queue = guards
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                LOG.warning("interpretação externa indisponível", extra={"erro": type(exc).__name__})
                mode = "Consulta local · IA indisponível nesta resposta"
                queue = None
    clauses = split_clauses(question) if queue is None else [None] * len(queue)

    for index, clause in enumerate(clauses):
        frame = interpreter.interpret(clause, state) if queue is None else queue[index]
        decision, frame = planner.ground(frame, state)
        if isinstance(decision, Reply):
            texts.append(render_reply(kb, decision))
            new = planner.remember(state, frame, clarifying=decision.kind == "esclarecimento")
            state = replace(new, pending=decision.pending)
            if decision.kind == "esclarecimento":
                clarification = True
                break
            continue
        try:
            result = execute(engine, decision)
            rendered = render(kb, decision, result, frame, engine)
            verify_grounded_text(rendered.text, rendered.allowed)
        except QueryError as exc:
            texts.append(render_reply(kb, Reply("limitacao", exc.code, exc.details)))
            state = planner.remember(state, frame)
            continue
        except VerificationError as exc:
            LOG.error("verificação reprovada", extra={"ferramenta": decision.tool, "motivo": str(exc)})
            texts.append(render_reply(kb, Reply("limitacao", "verificacao")))
            continue
        except DataUnavailable:
            texts.append(render_reply(kb, Reply("limitacao", "dados_indisponiveis")))
            mode = "Base indisponível"
            break
        texts.append(rendered.text)
        tables.extend(rendered.tables)
        traces.append(result.trace)
        sources.extend(_sources(result.trace))
        state = planner.remember(state, frame, decision, result, decision.period, explicit=bool(frame.year or frame.turn) or state.period_explicit)
    text = "\n\n".join(t for t in texts if t) or render_reply(kb, Reply("conversa", "desconhecido"))
    return Answer(text, _filters(state, kb), tables, sources, mode, clarification, state, traces)
