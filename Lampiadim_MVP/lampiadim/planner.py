"""Combina a interpretação com o contexto e decide: consultar, esclarecer ou informar um limite.

Situação A (pergunta clara): executa. Situação B (falta algo recuperável do
contexto ou dos filtros do painel): completa sem interromper. Situação C
(ambiguidade que muda o resultado): pede o menor esclarecimento possível e
guarda a consulta pendente para a resposta seguinte.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .data import normalize
from .entities import BRASIL
from .language import tokenize
from .tools import Plan

CANDIDATE_INTENTS = {"votos", "comparar_candidatos", "vitorias"}


@dataclass
class Reply:
    """Resposta sem consulta numérica: esclarecimento, limitação ou conversa."""
    kind: str                 # esclarecimento | limitacao | conversa
    code: str
    detail: dict = field(default_factory=dict)
    pending: dict | None = None


class Planner:
    def __init__(self, engine):
        self.engine = engine
        self.kb = engine.kb

    # ------------------------------------------------------------------ pendências
    def resolve_pending(self, text, state):
        """Se a mensagem responde ao esclarecimento pendente, devolve o Frame completado."""
        pending = state.pending
        if not pending:
            return None
        words = {t.norm for t in tokenize(text)}
        if len(words) > 8:
            return None
        frame = replace(pending["frame"], detail=dict(pending["frame"].detail))
        options, field_ = pending.get("options", []), pending["field"]
        chosen = None
        yes = bool(words & {"SIM", "ISSO", "ESSE", "ESSA", "ELE", "ELA", "PODE", "OK", "CERTO", "EXATO", "CONFIRMO"})
        if field_ == "territorio":
            if words & {"ESTADO", "UF"}:
                chosen = next((o for o in options if o.kind == "uf"), None)
            elif words & {"CIDADE", "MUNICIPIO", "CAPITAL"}:
                cities = [o for o in options if o.kind == "municipio"]
                ufs = words & set(self.kb.states)
                cities = [c for c in cities if not ufs or c.uf in ufs]
                chosen = cities[0] if len(cities) == 1 else None
        elif field_ == "uf":
            ufs = (words & set(self.kb.states)) | {uf for uf, name in self.kb.states.items() if normalize(name) in " ".join(sorted(words))}
            narrowed = [o for o in options if o.uf in ufs]
            chosen = narrowed[0] if len(narrowed) == 1 else (options[0] if yes and len(options) == 1 else None)
        elif field_ == "candidato":
            mentions = [m.values[0] for m in self.kb.scan(tokenize(text)) if m.kind == "candidato" and len(m.values) == 1]
            chosen = next((c for c in mentions if c in options or not options), None) or (options[0] if yes and len(options) == 1 else None)
        elif field_ in {"ano", "turno"}:
            numbers = [int(w[:-1]) if w[:-1].isdigit() and w[-1] in "OA" else int(w) for w in words if w.isdigit() or (w[:-1].isdigit() and w[-1] in "OA")]
            numbers += [1] if words & {"PRIMEIRO", "PRIMEIRA"} else [2] if words & {"SEGUNDO", "SEGUNDA"} else []
            chosen = next((n for n in numbers if n in options), None)
        elif field_ == "categoria":
            chosen = "INCOMPLETO" in words and next((o for o in options if "INCOMPLETO" in normalize(o)), None) or \
                "COMPLETO" in words and next((o for o in options if "INCOMPLETO" not in normalize(o)), None) or None
        elif field_ == "dimensao":
            chosen = "identidade" if "IDENTIDADE" in words else "escolaridade" if words & {"ESCOLARIDADE", "INSTRUCAO"} else \
                "idade" if words & {"IDADE", "ETARIA", "FAIXA"} else "sexo" if words & {"SEXO", "GENERO"} else None
        elif field_ == "metrica":
            chosen = "percentual_candidato" if words & {"PERCENTUAL", "PROPORCAO", "PROPORCIONAL"} else \
                "votos_candidato" if words & {"VOTOS", "ABSOLUTO", "ABSOLUTOS", "QUANTIDADE", "NUMERO", "TOTAL"} else None
        elif field_ == "periodo":
            turns = {1} if words & {"PRIMEIRO", "1O", "1"} else {2} if words & {"SEGUNDO", "2O", "2"} else set()
            chosen = next((o for o in options if (yes and not turns) or o[1] in turns), None)
        if chosen is None:
            return None
        frame.intent, frame.reason = pending["intent"], ""
        if field_ in {"territorio", "uf"}:
            frame.territories = [t for t in frame.territories if t != chosen] + [chosen]
        elif field_ == "candidato":
            frame.candidates = list(dict.fromkeys(list(frame.candidates) + [chosen]))
        elif field_ == "ano":
            frame.year = chosen
        elif field_ == "turno":
            frame.turn = chosen
        elif field_ == "periodo":
            frame.year, frame.turn = chosen
        elif field_ == "categoria":
            frame.categories = {**frame.categories, "escolaridade": (chosen,)}
        elif field_ == "dimensao":
            if pending.get("category"):
                value = next((v for v in self.engine.data.categories[chosen] if normalize(v) == "NAO INFORMADO"), None)
                if value:
                    frame.categories = {**frame.categories, chosen: (value,)}
            frame.dimension = chosen
        elif field_ == "metrica":
            frame.metric = chosen
        return frame

    def _ask(self, code, frame, intent, field_, options=(), **detail):
        return Reply("esclarecimento", code, {**detail, "options": list(options)},
                     pending={"frame": frame, "intent": intent, "field": field_, "options": list(options), **({"category": True} if code == "categoria_sem_dimensao" else {})})

    # ------------------------------------------------------------------ problemas de entidade
    def _problem(self, frame, state):
        code = frame.reason
        intent = frame.detail.get("intent") or "votos"
        detail = {k: v for k, v in frame.detail.items() if k not in {"intent", "unavailable_dimension", "vague_age", "person_mentioned"}}
        if code == "estado_ou_municipio":
            return self._ask(code, frame, intent, "territorio", detail["options"], text=detail["text"])
        if code == "municipio_homonimo":
            return self._ask(code, frame, intent, "uf", detail["options"], text=detail["text"])
        if code == "municipio_fora_da_uf":
            return self._ask(code, frame, intent, "uf", self.kb.cities.get(normalize(detail["text"]), []), **detail)
        if code == "candidato_ambiguo":
            return self._ask(code, frame, intent, "candidato", detail["options"], text=detail["text"])
        if code == "candidato_inexistente":
            words = set(normalize(detail["text"]).split())
            similar = [c.key for c in self.kb.candidates.values() if words & (set(normalize(c.key).split()) | set(normalize(c.full_name).split())) - {"DA", "DE", "DO", "DOS", "DAS"}]
            if len(similar) == 1:
                return self._ask(code, frame, intent, "candidato", similar, text=detail["text"], similar=similar[0])
            return Reply("limitacao", code, {"text": detail["text"]})
        if code == "escolaridade_ambigua":
            return self._ask(code, frame, intent, "categoria", detail["options"])
        if code == "categoria_sem_dimensao":
            return self._ask(code, frame, intent, "dimensao", ["sexo", "identidade", "escolaridade"])
        if code == "partido_incompativel":
            candidate = self.kb.candidates[detail["candidate"]]
            return Reply("esclarecimento", code, {"candidate": candidate, "party": detail["party"]})
        if code == "anos_multiplos":
            missing = [y for y in detail["years"] if y not in {p[0] for p in self.kb.periods}]
            return Reply("limitacao", "periodo_indisponivel" if missing else "serie_historica", {"years": detail["years"]})
        return Reply("limitacao", code, detail)

    # ------------------------------------------------------------------ período
    def _period(self, frame, state, candidates, intent):
        periods = list(self.kb.periods)
        if candidates:
            shared = set.intersection(*(set(self.kb.candidates[c].periods) for c in candidates))
            periods = sorted(shared) or periods
        year = frame.year or (state.period[0] if state.period and (state.period_explicit or frame.followup or frame.correction) else None)
        if year is None and state.period and len({p[0] for p in self.kb.periods}) == 1:
            year = state.period[0]
        turn = frame.turn
        if turn is None and state.period and year == state.period[0] and (state.period_explicit or frame.followup or frame.correction):
            turn = state.period[1]
        explicit = bool(frame.year or frame.turn) or state.period_explicit
        if year is None:
            years = sorted({p[0] for p in periods})
            if len(years) > 1:
                return None, self._ask("ano", frame, intent, "ano", years), explicit
            year = years[0]
        if turn is None:
            turns = sorted({p[1] for p in periods if p[0] == year})
            if len(turns) > 1:
                return (year, None), self._ask("turno", frame, intent, "turno", turns, year=year), explicit
            turn = turns[0] if turns else (frame.turn or 1)
        period = (year, turn)
        if period not in self.kb.periods:
            same_year = [p for p in self.kb.periods if p[0] == year]
            alternative = same_year[:1] if len(same_year) == 1 else self.kb.periods[-1:] if len(self.kb.periods) == 1 else []
            pending = {"frame": frame, "intent": intent, "field": "periodo", "options": alternative} if alternative else None
            return period, Reply("limitacao", "periodo_indisponivel", {"period": period, "alternative": alternative[0] if alternative else None}, pending), explicit
        if candidates and any(period not in self.kb.candidates[c].periods for c in candidates):
            missing = [c for c in candidates if period not in self.kb.candidates[c].periods]
            return period, Reply("limitacao", "candidato_fora_do_pleito", {"candidate": missing[0], "period": period}), explicit
        return period, None, explicit

    # ------------------------------------------------------------------ território
    def base_territory(self, state):
        base = state.base
        if base.municipality in self.kb.city_by_code:
            return self.kb.city_by_code[base.municipality]
        if base.ddd:
            return self.kb.ddd(base.ddd)
        if base.uf:
            return self.kb.state(base.uf)
        return None

    def _territories(self, frame, state, intent):
        if frame.territories:
            return list(frame.territories)
        if frame.place_ref == "par" and len(state.recent_places) >= 2:
            return list(state.recent_places[-2:])
        if state.territories:
            return list(state.territories[:1]) if intent != "comparar_territorios" else list(state.territories)
        base = self.base_territory(state)
        return [base] if base else [BRASIL]

    # ------------------------------------------------------------------ fundamento da consulta
    def ground(self, frame, state):
        """Devolve (Plan | Reply, Frame efetivo)."""
        if frame.intent in {"saudacao", "agradecimento", "ajuda", "fora_escopo", "desconhecido"}:
            return Reply("conversa", frame.intent), frame
        if frame.intent == "limitacao":
            return Reply("limitacao", frame.reason, frame.detail), frame
        if frame.intent == "problema":
            return self._problem(frame, state), frame
        years = {p[0] for p in self.kb.periods}
        if frame.intent not in {"eleitorado", "distribuicao", "contar_municipios", "candidaturas"} and (frame.year or frame.turn):
            year = frame.year or (state.period[0] if state.period else max(years))
            if year not in years or (frame.turn and (year, frame.turn) not in self.kb.periods):
                # Período pedido explicitamente e inexistente: informar antes de qualquer outra interpretação.
                period = (year, frame.turn or 1)
                same_year = [p for p in self.kb.periods if p[0] == year] or self.kb.periods[-1:]
                pending = {"frame": frame, "intent": frame.intent if frame.intent not in {"continuar"} else (state.intent or "resultado"), "field": "periodo", "options": same_year[:1]}
                return Reply("limitacao", "periodo_indisponivel", {"period": period, "alternative": same_year[0]}, pending), frame
        intent = frame.intent
        if intent == "comparar":
            if len(state.recent) >= 2:
                intent, frame.candidates, frame.metric = "comparar_candidatos", list(state.recent[-2:]), "mais_votos"
            elif len(state.recent_places) >= 2:
                intent, frame.territories = "comparar_territorios", list(state.recent_places[-2:])
            else:
                return Reply("esclarecimento", "comparar_o_que"), frame
        if intent == "continuar":
            intent = state.intent or ("votos" if frame.candidates else "resultado" if frame.territories else "")
            if not intent:
                return Reply("esclarecimento", "pergunta_incompleta" if not frame.metric else "percentual_de_que"), frame
            if not frame.metric and intent == state.intent:
                frame.metric = state.metric
            if intent == "comparar_candidatos" and frame.metric in {"votos", "percentual"}:
                frame.metric = {"votos": "diferenca_votos", "percentual": "diferenca_pp"}[frame.metric]
            if intent == "comparar_candidatos" and len(frame.candidates) == 1 and frame.followup and not frame.candidate_ref:
                intent = "votos"
            if intent in {"ranking", "vitorias"}:
                frame.limit = frame.limit or state.limit
                frame.position = frame.position or state.position
                frame.order = frame.order or state.order
                frame.level = frame.level or state.level
                if frame.metric == "percentual" and state.metric == "votos_candidato":
                    frame.metric = "percentual_candidato"
                elif frame.metric == "votos" and state.metric == "percentual_candidato":
                    frame.metric = "votos_candidato"
                elif frame.metric not in {"votos_candidato", "percentual_candidato", "votos_validos", "eleitores", "percentual_eleitores"}:
                    frame.metric = state.metric
            if intent in {"eleitorado", "distribuicao"}:
                frame.categories = frame.categories or dict(state.categories)
                frame.dimension = frame.dimension or state.dimension
            if intent == "vencedor":
                frame.position = frame.position or state.position or 1
        frame.intent = intent

        # Candidaturas -------------------------------------------------------
        candidates = list(frame.candidates)
        if not candidates and frame.candidate_ref == "foco":
            if not state.candidates:
                return Reply("esclarecimento", "candidato_ausente"), frame
            candidates = list(state.candidates[-1:])
        elif not candidates and frame.candidate_ref == "par":
            if len(state.recent) < 2:
                return Reply("esclarecimento", "par_ausente"), frame
            candidates = list(state.recent[-2:])
        elif len(candidates) == 1 and frame.candidate_ref == "par" and state.recent:
            candidates = list(dict.fromkeys([k for k in state.recent if k not in candidates][-1:] + candidates))
        elif not candidates and frame.candidate_ref in {"vencedor", "top2"}:
            candidates = []
        elif not candidates and state.candidates and intent == "comparar_territorios":
            # Mantém a métrica da consulta anterior apenas quando ela tratava de uma única candidatura.
            if len(state.candidates) == 1 and state.intent in {"votos", "comparar_territorios"} and frame.metric != "geral":
                candidates = list(state.candidates)
        elif not candidates and state.candidates and (intent in CANDIDATE_INTENTS | {"ranking"}) and (frame.followup or frame.correction or frame.intent == state.intent):
            if intent != "ranking" or state.metric in {"votos_candidato", "percentual_candidato"} or frame.metric in {"votos_candidato", "percentual_candidato"}:
                candidates = list(state.candidates)
        if intent == "comparar_candidatos" and len(candidates) == 1:
            other = [k for k in state.recent if k not in candidates]
            if frame.followup and other:
                candidates = [other[-1]] + candidates
            else:
                return self._ask("parceiro_comparacao", frame, intent, "candidato", [], candidate=candidates[0]), frame
        if intent == "comparar_candidatos" and not candidates and frame.candidate_ref != "top2":
            if state.intent in {"vencedor", "resultado", "comparar_candidatos"} or state.leaders:
                frame.candidate_ref = "top2"
            else:
                return Reply("esclarecimento", "par_ausente"), frame
        if intent == "votos" and not candidates and frame.candidate_ref in {"vencedor", "top2"}:
            intent, frame.position = "vencedor", 1
            frame.metric = frame.metric or "votos"
        if intent == "votos" and not candidates:
            return Reply("esclarecimento", "candidato_ausente"), frame
        if intent in {"ranking"} and frame.metric in {"votos_candidato", "percentual_candidato"} and not candidates:
            return Reply("esclarecimento", "candidato_ausente"), frame
        if intent == "ranking" and frame.reason == "metrica_ranking":
            return self._ask("metrica_ranking", frame, intent, "metrica", ["votos_candidato", "percentual_candidato"]), frame
        if intent == "vitorias" and len(candidates) != 1:
            return Reply("esclarecimento", "candidato_ausente"), frame

        # Período -----------------------------------------------------------
        profile_intent = intent in {"eleitorado", "distribuicao", "contar_municipios"} or (intent == "ranking" and frame.metric in {"eleitores", "percentual_eleitores"})
        if profile_intent:
            year = frame.year or self.engine.profile_years[-1]
            if year not in self.engine.profile_years:
                return Reply("limitacao", "cadastro_indisponivel", {"year": year}), frame
            period, explicit = None, bool(frame.year) or state.period_explicit
            if frame.turn == 2 and intent != "contar_municipios":
                period = None  # o cadastro não depende do turno
        else:
            if intent == "candidaturas":
                frame.turn = 1 if frame.metric == "segundo_turno" else frame.turn
            period, problem, explicit = self._period(frame, state, candidates, intent)
            if problem:
                return problem, replace(frame, year=period[0] if period else frame.year, turn=period[1] if period else frame.turn)

        # Território --------------------------------------------------------
        territories = self._territories(frame, state, intent) if intent not in {"ranking", "vitorias", "candidaturas"} else list(frame.territories)
        frame.territories = territories
        frame.candidates = candidates
        if intent == "candidaturas":
            return Plan("consultar_candidaturas", period, tuple(candidates), metric=frame.metric), frame
        if intent in {"ranking", "vitorias"}:
            scope = next((t for t in territories if t.kind in {"brasil", "regiao", "uf", "ddd"}), None)
            if territories and scope is None:
                return Reply("limitacao", "ranking_em_municipio", {"territory": territories[0]}), frame
            if scope is None:
                base = self.base_territory(state)
                scope = state.scope if frame.followup and state.scope else (base if base and base.kind != "municipio" else BRASIL)
            if (frame.level or "municipio") == "uf" and scope.kind not in {"brasil", "regiao"}:
                scope = BRASIL  # ranking de estados só faz sentido no país ou numa região
            frame.territories = [scope]
            if intent == "vitorias":
                return Plan("contar_vitorias", period, tuple(candidates), scope=scope, level=frame.level or "municipio"), frame
            categories = {k: v for k, v in frame.categories.items() if v}
            return Plan("gerar_ranking_municipal", period, tuple(candidates[:1]), scope=scope, metric=frame.metric or "votos_validos", categories=categories,
                        limit=frame.limit or (None if frame.position else 1), position=frame.position, order=frame.order or "desc", level=frame.level or "municipio"), frame
        territory = territories[0]
        if intent == "contar_municipios":
            return Plan("contar_municipios", None, territories=(territory,)), frame
        if intent == "eleitorado":
            return Plan("consultar_eleitorado", None, territories=(territory,), categories={k: v for k, v in frame.categories.items() if v}, metric=frame.metric), frame
        if intent == "distribuicao":
            dimension = frame.dimension or next((k for k, v in frame.categories.items() if len(v) > 1), "")
            if not dimension:
                return self._ask("dimensao_perfil", frame, intent, "dimensao", ["sexo", "identidade", "idade", "escolaridade"]), frame
            return Plan("consultar_distribuicao_demografica", None, territories=(territory,), dimension=dimension, categories={k: v for k, v in frame.categories.items() if v}), frame
        if intent == "comparar_territorios":
            if len(territories) == 1 and state.territories and state.territories[0] != territories[0]:
                territories = [state.territories[0]] + territories
            if len(territories) < 2:
                return Reply("esclarecimento", "territorios_ausentes"), frame
            frame.territories = territories
            metric = frame.metric or (state.metric if state.intent in {"votos", "comparar_territorios"} else "")
            frame.metric = metric
            return Plan("comparar_territorios", period, tuple(candidates[:1]), territories=tuple(territories), metric=metric), frame
        if intent == "comparar_candidatos":
            return Plan("comparar_candidatos", period, tuple(candidates) if frame.candidate_ref != "top2" else (), territories=(territory,), metric=frame.metric or "diferenca"), frame
        if intent == "votos":
            return Plan("consultar_votos", period, tuple(candidates), territories=(territory,), metric=frame.metric or "votos"), frame
        if intent == "vencedor":
            return Plan("consultar_resultado_territorial", period, tuple(candidates), territories=(territory,), metric=frame.metric or "vencedor", position=frame.position or 1), frame
        if intent == "resultado":
            return Plan("consultar_resultado_territorial", period, (), territories=(territory,), metric=frame.metric or "resultado"), frame
        return Reply("conversa", "desconhecido"), frame

    # ------------------------------------------------------------------ memória
    def remember(self, state, frame, plan=None, result=None, period=None, explicit=False, clarifying=False):
        """Atualiza seletivamente o contexto: só muda a dimensão que a pergunta alterou."""
        updates = {"exchanges": state.exchanges + 1, "pending": None}
        new = replace(state, **updates)
        if clarifying:
            # Um pedido de esclarecimento não redefine a intenção corrente.
            frame = replace(frame, intent="problema")
        if frame.candidates:
            new = new.remember_candidates(tuple(frame.candidates))
        if frame.territories and frame.intent not in {"ranking", "vitorias", "candidaturas"}:
            new = new.remember_places(tuple(frame.territories))
        if period or frame.year or frame.turn:
            p = period or (frame.year or (state.period[0] if state.period else None), frame.turn or (state.period[1] if state.period else None))
            new = replace(new, period=p, period_explicit=explicit or bool(frame.year or frame.turn))
        if frame.intent and frame.intent not in {"problema", "limitacao", "continuar", "comparar"}:
            new = replace(new, intent=frame.intent, metric=frame.metric)
        if frame.intent in {"ranking", "vitorias"} and frame.territories:
            new = replace(new, scope=frame.territories[0], limit=frame.limit, position=frame.position, order=frame.order, level=frame.level)
        if frame.intent in {"eleitorado", "distribuicao"}:
            new = replace(new, dimension=frame.dimension, categories=dict(frame.categories))
        if result is not None and plan is not None and plan.tool in {"consultar_resultado_territorial", "comparar_candidatos", "consultar_votos"}:
            rows = result.data.get("all", result.data.get("rows"))
            if rows is not None and len(rows) and "NM_URNA_CANDIDATO" in rows:
                new = replace(new, leaders=tuple(rows.NM_URNA_CANDIDATO.head(2)))
            # O vencedor/colocado informado passa a ser a candidatura em foco ("nele", "os dois").
            if plan.tool == "consultar_resultado_territorial" and not plan.candidates and rows is not None and len(rows) and result.data.get("total"):
                position = plan.position or 1
                target = rows.POSICAO.max() if position < 0 else position
                shown = tuple(rows.loc[rows.POSICAO.eq(target), "NM_URNA_CANDIDATO"])
                if shown and plan.metric not in {"resultado", "total_validos"}:
                    new = new.remember_candidates(shown)
            if plan.tool == "comparar_candidatos" and not plan.candidates and rows is not None:
                new = new.remember_candidates(tuple(result.data["rows"].NM_URNA_CANDIDATO.head(2)))
        return new
