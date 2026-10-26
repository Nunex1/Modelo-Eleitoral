"""Gerador de respostas: resultado verificado → texto mínimo suficiente em português.

Os textos são montados por modelos determinísticos. Todo número passa pelo
``Writer``, que registra sua origem; a resposta final só é exibida se cada
número do texto tiver sido produzido aqui a partir do resultado consultado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

import pandas as pd

from .data import normalize
from .language import fmt_dec, fmt_int, places_for

MAX_LIST = 5


@dataclass
class Rendered:
    text: str
    tables: list = field(default_factory=list)
    allowed: set = field(default_factory=set)


class Writer:
    def __init__(self, kb):
        self.kb = kb
        self.allowed = set()

    def n(self, value):
        text = fmt_int(value)
        self.allowed.add(text)
        return text

    def pct(self, value, places=1):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "percentual indisponível"
        text = fmt_dec(value, places)
        self.allowed.add(text)
        return text + "%"

    def pp(self, value, places=1):
        text = fmt_dec(value, places)
        self.allowed.add(text)
        return text + (" ponto percentual" if text in {"1,0", "1", "1,00"} else " pontos percentuais")

    def lit(self, value):
        self.allowed.update(re.findall(r"\d+", str(value)))
        return str(value)

    def period(self, period, long=False):
        year, turn = period
        return f"no {self.lit(turn)}º turno{' da eleição presidencial' if long else ''} de {self.lit(year)}"

    def place(self, territory):
        return self.lit(territory.phrase)

    def label(self, territory):
        return self.lit(territory.label)

    def subject(self, territory):
        text, plural = territory.subject
        return self.lit(text), plural

    def cand(self, key):
        candidate = self.kb.candidates.get(key)
        return candidate.display if candidate else key.title()

    def echo(self, text):
        """Eco seguro de texto digitado: sem marcação, links ou HTML."""
        clean = re.sub(r"[^\w\s'/-]", "", str(text), flags=re.U)[:60].strip()
        return self.lit(clean or "termo informado")


def join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def verdict(asserted, actual, kind):
    """Confronta um número afirmado pelo usuário com o valor consultado."""
    if not asserted or actual is None:
        return ""
    value, assert_kind, approximate = asserted[0]
    if assert_kind != kind:
        return ""
    if kind == "pct":
        error = abs(value - actual)
        return "Sim. " if error <= 0.05 else "Aproximadamente. " if error <= 1 else "Não. "
    if value == actual:
        return "Sim. "
    relative = abs(value - actual) / actual if actual else 1
    return "Aproximadamente. " if approximate and relative <= 0.02 else "Não. "


# ---------------------------------------------------------------------------- votos

def render_votes(w, plan, data, frame):
    rows, territory = data["rows"], data["territory"]
    place, period = w.place(territory), w.period(plan.period, long=True)
    places = places_for(list(rows.PERCENTUAL))
    prefix = ""
    if frame.note == "bases_incompativeis":
        prefix = "Votos e cadastro são bases distintas; o percentual disponível usa os votos válidos. "
    if len(rows) == 1:
        r = rows.iloc[0]
        name = w.cand(r.NM_URNA_CANDIDATO)
        if plan.metric == "percentual":
            check = verdict(frame.asserted, r.PERCENTUAL, "pct")
            return Rendered(prefix + check + f"{name} teve {w.pct(r.PERCENTUAL, places)} dos votos válidos {place} {w.period(plan.period)}.")
        if plan.metric == "desempenho":
            return Rendered(f"{name} recebeu {w.n(r.VOTOS)} votos {place} ({w.pct(r.PERCENTUAL, places)} dos votos válidos) "
                            f"e ficou em {w.lit(int(r.POSICAO))}º lugar {w.period(plan.period)}.")
        check = verdict(frame.asserted, int(r.VOTOS), "abs")
        return Rendered(prefix + check + f"{name} recebeu {w.n(r.VOTOS)} votos {place} {period}.")
    lines = [f"Votos {place} {w.period(plan.period)}:"]
    for r in rows.itertuples():
        main = f"{w.pct(r.PERCENTUAL, places)} dos válidos ({w.n(r.VOTOS)} votos)" if plan.metric == "percentual" else f"{w.n(r.VOTOS)} votos ({w.pct(r.PERCENTUAL, places)})"
        lines.append(f"- {w.cand(r.NM_URNA_CANDIDATO)}: {main}")
    return Rendered("\n".join(lines))


def render_result(w, plan, data, frame):
    rows, territory, total = data["rows"], data["territory"], data["total"]
    place, period = w.place(territory), w.period(plan.period)
    if not total:
        return Rendered(f"Não há votos válidos registrados {place} {period}.")
    if plan.metric == "total_validos":
        subject, plural = w.subject(territory)
        return Rendered(f"{subject} {'tiveram' if plural else 'teve'} {w.n(total)} votos válidos para Presidente {period}.")
    places = places_for(list(rows.PERCENTUAL.head(3)))
    if plan.metric == "resultado":
        first, second = rows.iloc[0], rows.iloc[1] if len(rows) > 1 else None
        text = f"{w.cand(first.NM_URNA_CANDIDATO)} {'foi o mais votado' if territory.kind in {'brasil', 'total'} else 'venceu'} {place} {period}, com {w.pct(first.PERCENTUAL, places)} dos votos válidos"
        text += f"; {w.cand(second.NM_URNA_CANDIDATO)} teve {w.pct(second.PERCENTUAL, places)}." if second is not None else "."
        table = rows.assign(Candidatura=rows.NM_URNA_CANDIDATO.map(w.cand)).rename(columns={"SG_PARTIDO": "Partido", "VOTOS": "Votos", "PERCENTUAL": "% válidos", "POSICAO": "Posição"})
        return Rendered(text, [(f"Resultado {territory.label} · {plan.period[1]}º turno de {plan.period[0]}", table[["Posição", "Candidatura", "Partido", "Votos", "% válidos"]])])
    position = plan.position or 1
    target = rows.POSICAO.max() if position < 0 else position
    leaders = rows[rows.POSICAO.eq(target)]
    if leaders.empty:
        return Rendered(f"Há apenas {w.n(len(rows))} candidaturas {place} {period}.")
    with_votes = plan.metric == "votos"
    if plan.candidates:
        asked = rows[rows.NM_URNA_CANDIDATO.eq(plan.candidates[0])].iloc[0]
        winner = leaders.iloc[0]
        if asked.NM_URNA_CANDIDATO in set(leaders.NM_URNA_CANDIDATO) and len(leaders) == 1:
            return Rendered(f"Sim. {w.cand(winner.NM_URNA_CANDIDATO)} venceu {place} {period}, com {w.pct(winner.PERCENTUAL, places)} dos votos válidos.")
        return Rendered(f"Não. {w.cand(winner.NM_URNA_CANDIDATO)} venceu {place} {period}, com {w.pct(winner.PERCENTUAL, places)} dos votos válidos; "
                        f"{w.cand(asked.NM_URNA_CANDIDATO)} ficou em {w.lit(int(asked.POSICAO))}º lugar, com {w.pct(asked.PERCENTUAL, places_for([asked.PERCENTUAL, winner.PERCENTUAL]))}.")
    if len(leaders) > 1:
        names = join(w.cand(k) for k in leaders.NM_URNA_CANDIDATO)
        where = "em primeiro lugar" if position == 1 else f"na {w.lit(target)}ª posição"
        return Rendered(f"Houve empate {where} {place} {period}: {names}, com {w.n(leaders.iloc[0].VOTOS)} votos cada.")
    r = leaders.iloc[0]
    name = w.cand(r.NM_URNA_CANDIDATO)
    if position == 1:
        verb = "foi o mais votado" if territory.kind in {"brasil", "total", "exterior"} else "venceu"
        amount = f"{w.n(r.VOTOS)} votos ({w.pct(r.PERCENTUAL, places)} dos válidos)" if with_votes else f"{w.pct(r.PERCENTUAL, places)} dos votos válidos"
        return Rendered(f"{name} {verb} {place} {period}, com {amount}.")
    if position < 0:
        return Rendered(f"{name} foi o menos votado {place} {period}, com {w.n(r.VOTOS)} votos ({w.pct(r.PERCENTUAL, places_for(list(rows.PERCENTUAL)))}).")
    return Rendered(f"{name} ficou em {w.lit(target)}º lugar {place} {period}, com {w.n(r.VOTOS)} votos ({w.pct(r.PERCENTUAL, places_for(list(rows.PERCENTUAL)))} dos válidos).")


def render_comparison(w, plan, data, frame):
    rows, pairs, territory = data["rows"], data["pairs"], data["territory"]
    place, period = w.place(territory), w.period(plan.period)
    if len(rows) < 2:
        return Rendered(f"Há menos de duas candidaturas com votos {place} {period}.")
    a, b = rows.iloc[0], rows.iloc[1]
    na, nb = w.cand(a.NM_URNA_CANDIDATO), w.cand(b.NM_URNA_CANDIDATO)
    places = places_for([a.PERCENTUAL, b.PERCENTUAL])
    pair = pairs[0]
    if a.VOTOS == b.VOTOS:
        return Rendered(f"{na} e {nb} empataram {place} {period}, com {w.n(a.VOTOS)} votos cada.")
    metric = plan.metric
    if metric == "mais_votos":
        if len(rows) > 2:
            lines = [f"{na} teve mais votos entre as candidaturas citadas {place} {period}:"]
            lines += [f"- {w.cand(r.NM_URNA_CANDIDATO)}: {w.n(r.VOTOS)} votos ({w.pct(r.PERCENTUAL, places_for(list(rows.PERCENTUAL)))})" for r in rows.itertuples()]
            return Rendered("\n".join(lines))
        return Rendered(f"{na} teve mais votos que {nb} {place} {period}: {w.n(a.VOTOS)} ({w.pct(a.PERCENTUAL, places)}) contra {w.n(b.VOTOS)} ({w.pct(b.PERCENTUAL, places)}).")
    pp_places = places_for([pair["pp"]]) if pair["pp"] is not None else 1
    if metric == "diferenca_votos":
        return Rendered(f"{na} recebeu {w.n(pair['votos'])} votos a mais que {nb} {place} {period}.")
    if metric == "diferenca_pp":
        return Rendered(f"A diferença entre {na} ({w.pct(a.PERCENTUAL, places)}) e {nb} ({w.pct(b.PERCENTUAL, places)}) foi de {w.pp(pair['pp'], pp_places)} dos votos válidos {place} {period}.")
    if metric == "variacao":
        if pair["relativa"] is None:
            return Rendered(f"Não há variação relativa calculável: {nb} teve 0 votos {place} {period}.")
        return Rendered(f"{na} teve {w.pct(pair['relativa'], places_for([pair['relativa']]))} mais votos que {nb} {place} {period} ({w.n(a.VOTOS)} contra {w.n(b.VOTOS)}).")
    return Rendered(f"{na} recebeu {w.n(pair['votos'])} votos a mais que {nb} {place} {period}, uma diferença de {w.pp(pair['pp'], pp_places)} dos votos válidos.")


def render_territories(w, plan, data, frame):
    entries, candidate = data["rows"], data["candidate"]
    period = w.period(plan.period)
    if candidate:
        name = w.cand(candidate)
        places = places_for([e["percentual"] for e in entries])
        if len(entries) == 2:
            e1, e2 = entries
            if plan.metric == "percentual":
                return Rendered(f"{name} teve {w.pct(e1['percentual'], places)} dos votos válidos {w.place(e1['territory'])} e {w.pct(e2['percentual'], places)} {w.place(e2['territory'])} {period}.")
            return Rendered(f"{name} recebeu {w.n(e1['votos'])} votos {w.place(e1['territory'])} ({w.pct(e1['percentual'], places)}) e {w.n(e2['votos'])} {w.place(e2['territory'])} ({w.pct(e2['percentual'], places)}) {period}.")
        table = pd.DataFrame([{"Localidade": w.label(e["territory"]), "Votos": e["votos"], "% válidos": e["percentual"], "Posição": e["posicao"]} for e in entries])
        return Rendered(f"{name} {period}:", [("Comparação territorial", table)])
    rows = []
    for e in entries:
        leaders = e["leaders"]
        rows.append({"Localidade": w.label(e["territory"]), "Votos válidos": e["total"],
                     "Mais votado": join(w.cand(k) for k in leaders.NM_URNA_CANDIDATO) if len(leaders) else "Sem votos",
                     "% do mais votado": leaders.iloc[0].PERCENTUAL if len(leaders) else None, **({"Eleitores cadastrados": e["eleitores"]} if "eleitores" in e else {})})
    text = "Comparação " + period + ": " + "; ".join(
        f"{w.label(e['territory'])}, {w.n(e['total'])} votos válidos, mais votado {join(w.cand(k) for k in e['leaders'].NM_URNA_CANDIDATO)} ({w.pct(e['leaders'].iloc[0].PERCENTUAL)})"
        for e in entries if len(e["leaders"])) + "."
    return Rendered(text, [("Comparação territorial", pd.DataFrame(rows))] if len(entries) > 2 else [])


def category_phrase(w, categories, plural=True):
    """Descrição das categorias do cadastro: 'eleitoras com 18 anos'."""
    parts, noun = [], "eleitores"
    for name, values in categories.items():
        for value in values:
            norm = normalize(value)
            if name == "sexo" and norm == "FEMININO" and len(values) == 1:
                noun = "eleitoras"
            elif name == "sexo":
                parts.append("do sexo masculino" if norm == "MASCULINO" else "do sexo feminino" if norm == "FEMININO" else "com gênero não informado")
            elif name == "identidade":
                parts.append({"PREFERE NAO INFORMAR": "que preferem não informar a identidade de gênero", "NAO INFORMADO": "com identidade de gênero não informada"}.get(norm, f"com identidade de gênero {value.lower()}"))
            elif name == "escolaridade":
                parts.append({"ANALFABETO": "analfabetos", "LE E ESCREVE": "que leem e escrevem", "NAO INFORMADO": "com escolaridade não informada"}.get(norm, f"com {value.lower()}"))
        if name == "idade":
            parts.append(age_phrase(w, values))
    return w.lit(noun + ("" if not parts else " " + join(parts)))


def age_phrase(w, bands):
    bounds = sorted(tuple(int(n) for n in re.findall(r"\d+", b)) for b in bands if re.findall(r"\d+", b))
    if not bounds:
        return "com idade inválida no cadastro"
    lo, hi = bounds[0][0], bounds[-1][-1]
    if any("mais" in b for b in bands):
        return f"com {lo} anos ou mais"
    return f"com {lo} anos" if lo == hi else f"de {lo} a {hi} anos"


def render_electorate(w, plan, data, frame):
    territory, count, total = data["territory"], data["count"], data["total"]
    subject, plural = w.subject(territory)
    year = w.lit(data["year"])
    if plan.metric == "percentual" and plan.categories:
        share = 100 * count / total if total else None
        what = category_phrase(w, plan.categories)
        article = "As" if what.startswith("eleitoras") else "Os"
        return Rendered(f"{article} {what} são {w.pct(share, places_for([share]))} do eleitorado {w.place(territory).replace('em ', 'de ', 1) if territory.kind == 'municipio' else w.place(territory)} "
                        f"({w.n(count)} de {w.n(total)}), segundo o cadastro eleitoral de {year}.")
    what = category_phrase(w, plan.categories) if plan.categories else "eleitores"
    check = verdict(frame.asserted, count, "abs")
    return Rendered(check + f"{subject} {'têm' if plural else 'tem'} {w.n(count)} {what} no cadastro eleitoral de {year}.")


DIMENSION_NAMES = {"sexo": "sexo (gênero no cadastro)", "identidade": "identidade de gênero", "idade": "faixa etária", "escolaridade": "escolaridade"}


def render_distribution(w, plan, data, frame):
    rows, territory, total = data["rows"], data["territory"], data["total"]
    year = w.lit(data["year"])
    requested = plan.categories.get(plan.dimension)
    if requested and len(requested) <= 4:
        parts = [f"{w.n(r.QT_ELEITORES)} {category_phrase(w, {plan.dimension: (r.CATEGORIA,)})}" for r in rows.itertuples()]
        place = w.place(territory)
        return Rendered(f"{place[0].upper() + place[1:]}, o cadastro eleitoral de {year} tem {join(parts)}.")
    table = rows.rename(columns={"CATEGORIA": "Categoria", "QT_ELEITORES": "Eleitores", "PERCENTUAL": "% do recorte"})
    head = f"Distribuição do eleitorado {w.place(territory)} por {DIMENSION_NAMES[plan.dimension]}, segundo o cadastro de {year} ({w.n(total)} eleitores)"
    filters = {k: v for k, v in plan.categories.items() if k != plan.dimension and v}
    if filters:
        head += ", entre " + category_phrase(w, filters)
    top = rows.iloc[0] if len(rows) else None
    text = head + "." + (f" Maior grupo: {top.CATEGORIA.lower()} ({w.pct(top.PERCENTUAL, places_for([top.PERCENTUAL]))})." if top is not None and plan.dimension != "idade" else "")
    return Rendered(text, [(f"Perfil por {DIMENSION_NAMES[plan.dimension]}", table)])


RANK_WHAT = {"votos_candidato": "mais votos para {c}", "percentual_candidato": "o maior percentual de votos válidos para {c}",
             "votos_validos": "mais votos válidos", "eleitores": "o maior eleitorado{d}", "percentual_eleitores": "a maior proporção de {d2}"}
RANK_WHAT_ASC = {"votos_candidato": "menos votos para {c}", "percentual_candidato": "o menor percentual de votos válidos para {c}",
                 "votos_validos": "menos votos válidos", "eleitores": "o menor eleitorado{d}", "percentual_eleitores": "a menor proporção de {d2}"}


def render_ranking(w, plan, data, frame):
    rows, scope = data["rows"], data["scope"]
    candidate = w.cand(data["candidate"]) if data["candidate"] else ""
    profile = plan.metric in {"eleitores", "percentual_eleitores"}
    when = f"segundo o cadastro eleitoral de {w.lit(data['year'])}" if profile else w.period(plan.period)
    d = (" " + category_phrase(w, plan.categories).replace("eleitores ", "").replace("eleitoras", "feminino")) if plan.categories else ""
    d2 = category_phrase(w, plan.categories) if plan.categories else "eleitores"
    what = (RANK_WHAT if plan.order != "asc" else RANK_WHAT_ASC)[plan.metric].format(c=candidate, d=d.rstrip(), d2=d2)
    unit = "estado" if plan.level == "uf" else "município"
    where = w.place(scope)

    def name(r):
        return w.lit(w.kb.states[r.SG_UF] if plan.level == "uf" else f"{w.kb.city_by_code[r.CD_MUNICIPIO].name}/{r.SG_UF}")

    def amount(r):
        if plan.metric == "percentual_candidato":
            return f"{w.pct(r.PERCENTUAL, places_for(list(rows.PERCENTUAL)))} ({w.n(r.NUMERADOR)} votos)"
        if plan.metric == "percentual_eleitores":
            return f"{w.pct(r.PERCENTUAL, places_for(list(rows.PERCENTUAL)))} ({w.n(r.NUMERADOR)} de {w.n(r.DENOMINADOR)})"
        if profile:
            return f"{w.n(r.NUMERADOR)} {d2}"
        return f"{w.n(r.NUMERADOR)} votos" + ("" if plan.metric == "votos_candidato" else " válidos")

    if rows.empty:
        return Rendered(f"Não há {unit}s elegíveis para esse ranking {where}.")
    if plan.position or (plan.limit or 1) == 1:
        if len(rows) > 1:
            return Rendered(f"Empate entre {join(name(r) for r in rows.itertuples())}, com {amount(rows.iloc[0])} cada, {when}.")
        r = rows.iloc[0]
        if plan.position and plan.position != 1:
            ordinal = w.lit(plan.position) + ("º" if unit == "estado" else "ª") if plan.position > 0 else ("último" if unit == "estado" else "última")
            return Rendered(f"{'O' if unit == 'estado' else 'A'} {ordinal} {'estado' if unit == 'estado' else 'cidade'} com {what} {where} foi {name(r)}, com {amount(r)}, {when}.")
        verb = "é" if profile else "foi"
        return Rendered(f"{name(r)} {verb} o {unit} com {what} {where}: {amount(r)}, {when}.")
    limit = plan.limit
    header = f"Os {w.lit(limit)} {unit}s com {what} {where}, {when}:"
    if data["eligible"] < limit:
        header = f"Há {w.n(data['eligible'])} {unit}s elegíveis {where}. Com {what}, {when}:"
    tie_note = " Há empate na última posição; todos os empatados foram incluídos." if len(rows) > limit else ""
    if len(rows) <= MAX_LIST:
        lines = [header] + [f"{w.lit(int(r.POSICAO))}. {name(r)} — {amount(r)}" for r in rows.itertuples()]
        return Rendered("\n".join(lines) + ("\n\n" + tie_note.strip() if tie_note else ""))
    table = pd.DataFrame([{"Posição": int(r.POSICAO), unit.capitalize(): (w.kb.states[r.SG_UF] if plan.level == "uf" else f"{w.kb.city_by_code[r.CD_MUNICIPIO].name}/{r.SG_UF}"),
                           ("% válidos" if plan.metric == "percentual_candidato" else "% do cadastro" if plan.metric == "percentual_eleitores" else "Votos" if not profile else "Eleitores"):
                           (r.PERCENTUAL if plan.metric.startswith("percentual") else r.NUMERADOR)} for r in rows.itertuples()])
    return Rendered(header.rstrip(":") + "." + tie_note, [("Ranking", table)])


def render_wins(w, plan, data, frame):
    unit = "estados" if plan.level == "uf" else "municípios"
    text = f"{w.cand(data['candidate'])} foi o mais votado em {w.n(data['wins'])} dos {w.n(data['eligible'])} {unit} {w.place(data['scope'])} {w.period(plan.period)}."
    if data["ties"]:
        text += f" Em {w.n(data['ties'])} {unit[:-1] if data['ties'] == 1 else unit} houve empate na primeira posição."
    return Rendered(text)


def render_candidacies(w, plan, data, frame):
    rows = data["rows"]
    year = w.lit(plan.period[0])
    if plan.metric == "segundo_turno":
        if "DS_SIT_TOT_TURNO" not in rows:
            return Rendered("A situação de totalização das candidaturas não está na base preparada.")
        qualified = rows[rows.DS_SIT_TOT_TURNO.astype(str).map(normalize).eq("2O TURNO")]
        if qualified.empty:
            return Rendered(f"Nenhuma candidatura aparece com situação “{w.lit(2)}º turno” na totalização do {w.lit(1)}º turno de {year}.")
        names = join(f"{w.cand(r.NM_URNA_CANDIDATO)} ({r.SG_PARTIDO})" for r in qualified.itertuples())
        return Rendered(f"{names} foram para o {w.lit(2)}º turno, segundo a totalização do {w.lit(1)}º turno de {year}.")
    if plan.metric in {"partido", "numero", "nome"} and plan.candidates:
        lines = []
        for key in plan.candidates:
            c = w.kb.candidates[key]
            if plan.metric == "partido":
                lines.append(f"{c.display} concorreu pelo {c.party}" + (f" ({c.party_name.title()})" if c.party_name else "") + f", número {w.lit(c.number)}, em {year}.")
            elif plan.metric == "numero":
                lines.append(f"O número de {c.display} em {year} foi {w.lit(c.number)}.")
            else:
                lines.append(f"O nome completo de {c.display} no registro do TSE é {c.full_name.title() if c.full_name else c.key.title()}." if c.full_name else
                             f"A base preparada não contém o nome completo de {c.display}.")
        return Rendered(" ".join(lines))
    count = f"{w.n(len(rows))} candidaturas disputaram a Presidência {w.period(plan.period)}."
    if plan.metric == "contagem":
        return Rendered(count)
    table = rows.assign(Candidatura=rows.NM_URNA_CANDIDATO.map(w.cand)).rename(columns={"NR_CANDIDATO": "Número", "SG_PARTIDO": "Partido", "VOTOS_BRASIL": "Votos", "PERCENTUAL": "% válidos"})
    return Rendered(count, [("Candidaturas (votos no Brasil, sem exterior)", table[["Número", "Candidatura", "Partido", "Votos", "% válidos"]])])


def render_municipalities(w, plan, data, frame):
    territory = data["territory"]
    if territory.kind == "ddd":
        text = f"O DDD {w.lit(territory.code)} abrange {w.n(data['count'])} municípios com correspondência validada na base."
        if data["gap"]:
            text += f" {w.n(len(data['gap']))} municípios das mesmas UFs estão sem DDD validado."
        return Rendered(text)
    subject, plural = w.subject(territory)
    return Rendered(f"{subject} {'têm' if plural else 'tem'} {w.n(data['count'])} municípios na base.")


RENDERERS = {"consultar_votos": render_votes, "consultar_resultado_territorial": render_result, "comparar_candidatos": render_comparison,
             "comparar_territorios": render_territories, "consultar_eleitorado": render_electorate,
             "consultar_distribuicao_demografica": render_distribution, "gerar_ranking_municipal": render_ranking,
             "contar_vitorias": render_wins, "consultar_candidaturas": render_candidacies, "contar_municipios": render_municipalities}


def render(kb, plan, result, frame, engine=None):
    w = Writer(kb)
    rendered = RENDERERS[plan.tool](w, plan, result.data, frame)
    if engine is not None:
        gap = [t for t in (plan.territories + ((plan.scope,) if plan.scope else ())) if t.kind == "ddd" and engine.ddd_coverage_gap(t)]
        if gap and plan.tool != "contar_municipios":
            missing = engine.ddd_coverage_gap(gap[0])
            rendered.text += f" Cobertura parcial: {w.n(len(missing))} municípios das UFs desse DDD não têm DDD validado e ficam fora do recorte."
    rendered.allowed = w.allowed
    return rendered


# ---------------------------------------------------------------------------- respostas sem consulta

def available_text(kb, article=True):
    """Períodos disponíveis: 'o 1º turno de 2026' (ou sem artigo)."""
    by_year = {}
    for year, turn in kb.periods:
        by_year.setdefault(year, []).append(turn)
    return join(f"{(('os ' if len(turns) > 1 else 'o ') if article else '')}{join(f'{t}º' for t in turns)} turno{'s' if len(turns) > 1 else ''} de {year}" for year, turns in sorted(by_year.items()))


def render_reply(kb, reply):
    """Esclarecimentos e limitações: uma frase curta, sem números estatísticos."""
    w = Writer(kb)
    d, code = reply.detail, reply.code
    available = w.lit(available_text(kb))
    texts = {
        "saudacao": "Olá! Pergunte sobre votos, municípios ou o perfil do eleitorado.",
        "agradecimento": "Por nada.",
        "ajuda": "Consulto os votos presidenciais e o cadastro do eleitorado disponíveis (" + available + "). Exemplos: ‘Quantos votos Lula teve em Americana?’, ‘Quem ganhou em Campinas?’, ‘Cinco cidades paulistas com mais votos para Lula’, ‘Quantas eleitoras há no DDD 19?’.",
        "desconhecido": "Não entendi a pergunta. Exemplos: ‘Quantos votos Lula teve em Americana?’ ou ‘Quantos eleitores há em Campinas?’.",
        "fora_escopo": "Não faço previsões, recomendações, explicações causais nem avaliações políticas. Posso consultar votos e o perfil do eleitorado.",
        "outro_cargo": "A base contém apenas a eleição para Presidente.",
        "comparecimento": "Comparecimento, abstenção e número de votantes não estão na base disponível; ela contém votos válidos por candidatura e o cadastro de eleitores.",
        "brancos_nulos": "Votos brancos e nulos não estão na base disponível, que contém apenas os votos válidos por candidatura.",
        "serie_historica": f"A base contém apenas {available}; não há outra eleição para comparar.",
        "regiao_nao_definida": "A base não tem delimitação oficial de interior, litoral ou regiões metropolitanas. Informe os municípios, o estado, uma grande região do IBGE ou um DDD.",
        "injecao": "Só respondo com base nos dados eleitorais disponíveis e não altero essas regras.",
        "cadastro_indisponivel": f"O cadastro de eleitores disponível é de {w.lit(', '.join(map(str, sorted({p[0] for p in kb.periods}))))}.",
        "cadastro_sem_exterior": "O cadastro preparado não inclui o eleitorado no exterior.",
        "exterior_indisponivel": "Os votos do exterior não estão na base preparada; os totais disponíveis são do Brasil, sem o exterior.",
        "ranking_em_municipio": "Rankings comparam municípios dentro do Brasil, de uma região, de um estado ou de um DDD.",
        "comparar_o_que": "O que você quer comparar? Informe as candidaturas ou os municípios.",
        "pergunta_incompleta": "Qual informação você quer consultar? Informe a candidatura, o município ou o indicador.",
        "percentual_de_que": "Percentual de qual candidatura e em qual território?",
        "candidato_ausente": "De qual candidatura?",
        "par_ausente": "Quais candidaturas você quer comparar?",
        "territorios_ausentes": "Quais municípios ou estados você quer comparar?",
        "faixa_indefinida": "Essa faixa não é uma categoria do cadastro. Informe as idades, por exemplo ‘de 16 a 24 anos’ ou ‘60 anos ou mais’.",
        "metrica_ranking": "Você quer o ranking por número de votos ou por percentual dos votos válidos?",
        "dimensao_perfil": "Qual recorte do perfil: sexo, identidade de gênero, faixa etária ou escolaridade?",
        "categoria_sem_dimensao": "“Não informado” em qual campo: sexo, identidade de gênero ou escolaridade?",
        "escolaridade_ambigua": "Completo ou incompleto?",
        "consulta_excessiva": "A consulta pede mais itens do que o limite permitido. Reduza a quantidade de municípios ou candidaturas.",
        "limite_invalido": "O ranking aceita de 1 a 50 posições.",
        "dados_indisponiveis": "Não consegui consultar a base de dados agora. Nenhum número foi apresentado; tente novamente em instantes.",
        "verificacao": "Não foi possível validar o resultado desta consulta; por isso nenhum número foi apresentado.",
    }
    if code in texts:
        return texts[code]
    if code == "inferencia_demografica":
        attribute = d.get("attribute", "o perfil")
        if attribute == "o perfil":
            return "Não é possível determinar. Os dados públicos de votação não identificam o perfil dos eleitores que votaram em cada candidato."
        return f"Não é possível determinar. Os dados públicos de votação não identificam {attribute} dos eleitores que votaram em cada candidato."
    if code == "dimensao_indisponivel":
        return f"A base preparada não inclui {d.get('attribute', 'essa informação')}. As dimensões do cadastro disponíveis são sexo, identidade de gênero, faixa etária e escolaridade."
    if code == "periodo_indisponivel":
        period = d.get("period") or ()
        years = {p[0] for p in kb.periods}
        alternative = d.get("alternative")
        offer = f" Quer consultar o {w.lit(alternative[1])}º turno de {w.lit(alternative[0])}?" if alternative else ""
        if period and period[0] in years:
            return f"Os dados do {w.lit(period[1])}º turno de {w.lit(period[0])} ainda não estão integrados à base; há apenas {available}.{offer}"
        return f"A base contém apenas {available}.{offer}"
    if code == "ano":
        return "De qual eleição: " + join(w.lit(y) for y in d["options"]) + "?"
    if code == "turno":
        return "Você quer os resultados do " + join(f"{w.lit(t)}º" for t in d["options"]) + " turno?"
    if code == "estado_ou_municipio":
        state = next(o for o in d["options"] if o.kind == "uf")
        cities = [o for o in d["options"] if o.kind == "municipio"]
        return f"Você quer o {state.phrase[3:]} ou o município de {join(w.label(c) for c in cities)}?"
    if code == "municipio_homonimo":
        options = d["options"]
        return f"Há municípios chamados {options[0].name} em {join(sorted({o.uf for o in options}))}. Qual UF?"
    if code == "municipio_fora_da_uf":
        found = d.get("found") or []
        offer = f" Quer consultar {w.echo(d['text']).title()}/{found[0]}?" if len(found) == 1 else ""
        return f"Não encontrei {w.echo(d['text']).title()} em {d['uf']}." + (f" Há {w.echo(d['text']).title()} em {join(found)}.{offer}" if found else "")
    if code == "candidato_ambiguo":
        return f"Mais de uma candidatura corresponde a “{w.echo(d['text']).title()}”: {join(w.cand(k) for k in d['options'])}. Qual delas?"
    if code == "candidato_inexistente":
        base = f"Não há candidatura de “{w.echo(d['text']).title()}” na eleição presidencial desta base ({w.lit(available_text(kb, article=False))})."
        if d.get("similar"):
            base += f" Você quer consultar {w.cand(d['similar'])} ({kb.candidates[d['similar']].party})?"
        return base
    if code == "candidato_fora_do_pleito":
        return f"{w.cand(d['candidate'])} não tem candidatura no {w.lit(d['period'][1])}º turno de {w.lit(d['period'][0])} nesta base."
    if code == "entidade_desconhecida":
        return f"Não encontrei “{w.echo(d['text'])}” entre os municípios nem entre as candidaturas da base. Confira o nome e, se for município, informe a UF."
    if code == "ddd_inexistente" or code == "ddd_sem_correspondencia":
        return f"O DDD {w.lit(d.get('ddd', ''))} não tem municípios com correspondência validada na base."
    if code == "faixa_desalinhada":
        bands = d.get("options") or []
        options = ", ".join(bands[:3]) + (", …" if len(bands) > 3 else "")
        return "O cadastro usa faixas etárias fixas e não permite separar exatamente essa idade" + (f". Faixas próximas: {w.lit(options)}." if bands else ".")
    if code == "partido_incompativel":
        c = d["candidate"]
        return f"{c.display} concorreu pelo {c.party}, não pelo {d['party']}. Qual candidatura você quer consultar?"
    if code == "parceiro_comparacao":
        return f"Comparar {w.cand(d['candidate'])} com qual candidatura?"
    return "Não consegui responder com segurança a partir dos dados disponíveis."
