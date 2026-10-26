"""Ferramentas de consulta: contrato tipado entre a interpretação e o motor estatístico.

Cada ferramenta declara parâmetros, validação, retorno, fonte e limites. Nenhuma
recebe texto livre para executar: os parâmetros já chegam resolvidos contra a base
(chaves de candidatura, códigos territoriais, período) e são revalidados aqui.
Os retornos são dados; nunca são reinterpretados como instruções.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time

from .data import DIMENSIONS
from .engine import DataUnavailable
from .entities import REGIONS, Territory
from .verification import VerificationError, check, verify_distribution, verify_electorate, verify_ranking, verify_result

LOG = logging.getLogger("lampiadim.consultas")
MAX_LIMIT, MAX_TERRITORIES, MAX_CANDIDATES = 50, 6, 12
VOTE_SCOPES = {"brasil", "regiao", "uf", "ddd", "municipio", "exterior", "total"}
RANKING_SCOPES = {"brasil", "regiao", "uf", "ddd"}
PROFILE_SCOPES = {"brasil", "regiao", "uf", "ddd", "municipio"}


class QueryError(ValueError):
    """Consulta inválida para a base: o código orienta a mensagem, sem números."""

    def __init__(self, code, **details):
        super().__init__(code)
        self.code, self.details = code, details


@dataclass
class Plan:
    tool: str
    period: tuple | None = None
    candidates: tuple = ()
    territories: tuple = ()
    scope: Territory | None = None
    metric: str = ""
    dimension: str = ""
    categories: dict = field(default_factory=dict)
    limit: int | None = None
    position: int | None = None
    order: str = "desc"
    level: str = "municipio"


@dataclass
class ToolResult:
    tool: str
    data: dict
    trace: dict


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict      # nome → (tipo, obrigatório, regra de validação)
    returns: str
    source: str
    limits: str
    run: object = None


VOTES_SOURCE = "votos.parquet · TSE votacao_candidato_munzona (arquivo BR, cargo Presidente, sem exterior)"
PROFILE_SOURCE = "perfil.parquet · TSE perfil_eleitorado (27 UFs, sem exterior)"
INFO_SOURCE = "candidatos.parquet · TSE votacao_candidato_munzona (metadados e votos no exterior)"


def _version(data, key):
    source = data.manifest["sources"].get(key, {})
    dates = ", ".join(source.get("generated_dates", [])) or data.manifest.get("prepared_at", "")[:10]
    return f"geração {dates} · sha256 {source.get('sha256', '')[:12]}"


def _trace(engine, tool, plan, table, version_key, metric, denominator, records, result):
    return {"ferramenta": tool, "fonte": table, "versao": _version(engine.data, version_key), "ano": plan.period[0] if plan.period else None,
            "turno": plan.period[1] if plan.period else None, "filtros": _filters(plan), "metrica": metric, "denominador": denominator,
            "registros": records, "resultado": result, "validacao": "pendente"}


def _filters(plan):
    out = {}
    if plan.candidates:
        out["candidaturas"] = list(plan.candidates)
    if plan.territories:
        out["territorios"] = [t.label for t in plan.territories]
    if plan.scope:
        out["escopo"] = plan.scope.label
    if plan.categories:
        out["cadastro"] = {k: list(v) for k, v in plan.categories.items() if v}
    for key in ["limit", "position", "order", "level", "dimension"]:
        value = getattr(plan, key)
        if value not in (None, "", "desc", "municipio"):
            out[key] = value
    return out


# ---------------------------------------------------------------------------- validação

def validate(engine, plan):
    kb = engine.kb
    spec = TOOLS.get(plan.tool)
    if spec is None:
        raise QueryError("ferramenta_desconhecida")
    profile_tool = plan.tool in {"consultar_eleitorado", "consultar_distribuicao_demografica", "contar_municipios"} or plan.metric in {"eleitores", "percentual_eleitores"}
    if not profile_tool and plan.period not in kb.periods:
        raise QueryError("periodo_indisponivel", period=plan.period)
    if len(plan.candidates) > MAX_CANDIDATES or len(plan.territories) > MAX_TERRITORIES:
        raise QueryError("consulta_excessiva")
    for key in plan.candidates:
        candidate = kb.candidates.get(key)
        if candidate is None or plan.period not in candidate.periods:
            raise QueryError("candidato_fora_do_pleito", candidate=key, period=plan.period)
    for territory in plan.territories + ((plan.scope,) if plan.scope else ()):
        _validate_territory(engine, territory)
    if plan.limit is not None and not 1 <= plan.limit <= MAX_LIMIT:
        raise QueryError("limite_invalido")
    for name, values in plan.categories.items():
        if name not in DIMENSIONS or any(v not in engine.data.categories[name] for v in values):
            raise QueryError("categoria_invalida", dimension=name)
    if plan.dimension and plan.dimension not in DIMENSIONS:
        raise QueryError("categoria_invalida", dimension=plan.dimension)
    if plan.tool in {"consultar_eleitorado", "consultar_distribuicao_demografica"} or plan.metric in {"eleitores", "percentual_eleitores"}:
        if plan.period and plan.period[0] not in engine.profile_years:
            raise QueryError("cadastro_indisponivel", year=plan.period[0])
        for territory in plan.territories + ((plan.scope,) if plan.scope else ()):
            if territory.kind not in PROFILE_SCOPES:
                raise QueryError("cadastro_sem_exterior")


def _validate_territory(engine, territory):
    kb = engine.kb
    if territory.kind not in VOTE_SCOPES:
        raise QueryError("territorio_invalido")
    if territory.kind == "uf" and territory.code not in kb.states:
        raise QueryError("territorio_invalido")
    if territory.kind == "regiao" and territory.code not in REGIONS:
        raise QueryError("territorio_invalido")
    if territory.kind in {"exterior", "total"} and "VOTOS_EXTERIOR" not in engine.info:
        raise QueryError("exterior_indisponivel")
    if territory.kind == "ddd" and int(territory.code) not in kb.ddds:
        raise QueryError("ddd_sem_correspondencia", ddd=territory.code)
    if territory.kind == "municipio" and not engine.codes(territory):
        raise QueryError("territorio_invalido")


# ---------------------------------------------------------------------------- execução

def _result(engine, plan, territory):
    result = engine.result(plan.period, territory)
    return result, verify_result(engine.data, result, territory, plan.period)


def consultar_votos(engine, plan):
    territory = plan.territories[0]
    result, status = _result(engine, plan, territory)
    rows = result["rows"]
    chosen = rows[rows.NM_URNA_CANDIDATO.isin(plan.candidates)].set_index("NM_URNA_CANDIDATO").reindex(list(plan.candidates)).reset_index()
    data = {"rows": chosen, "total": result["total"], "territory": territory, "all": rows}
    trace = _trace(engine, "consultar_votos", plan, VOTES_SOURCE if territory.kind not in {"exterior", "total"} else INFO_SOURCE, "votes",
                   plan.metric or "votos", "votos válidos de todas as candidaturas no território e turno", result["records"],
                   {r.NM_URNA_CANDIDATO: {"votos": int(r.VOTOS), "percentual": r.PERCENTUAL} for r in chosen.itertuples()})
    trace["validacao"] = status
    return data, trace


def consultar_resultado_territorial(engine, plan):
    territory = plan.territories[0]
    result, status = _result(engine, plan, territory)
    top = result["rows"].head(3)
    trace = _trace(engine, "consultar_resultado_territorial", plan, VOTES_SOURCE if territory.kind not in {"exterior", "total"} else INFO_SOURCE,
                   "votes", plan.metric or "resultado", "votos válidos de todas as candidaturas no território e turno", result["records"],
                   {"total_validos": result["total"], "primeiros": {r.NM_URNA_CANDIDATO: int(r.VOTOS) for r in top.itertuples()}})
    trace["validacao"] = status
    return {"rows": result["rows"], "total": result["total"], "territory": territory}, trace


def comparar_candidatos(engine, plan):
    territory = plan.territories[0]
    result, status = _result(engine, plan, territory)
    rows = result["rows"]
    if plan.candidates:
        chosen = rows[rows.NM_URNA_CANDIDATO.isin(plan.candidates)]
    else:  # vencedor contra o segundo colocado
        chosen = rows.head(2)
    chosen = chosen.sort_values(["VOTOS", "NM_URNA_CANDIDATO"], ascending=[False, True]).reset_index(drop=True)
    pairs = []
    for i in range(len(chosen) - 1):
        a, b = chosen.iloc[i], chosen.iloc[i + 1]
        pairs.append({"a": a.NM_URNA_CANDIDATO, "b": b.NM_URNA_CANDIDATO, "votos": int(a.VOTOS - b.VOTOS),
                      "pp": a.PERCENTUAL - b.PERCENTUAL if result["total"] else None,
                      "relativa": 100 * (a.VOTOS - b.VOTOS) / b.VOTOS if b.VOTOS else None})
    trace = _trace(engine, "comparar_candidatos", plan, VOTES_SOURCE if territory.kind not in {"exterior", "total"} else INFO_SOURCE, "votes",
                   plan.metric or "comparacao", "mesmo território, ano e turno; percentuais sobre os votos válidos", result["records"],
                   {"candidaturas": {r.NM_URNA_CANDIDATO: int(r.VOTOS) for r in chosen.itertuples()}, "diferencas": pairs})
    trace["validacao"] = status
    return {"rows": chosen, "pairs": pairs, "total": result["total"], "territory": territory, "all": rows}, trace


def comparar_territorios(engine, plan):
    out, records, statuses = [], 0, []
    candidate = plan.candidates[0] if plan.candidates else None
    for territory in plan.territories:
        result, status = _result(engine, plan, territory)
        statuses.append(status)
        records += result["records"]
        rows = result["rows"]
        entry = {"territory": territory, "total": result["total"], "leaders": rows[rows.POSICAO.eq(1)] if result["total"] else rows.head(0)}
        if candidate:
            row = rows[rows.NM_URNA_CANDIDATO.eq(candidate)].iloc[0]
            entry.update(votos=int(row.VOTOS), percentual=row.PERCENTUAL, posicao=int(row.POSICAO))
        if plan.metric == "eleitores" and territory.kind in PROFILE_SCOPES:
            entry["eleitores"] = engine.electorate(territory, {})["total"]
        out.append(entry)
    trace = _trace(engine, "comparar_territorios", plan, VOTES_SOURCE, "votes", plan.metric or "comparacao_territorial",
                   "votos válidos de cada território (denominadores próprios)", records,
                   {e["territory"].label: {"total_validos": e["total"], **({"votos": e["votos"]} if candidate else {})} for e in out})
    trace["validacao"] = "aprovada" if all(s.startswith("aprovada") for s in statuses) else "falhou"
    return {"rows": out, "candidate": candidate}, trace


def gerar_ranking_municipal(engine, plan):
    scope = plan.scope
    candidate = plan.candidates[0] if plan.candidates else None
    if plan.metric in {"eleitores", "percentual_eleitores"}:
        frame, records = engine.electorate_by_place(scope, plan.categories, plan.level)
        expected = engine.electorate(scope, plan.categories)["count"]
        source, version, denominator = PROFILE_SOURCE, "profile", "eleitores cadastrados de cada município"
    else:
        frame, records = engine.municipal_values(plan.period, scope, candidate, plan.level)
        reference = engine.result(plan.period, scope)
        expected = int(reference["rows"].loc[reference["rows"].NM_URNA_CANDIDATO.eq(candidate), "VOTOS"].sum()) if candidate else reference["total"]
        source, version, denominator = VOTES_SOURCE, "votes", "votos válidos de cada município no turno"
    status = verify_ranking(engine.data, frame, scope, plan.period, expected)
    value = "PERCENTUAL" if plan.metric.startswith("percentual") else "NUMERADOR"
    key = "CD_MUNICIPIO" if plan.level == "municipio" else "SG_UF"
    eligible = frame[frame.DENOMINADOR.gt(0)] if value == "PERCENTUAL" else frame
    ordered = eligible.sort_values([value, key], ascending=[plan.order == "asc", True], na_position="last").reset_index(drop=True)
    ordered["POSICAO"] = ordered[value].rank(method="min", ascending=plan.order == "asc").astype(int)
    if plan.position:
        index = plan.position - 1 if plan.position > 0 else len(ordered) + plan.position
        pick = ordered.iloc[[index]] if 0 <= index < len(ordered) else ordered.head(0)
        rows = ordered[ordered[value].eq(pick[value].iloc[0])] if len(pick) else pick
    else:
        limit = plan.limit or 1
        cut = ordered.head(limit)
        # Empate no último lugar do recorte: inclui todos os empatados.
        rows = ordered[ordered[value].isin(cut[value])] if len(cut) else cut
        rows = rows[rows.POSICAO <= limit]
    trace = _trace(engine, "gerar_ranking_municipal", plan, source, version, plan.metric, denominator, records,
                   {"elegiveis": len(eligible), "linhas": [{key: r[key], "valor": r[value]} for _, r in rows.iterrows()]})
    trace["validacao"] = status
    year = plan.period[0] if plan.period and plan.period[0] in engine.profile_years else engine.profile_years[-1]
    return {"rows": rows, "eligible": len(eligible), "value": value, "candidate": candidate, "scope": scope, "year": year}, trace


def contar_vitorias(engine, plan):
    candidate = plan.candidates[0]
    leaders, records, eligible = engine.winners(plan.period, plan.scope, plan.level)
    mine = leaders[leaders.NM_URNA_CANDIDATO.eq(candidate)]
    wins, ties = int((~mine.EMPATE).sum()), int(mine.EMPATE.sum())
    key = ["SG_UF", "CD_MUNICIPIO"] if plan.level == "municipio" else ["SG_UF"]
    check(not leaders.duplicated(key + ["NM_URNA_CANDIDATO"]).any(), "vencedor duplicado")
    check(wins + ties <= eligible, "vitórias acima do número de territórios")
    trace = _trace(engine, "contar_vitorias", plan, VOTES_SOURCE, "votes", "municipios_com_maior_votacao", "municípios do escopo", records,
                   {"vitorias": wins, "empates_no_topo": ties, "elegiveis": eligible})
    trace["validacao"] = "aprovada"
    return {"wins": wins, "ties": ties, "eligible": eligible, "candidate": candidate, "scope": plan.scope}, trace


def consultar_eleitorado(engine, plan):
    territory = plan.territories[0]
    result = engine.electorate(territory, plan.categories)
    year = plan.period[0] if plan.period else engine.profile_years[-1]
    status = verify_electorate(engine.data, territory, plan.categories, result["count"], result["total"], year)
    trace = _trace(engine, "consultar_eleitorado", plan, PROFILE_SOURCE, "profile", "eleitores_cadastrados",
                   "eleitores cadastrados do território (perfil do eleitorado)", result["records"], {"eleitores": result["count"], "cadastro_total": result["total"]})
    trace["ano"] = year
    trace["validacao"] = status
    return {**result, "territory": territory, "year": year}, trace


def consultar_distribuicao_demografica(engine, plan):
    territory = plan.territories[0]
    result = engine.distribution(territory, plan.dimension, plan.categories)
    rows = result["rows"]
    requested = plan.categories.get(plan.dimension)
    expected = engine.electorate(territory, plan.categories)["count"]
    status = verify_distribution(rows, result["total"], expected)
    if requested:
        rows = rows[rows.CATEGORIA.isin(requested)].set_index("CATEGORIA").reindex(list(requested), fill_value=0).reset_index()
    year = plan.period[0] if plan.period else engine.profile_years[-1]
    trace = _trace(engine, "consultar_distribuicao_demografica", plan, PROFILE_SOURCE, "profile", f"distribuicao_{plan.dimension}",
                   "eleitores cadastrados do recorte", result["records"], {r.CATEGORIA: int(r.QT_ELEITORES) for r in rows.itertuples()})
    trace["ano"] = year
    trace["validacao"] = status
    return {"rows": rows, "total": result["total"], "territory": territory, "dimension": plan.dimension, "year": year}, trace


def consultar_candidaturas(engine, plan):
    table, total = engine.candidates_table(plan.period)
    check(table.NM_URNA_CANDIDATO.is_unique and total == engine.result(plan.period, Territory("brasil"))["total"], "candidaturas não reconciliam com os votos")
    if plan.candidates:
        table = table[table.NM_URNA_CANDIDATO.isin(plan.candidates)]
    trace = _trace(engine, "consultar_candidaturas", plan, INFO_SOURCE, "candidates", plan.metric or "lista", "votos válidos no Brasil, sem exterior",
                   len(table), {"candidaturas": table.NM_URNA_CANDIDATO.tolist()})
    trace["validacao"] = "aprovada"
    return {"rows": table, "total": total}, trace


def contar_municipios(engine, plan):
    territory = plan.territories[0]
    codes = engine.codes(territory)
    check(len(set(codes)) == len(codes), "município duplicado no território")
    gap = engine.ddd_coverage_gap(territory)
    trace = _trace(engine, "contar_municipios", plan, "municipios.parquet · TSE/IBGE/Anatel", "geography", "municipios", "municípios da base",
                   len(codes), {"municipios": len(codes), "sem_ddd_validado_nas_ufs": len(gap)})
    trace["validacao"] = "aprovada"
    return {"count": len(codes), "territory": territory, "gap": gap}, trace


ONE = "1 território: " + ", ".join(sorted(VOTE_SCOPES))
TOOLS = {spec.name: spec for spec in [
    ToolSpec("consultar_votos", "Votos e percentual de candidaturas em um território.",
             {"period": ("(ano, turno)", True, "presente na base"), "candidates": ("tuple[str]", True, "1–12 candidaturas do período"),
              "territories": ("tuple[Territory]", True, ONE)},
             "linhas com votos, percentual sobre os válidos e colocação; total de válidos", VOTES_SOURCE, "somente leitura; 1 território", consultar_votos),
    ToolSpec("consultar_resultado_territorial", "Resultado completo de um território: vencedor, colocações e total de válidos.",
             {"period": ("(ano, turno)", True, "presente na base"), "territories": ("tuple[Territory]", True, ONE)},
             "todas as candidaturas ordenadas", VOTES_SOURCE, "somente leitura", consultar_resultado_territorial),
    ToolSpec("comparar_candidatos", "Diferenças absolutas, em pontos percentuais e relativas no mesmo universo.",
             {"period": ("(ano, turno)", True, "presente na base"), "candidates": ("tuple[str]", False, "0 = dois primeiros; 2–12"),
              "territories": ("tuple[Territory]", True, ONE)}, "candidaturas e pares de diferenças", VOTES_SOURCE, "mesmo território e turno", comparar_candidatos),
    ToolSpec("comparar_territorios", "Mesma métrica e período em 2–6 territórios.",
             {"period": ("(ano, turno)", True, "presente na base"), "territories": ("tuple[Territory]", True, "2–6"), "candidates": ("tuple[str]", False, "0–1")},
             "métricas por território com denominadores próprios", VOTES_SOURCE, f"até {MAX_TERRITORIES} territórios", comparar_territorios),
    ToolSpec("gerar_ranking_municipal", "Ordena todos os municípios (ou UFs) elegíveis do escopo.",
             {"period": ("(ano, turno)", True, "presente na base"), "scope": ("Territory", True, ", ".join(sorted(RANKING_SCOPES))),
              "metric": ("str", True, "votos_candidato | percentual_candidato | votos_validos | eleitores | percentual_eleitores"),
              "limit": ("int", False, f"1–{MAX_LIMIT}"), "position": ("int", False, "posição única"), "order": ("str", False, "desc | asc")},
             "linhas com valor, numerador e denominador; empates no corte incluídos", VOTES_SOURCE + " / " + PROFILE_SOURCE, f"até {MAX_LIMIT} linhas", gerar_ranking_municipal),
    ToolSpec("contar_vitorias", "Municípios em que a candidatura teve a maior votação.",
             {"period": ("(ano, turno)", True, "presente na base"), "candidates": ("tuple[str]", True, "1"), "scope": ("Territory", True, "brasil | uf | ddd")},
             "vitórias, empates no topo e municípios elegíveis", VOTES_SOURCE, "somente leitura", contar_vitorias),
    ToolSpec("consultar_eleitorado", "Eleitores cadastrados de um território, opcionalmente numa interseção de categorias.",
             {"territories": ("tuple[Territory]", True, "1 território do cadastro"), "categories": ("dict[str, tuple[str]]", False, "categorias oficiais")},
             "contagem e cadastro total", PROFILE_SOURCE, "não associa categorias a votos", consultar_eleitorado),
    ToolSpec("consultar_distribuicao_demografica", "Distribuição do cadastro por sexo, identidade de gênero, faixa etária ou escolaridade.",
             {"territories": ("tuple[Territory]", True, "1"), "dimension": ("str", True, ", ".join(DIMENSIONS)), "categories": ("dict", False, "filtros adicionais")},
             "categorias, eleitores e percentuais do recorte", PROFILE_SOURCE, "não associa categorias a votos", consultar_distribuicao_demografica),
    ToolSpec("consultar_candidaturas", "Candidaturas do pleito: número, partido, nome completo e situação na totalização.",
             {"period": ("(ano, turno)", True, "presente na base"), "candidates": ("tuple[str]", False, "filtro opcional")},
             "tabela de candidaturas", INFO_SOURCE, "somente leitura", consultar_candidaturas),
    ToolSpec("contar_municipios", "Quantidade de municípios distintos de um território na base.",
             {"territories": ("tuple[Territory]", True, "1 território do cadastro")}, "contagem e lacunas de DDD", "municipios.parquet",
             "somente leitura", contar_municipios),
]}


def execute(engine, plan):
    """Valida, executa e verifica uma consulta. Falhas viram exceções tipadas, nunca números."""
    validate(engine, plan)
    started = time.perf_counter()
    try:
        data, trace = TOOLS[plan.tool].run(engine, plan)
    except (QueryError, VerificationError):
        LOG.warning("consulta recusada", extra={"ferramenta": plan.tool})
        raise
    except DataUnavailable:
        raise
    except Exception as exc:  # falha de leitura/consulta: não improvisar resultados
        LOG.error("falha na consulta", extra={"ferramenta": plan.tool, "erro": type(exc).__name__})
        raise DataUnavailable(type(exc).__name__) from exc
    trace["duracao_ms"] = round(1000 * (time.perf_counter() - started), 1)
    # Monitoramento técnico: ferramenta, status e duração. Nunca o texto da conversa.
    LOG.info("consulta executada", extra={"ferramenta": plan.tool, "validacao": trace["validacao"], "duracao_ms": trace["duracao_ms"]})
    return ToolResult(plan.tool, data, trace)
