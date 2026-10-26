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
    dimensions: tuple = ()
    factors: dict = field(default_factory=dict)
    hour: int | None = None


# Natureza da informação, registrada em cada consulta e exibida nas respostas.
OFFICIAL, CALCULATION, SIMULATION = "DADO OFICIAL", "CÁLCULO ESTATÍSTICO", "SIMULAÇÃO HIPOTÉTICA"
SIMULATION_WARNING = "SIMULAÇÃO HIPOTÉTICA. NÃO REPRESENTA VOTOS REAIS POR PERFIL DEMOGRÁFICO."
SIMULATION_FORMULA = "votos simulados do grupo = votos oficiais da candidatura × peso do grupo ÷ soma dos pesos; peso = eleitores do grupo ÷ eleitores do recorte (× fator hipotético, no cenário ponderado)"
SIMULATION_HYPOTHESIS = ("Supõe artificialmente a mesma distribuição relativa de votos em todos os grupos (ou a alteração escolhida pelo usuário). "
                         "Não mede preferência, comparecimento, abstenção nem o voto de pessoa alguma: o voto é secreto e os dados públicos não ligam perfil a candidatura.")


def nature(plan):
    if plan.tool == "simular_distribuicao_demografica":
        return SIMULATION
    if plan.tool in {"consultar_candidaturas", "contar_municipios"}:
        return OFFICIAL
    if plan.tool == "consultar_votos":
        return OFFICIAL if plan.metric == "votos" else CALCULATION
    if plan.tool == "consultar_resultado_territorial":
        return OFFICIAL if plan.metric == "total_validos" else CALCULATION
    if plan.tool == "consultar_eleitorado":
        return CALCULATION if plan.metric == "percentual" else OFFICIAL
    if plan.tool == "consultar_horarios":
        return OFFICIAL if plan.metric in {"votos_apos_17h", "ultimo_voto", "faixas"} else CALCULATION
    return CALCULATION


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


def votes_provenance(data, period):
    """Fonte dos votos de um período: arquivo consolidado do TSE ou portal oficial de divulgação."""
    for code, report in data.manifest["sources"].get("divulgacao", {}).get("elections", {}).items():
        if period and (report["ano"], report["turno"]) == tuple(period) and "equivalente_ao_consolidado" not in report:
            return (f"votos_divulgacao.parquet · TSE resultados.tse.jus.br, eleição {code} (divulgação oficial, sem exterior)",
                    f"geração {report['geracao_na_origem']} · sha256 {report['sha256_conjunto'][:12]}")
    return VOTES_SOURCE, _version(data, "votes")


TIMING_SOURCE = "horarios_secoes.parquet · logs oficiais das urnas (TSE), via urnas-tardias e coleta própria"


def _trace(engine, tool, plan, table, version_key, metric, denominator, records, result):
    version = _version(engine.data, version_key)
    if table == VOTES_SOURCE:
        table, version = votes_provenance(engine.data, plan.period)
    if version_key == "timing":
        timing = engine.data.manifest["sources"].get("timing", {})
        version = f"urnas-tardias {timing.get('urnas_tardias', {}).get('commit', '')[:7]} · sha256 {timing.get('urnas_tardias', {}).get('sha256', '')[:12]}"
    return {"ferramenta": tool, "fonte": table, "versao": version, "ano": plan.period[0] if plan.period else None,
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
    if plan.tool == "simular_distribuicao_demografica":
        if not 1 <= len(plan.dimensions) <= 2 or any(d not in DIMENSIONS for d in plan.dimensions) or len(set(plan.dimensions)) != len(plan.dimensions):
            raise QueryError("simulacao_dimensao_invalida")
        if not 1 <= len(plan.candidates) <= 2:
            raise QueryError("simulacao_candidatura_invalida")
        for name, chosen in plan.factors.items():
            if name not in plan.dimensions or any(v not in engine.data.categories[name] or not 0 <= float(f) <= 10 for v, f in chosen.items()):
                raise QueryError("simulacao_fator_invalido")
    if plan.tool in {"consultar_eleitorado", "consultar_distribuicao_demografica", "simular_distribuicao_demografica"} or plan.metric in {"eleitores", "percentual_eleitores"}:
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


def simular_distribuicao_demografica(engine, plan):
    territory = plan.territories[0]
    runs, records = [], 0
    reference = engine.result(plan.period, territory)
    status = verify_result(engine.data, reference, territory, plan.period)
    for candidate in plan.candidates:
        simulation = engine.simulate(plan.period, territory, candidate, plan.dimensions, plan.factors)
        official = int(reference["rows"].loc[reference["rows"].NM_URNA_CANDIDATO.eq(candidate), "VOTOS"].sum())
        verify_simulation(simulation, official, bool(plan.factors))
        records += simulation["records"]
        runs.append({"candidate": candidate, **simulation})
    votes_table, votes_version = votes_provenance(engine.data, plan.period)
    trace = _trace(engine, "simular_distribuicao_demografica", plan, votes_table, "votes", "simulacao_" + "_x_".join(plan.dimensions),
                   "eleitores cadastrados do recorte territorial (composição completa do eleitorado)", records,
                   {r["candidate"]: {"votos_oficiais": r["votes"], "votos_simulados": {" / ".join(map(str, row[list(plan.dimensions)])): int(row.VOTOS_SIMULADOS)
                                                                                       for _, row in r["rows"].iterrows()}} for r in runs})
    trace.update(validacao=status, formula=SIMULATION_FORMULA, hipotese=SIMULATION_HYPOTHESIS, aviso=SIMULATION_WARNING,
                 fontes={"votos_oficiais": f"{votes_table} · {votes_version}", "composicao": f"{PROFILE_SOURCE} · {_version(engine.data, 'profile')}"},
                 cenario="ponderado" if plan.factors else "proporcional", fatores={k: dict(v) for k, v in plan.factors.items()})
    return {"runs": runs, "territory": territory, "dimensions": plan.dimensions, "factors": plan.factors}, trace


def verify_simulation(simulation, official, weighted):
    rows = simulation["rows"]
    check(simulation["votes"] == official, "votos de referência da simulação divergem do resultado oficial")
    check(int(rows.VOTOS_SIMULADOS.sum()) == official, "votos simulados não somam o total oficial da candidatura")
    check(abs(rows.VOTOS_EXATOS.sum() - official) < 1e-6, "soma exata da simulação difere do total oficial")
    check(abs(rows.PARTICIPACAO.sum() - 1) < 1e-9 and (rows.VOTOS_SIMULADOS >= 0).all(), "composição de referência inválida")
    check((rows.VOTOS_SIMULADOS - rows.VOTOS_EXATOS).abs().max() < 1 + 1e-9, "arredondamento fora do método dos maiores restos")
    if not weighted and official:
        check(((rows.VOTOS_EXATOS / official) - rows.PARTICIPACAO).abs().max() < 1e-9, "cenário proporcional não reproduz a composição do eleitorado")


def consultar_horarios(engine, plan):
    territory = plan.scope or plan.territories[0]
    sections = engine.timing_sections(plan.period, territory)
    if sections is None or sections.empty:
        raise QueryError("horarios_indisponiveis", period=plan.period, territory=territory)
    covered, missing = engine.timing_coverage(plan.period, territory)
    if missing:  # um total parcial seria lido como total do recorte
        raise QueryError("horarios_cobertura_parcial", period=plan.period, territory=territory, missing=missing,
                         covered=[engine.kb.city_by_code[c] for c in covered if c in engine.kb.city_by_code])
    status = verify_timing(engine, sections, plan.period, territory)
    hours, covered, total_sections = engine.timing_hours(plan.period, territory)
    if plan.metric in {"faixas", "votos_apos_hora"} and (hours is None or covered < total_sections):
        available = engine.data.timing_hours
        codes = sorted(set(available.loc[available.ANO_ELEICAO.eq(plan.period[0]) & available.NR_TURNO.eq(plan.period[1]), "CD_MUNICIPIO"])) if available is not None else []
        raise QueryError("faixas_indisponiveis", territory=territory, covered=[engine.kb.city_by_code[c] for c in codes if c in engine.kb.city_by_code], period=plan.period)
    timed = sections[sections.ULTIMO_VOTO.ne("")]
    last = timed.sort_values("ULTIMO_VOTO").iloc[-1] if len(timed) else None
    latest = sections.sort_values("ENCERRAMENTO").iloc[-1]
    summary = {"urnas": len(sections), "estendidas": int(sections.ESTENDIDA.sum()), "votos_log": int(sections.VOTOS_LOG.sum()),
               "votos_apos_17h": int(sections.VOTOS_APOS_17H.sum()), "votos_apos_17h20": int(sections.VOTOS_APOS_17H20.sum()),
               "votos_apos_17h_estendidas": int(sections.loc[sections.ESTENDIDA, "VOTOS_APOS_17H"].sum()),
               "urnas_com_voto_apos_17h": int(sections.VOTOS_APOS_17H.gt(0).sum()), "ultimo_voto": last.ULTIMO_VOTO if last is not None else None,
               "ultimo_voto_secao": (last.CD_MUNICIPIO, last.ZONA, last.SECAO) if last is not None else None,
               "ultimo_encerramento": latest.ENCERRAMENTO, "ultimo_encerramento_secao": (latest.CD_MUNICIPIO, latest.ZONA, latest.SECAO),
               "abertura_mediana": sorted(sections.ABERTURA)[len(sections) // 2], "encerramento_mediano": sorted(sections.ENCERRAMENTO)[len(sections) // 2],
               "esperadas": engine.expected_sections(plan.period, territory), "fontes": sorted(sections.FONTE.unique())}
    summary["pct_estendidas"] = 100 * summary["estendidas"] / summary["urnas"]
    data = {"summary": summary, "territory": territory, "hours": hours, "hours_covered": covered, "hours_total": total_sections, "sections": sections}
    if plan.metric == "votos_apos_hora":
        data["after_hour"] = int(hours.loc[hours.HORA.ge(plan.hour or 0), "VOTOS"].sum())
    if plan.metric == "ranking":
        frame = engine.timing_ranking(plan.period, territory, plan.level)
        key = "PCT_ESTENDIDAS" if plan.order == "pct" else "ESTENDIDAS"
        data["ranking"] = frame.sort_values([key, "URNAS"], ascending=[False, False]).head(plan.limit or 5).reset_index(drop=True)
    if plan.metric == "urnas_tardias":
        data["late"] = sections.sort_values(["ENCERRAMENTO", "CD_MUNICIPIO", "ZONA", "SECAO"], ascending=[False, True, True, True]).head(plan.limit or 10)
    trace = _trace(engine, "consultar_horarios", plan, TIMING_SOURCE, "timing", plan.metric or "resumo",
                   "urnas com linha do tempo no recorte (horário de Brasília)", len(sections),
                   {k: v for k, v in summary.items() if k not in {"fontes", "esperadas"}})
    trace["validacao"] = status
    trace["regra_estendida"] = "encerramento a partir de 17h45 (horário de Brasília)"
    return data, trace


def verify_timing(engine, sections, period, territory):
    """Horários vêm dos logs; nenhuma tabela temporal tem coluna de candidatura."""
    for frame in [engine.data.timing, engine.data.timing_hours]:
        check(frame is None or not ({"NM_URNA_CANDIDATO", "NR_CANDIDATO", "SG_PARTIDO"} & set(frame.columns)), "tabela temporal com candidatura")
    check(not sections.duplicated(["CD_MUNICIPIO", "ZONA", "SECAO"]).any(), "seção duplicada nos horários")
    check(sections.ESTENDIDA.eq(sections.ENCERRAMENTO.ge("17:45:00")).all(), "classificação de urna estendida inconsistente")
    check((sections.VOTOS_APOS_17H20 <= sections.VOTOS_APOS_17H).all() and (sections.VOTOS_APOS_17H <= sections.VOTOS_LOG).all(), "contagens de horário inconsistentes")
    hours = engine.data.timing_hours
    if hours is not None:
        own = hours[hours.ANO_ELEICAO.eq(period[0]) & hours.NR_TURNO.eq(period[1])].groupby(["CD_MUNICIPIO", "ZONA", "SECAO"]).VOTOS.sum()
        merged = sections.set_index(["CD_MUNICIPIO", "ZONA", "SECAO"]).VOTOS_LOG.to_frame().join(own.rename("POR_HORA"), how="inner")
        check(merged.VOTOS_LOG.eq(merged.POR_HORA).all(), "faixas horárias não somam os votos computados da seção")
    return "aprovada"


def comparar_turnos(engine, plan):
    territory = plan.territories[0]
    year = plan.period[0]
    frame, turns = engine.compare_turns(year, territory, plan.candidates)
    statuses = [verify_result(engine.data, engine.result((year, t), territory), territory, (year, t)) for t in turns]
    check(len(turns) >= 2, "comparação exige dois turnos")
    finalists = set(frame.loc[frame.NR_TURNO.eq(max(turns)), "NM_URNA_CANDIDATO"])
    chosen = list(plan.candidates) or sorted(finalists, key=lambda k: -int(frame[(frame.NR_TURNO == max(turns)) & (frame.NM_URNA_CANDIDATO == k)].VOTOS.iloc[0]))
    rows = []
    for candidate in chosen:
        values = {t: frame[(frame.NR_TURNO == t) & (frame.NM_URNA_CANDIDATO == candidate)] for t in turns}
        if any(v.empty for v in values.values()):
            raise QueryError("candidato_fora_do_pleito", candidate=candidate, period=(year, next(t for t, v in values.items() if v.empty)))
        first, second = values[min(turns)].iloc[0], values[max(turns)].iloc[0]
        rows.append({"candidate": candidate, "votos_1": int(first.VOTOS), "pct_1": first.PERCENTUAL, "votos_2": int(second.VOTOS), "pct_2": second.PERCENTUAL,
                     "dif_votos": int(second.VOTOS - first.VOTOS), "dif_pp": second.PERCENTUAL - first.PERCENTUAL})
    totals = frame.groupby("NR_TURNO").TOTAL_VALIDOS.first().to_dict()
    trace = _trace(engine, "comparar_turnos", plan, VOTES_SOURCE, "votes", "comparacao_entre_turnos",
                   "votos válidos de cada turno no mesmo território (denominadores próprios)", len(frame),
                   {r["candidate"]: {k: r[k] for k in ["votos_1", "votos_2", "dif_votos"]} for r in rows})
    trace["fonte"] = " + ".join(dict.fromkeys(votes_provenance(engine.data, (year, t))[0] for t in turns))
    trace["validacao"] = "aprovada" if all(s.startswith("aprovada") for s in statuses) else "falhou"
    return {"rows": rows, "territory": territory, "turns": turns, "totals": totals, "year": year}, trace


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
    ToolSpec("simular_distribuicao_demografica", "SIMULAÇÃO HIPOTÉTICA: distribui os votos oficiais de 1–2 candidaturas pela composição do eleitorado.",
             {"period": ("(ano, turno)", True, "presente na base"), "candidates": ("tuple[str]", True, "1–2"), "territories": ("tuple[Territory]", True, "1 território do cadastro"),
              "dimensions": ("tuple[str]", True, "1–2 de " + ", ".join(DIMENSIONS) + "; duas usam a distribuição conjunta oficial"),
              "factors": ("dict[str, dict[str, float]]", False, "fatores hipotéticos 0–10 por categoria (cenário ponderado)")},
             "votos simulados (inteiros por maiores restos), exatos, participação e pesos", f"{VOTES_SOURCE} + {PROFILE_SOURCE}",
             "nunca é dado real: resultado sempre rotulado como SIMULAÇÃO HIPOTÉTICA", simular_distribuicao_demografica),
    ToolSpec("consultar_horarios", "Linha do tempo das urnas: abertura, encerramento, último voto, votos após 17h, urnas estendidas, votos por hora.",
             {"period": ("(ano, turno)", True, "turno com logs integrados"), "territories": ("tuple[Territory]", True, "1 território"),
              "metric": ("str", False, "resumo | votos_apos_17h | estendidas | ultimo_voto | faixas | ranking | urnas_tardias"), "level": ("str", False, "uf | municipio")},
             "resumo por urna e, quando coletado, votos por hora", TIMING_SOURCE, "não associa horários a candidaturas", consultar_horarios),
    ToolSpec("comparar_turnos", "Votos e percentual das candidaturas em cada turno, no mesmo território.",
             {"period": ("(ano, turno final)", True, "ano com dois turnos"), "territories": ("tuple[Territory]", True, "1"), "candidates": ("tuple[str]", False, "finalistas por padrão")},
             "votos, percentuais e variações por candidatura", VOTES_SOURCE, "denominador próprio de cada turno", comparar_turnos),
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
    trace["natureza"] = nature(plan)
    # Monitoramento técnico: ferramenta, status e duração. Nunca o texto da conversa.
    LOG.info("consulta executada", extra={"ferramenta": plan.tool, "validacao": trace["validacao"], "duracao_ms": trace["duracao_ms"]})
    return ToolResult(plan.tool, data, trace)
