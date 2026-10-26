"""Motor estatístico determinístico sobre as bases preparadas.

Votos (resultado por candidatura e município) e cadastro (perfil do eleitorado)
são conjuntos distintos. A única função que combina os dois é ``simulate``, um
cenário matemático HIPOTÉTICO, sempre identificado como tal; nenhuma outra cruza
votos com categorias demográficas. Horários de urna nunca são ligados a candidaturas.
"""
from __future__ import annotations

from functools import lru_cache
import math
import re

import pandas as pd

from .data import DIMENSIONS
from .entities import REGIONS, KnowledgeBase, Territory


class DataUnavailable(RuntimeError):
    """A base não pôde ser lida ou consultada; nenhum número deve ser apresentado."""


def age_bounds(band):
    numbers = [int(n) for n in re.findall(r"\d+", band)]
    if not numbers:
        return None
    if "mais" in band:
        return numbers[0], 200
    return numbers[0], numbers[-1]


class Engine:
    def __init__(self, data):
        try:
            self.data = data
            self.kb = KnowledgeBase(data)
            votes = data.votes
            if votes.duplicated(["ANO_ELEICAO", "NR_TURNO", "CD_MUNICIPIO", "NM_URNA_CANDIDATO"]).any():
                raise DataUnavailable("Votos duplicados por município e candidatura")
            self.votes = votes
            self.totals = votes.groupby(["ANO_ELEICAO", "NR_TURNO", "CD_MUNICIPIO"]).VOTOS.sum()
            self.profile = data.profile
            self.towns = data.towns
            self.profile_years = sorted(int(y) for y in self.profile.AA_ELEICAO.unique())
            self.age_bands = {band: age_bounds(band) for band in data.categories["idade"]}
            self.info = data.candidate_info
            self._by_dimension = {}
        except DataUnavailable:
            raise
        except Exception as exc:  # base corrompida ou ausente
            raise DataUnavailable(str(exc)) from exc

    # ------------------------------------------------------------------ territórios
    @lru_cache(maxsize=256)
    def codes(self, territory: Territory):
        towns = self.towns
        if territory.kind in {"brasil", "total"}:
            return tuple(towns.CD_MUNICIPIO)
        if territory.kind == "uf":
            return tuple(towns.loc[towns.SG_UF.eq(territory.code), "CD_MUNICIPIO"])
        if territory.kind == "regiao":
            return tuple(towns.loc[towns.SG_UF.isin(REGIONS[territory.code][1]), "CD_MUNICIPIO"])
        if territory.kind == "ddd":
            return tuple(towns.loc[towns.DDD.eq(int(territory.code)).fillna(False), "CD_MUNICIPIO"])
        if territory.kind == "municipio":
            return tuple(towns.loc[towns.CD_MUNICIPIO.eq(territory.code), "CD_MUNICIPIO"])
        return ()

    def ddd_coverage_gap(self, territory):
        """Municípios sem DDD validado nas UFs que o DDD abrange (cobertura parcial)."""
        if territory.kind != "ddd":
            return []
        ufs = set(self.towns.loc[self.towns.DDD.eq(int(territory.code)).fillna(False), "SG_UF"])
        return [r for r in self.data.manifest["sources"]["geography"]["unavailable"] if r["SG_UF"] in ufs]

    # ------------------------------------------------------------------ votos
    def _period_votes(self, period):
        year, turn = period
        return self.votes[self.votes.ANO_ELEICAO.eq(year) & self.votes.NR_TURNO.eq(turn)]

    def result(self, period, territory):
        """Votos por candidatura no território, com percentual sobre os votos válidos e colocação."""
        year, turn = period
        if territory.kind in {"exterior", "total"}:
            info = self.info[self.info.ANO_ELEICAO.eq(year) & self.info.NR_TURNO.eq(turn)]
            if "VOTOS_EXTERIOR" not in info:
                raise DataUnavailable("Votos do exterior não preparados")
            column = info.VOTOS_EXTERIOR if territory.kind == "exterior" else info.VOTOS_BRASIL + info.VOTOS_EXTERIOR
            rows = pd.DataFrame({"NM_URNA_CANDIDATO": info.NM_URNA_CANDIDATO, "SG_PARTIDO": info.SG_PARTIDO, "VOTOS": column.astype("int64")})
            records, municipalities = len(info), 0
        else:
            codes = self.codes(territory)
            v = self._period_votes(period)
            v = v[v.CD_MUNICIPIO.isin(codes)]
            rows = v.groupby(["NM_URNA_CANDIDATO", "SG_PARTIDO"], as_index=False).VOTOS.sum()
            records, municipalities = len(v), len(codes)
        total = int(rows.VOTOS.sum())
        rows = rows.sort_values(["VOTOS", "NM_URNA_CANDIDATO"], ascending=[False, True]).reset_index(drop=True)
        rows["PERCENTUAL"] = (100 * rows.VOTOS / total) if total else float("nan")
        rows["POSICAO"] = rows.VOTOS.rank(method="min", ascending=False).astype(int)
        return {"rows": rows, "total": total, "municipalities": municipalities, "records": records}

    def municipal_values(self, period, scope, candidate=None, level="municipio"):
        """Votos de uma candidatura (ou válidos totais) por município/UF do escopo, com denominadores."""
        year, turn = period
        codes = self.codes(scope)
        v = self._period_votes(period)
        v = v[v.CD_MUNICIPIO.isin(codes)]
        group = ["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"] if level == "municipio" else ["SG_UF"]
        total = v.groupby(group, as_index=False).VOTOS.sum().rename(columns={"VOTOS": "DENOMINADOR"})
        if candidate:
            chosen = v[v.NM_URNA_CANDIDATO.eq(candidate)].groupby(group, as_index=False).VOTOS.sum().rename(columns={"VOTOS": "NUMERADOR"})
            frame = total.merge(chosen, on=group, how="left", validate="one_to_one")
            frame["NUMERADOR"] = frame.NUMERADOR.fillna(0).astype("int64")
        else:
            frame = total.assign(NUMERADOR=total.DENOMINADOR)
        frame["PERCENTUAL"] = (100 * frame.NUMERADOR / frame.DENOMINADOR).where(frame.DENOMINADOR.gt(0))
        return frame, len(v)

    def winners(self, period, scope, level="municipio"):
        """Primeiro colocado por município (ou UF); empates no topo ficam identificados."""
        codes = self.codes(scope)
        v = self._period_votes(period)
        v = v[v.CD_MUNICIPIO.isin(codes)]
        group = ["SG_UF", "CD_MUNICIPIO"] if level == "municipio" else ["SG_UF"]
        agg = v.groupby(group + ["NM_URNA_CANDIDATO"], as_index=False).VOTOS.sum()
        top = agg.groupby(group).VOTOS.transform("max")
        leaders = agg[agg.VOTOS.eq(top) & top.gt(0)]
        counts = leaders.groupby(group).NM_URNA_CANDIDATO.transform("size")
        return leaders.assign(EMPATE=counts.gt(1)), len(v), (len(codes) if level == "municipio" else agg.SG_UF.nunique())

    # ------------------------------------------------------------------ cadastro
    def _profile_mask(self, territory, categories):
        if territory.kind in {"exterior"}:
            raise DataUnavailable("O cadastro preparado não inclui o exterior")
        p = self.profile
        mask = p.CD_MUNICIPIO.isin(self.codes(territory)) if territory.kind not in {"brasil", "total"} else pd.Series(True, index=p.index)
        for name, values in categories.items():
            if values:
                mask &= p[DIMENSIONS[name]].isin(list(values))
        return mask

    def electorate(self, territory, categories):
        p = self.profile
        mask = self._profile_mask(territory, categories)
        selected = int(p.loc[mask, "QT_ELEITORES"].sum())
        base = self._profile_mask(territory, {})
        return {"count": selected, "total": int(p.loc[base, "QT_ELEITORES"].sum()), "records": int(mask.sum())}

    def distribution(self, territory, dimension, categories):
        p = self.profile
        column = DIMENSIONS[dimension]
        mask = self._profile_mask(territory, categories)
        table = p.loc[mask].groupby(column, observed=True).QT_ELEITORES.sum().reset_index().rename(columns={column: "CATEGORIA"})
        table["CATEGORIA"] = table.CATEGORIA.astype(str)
        total = int(table.QT_ELEITORES.sum())
        table["PERCENTUAL"] = (100 * table.QT_ELEITORES / total) if total else float("nan")
        if dimension == "idade":
            table = table.assign(_k=table.CATEGORIA.map(lambda b: (self.age_bands.get(b) or (999,))[0])).sort_values("_k").drop(columns="_k")
        else:
            table = table.sort_values(["QT_ELEITORES", "CATEGORIA"], ascending=[False, True])
        return {"rows": table.reset_index(drop=True), "total": total, "records": int(mask.sum())}

    def electorate_by_place(self, scope, categories, level="municipio"):
        """Eleitores (na interseção de categorias) e cadastro total por município/UF do escopo."""
        p = self.profile
        base = self._profile_mask(scope, {})
        mask = self._profile_mask(scope, categories)
        key = ["CD_MUNICIPIO"] if level == "municipio" else ["SG_UF"]
        total = p.loc[base].groupby(key, observed=True).QT_ELEITORES.sum().rename("DENOMINADOR")
        part = p.loc[mask].groupby(key, observed=True).QT_ELEITORES.sum().rename("NUMERADOR")
        frame = pd.concat([total, part], axis=1).fillna(0).astype("int64").reset_index()
        frame[key[0]] = frame[key[0]].astype(str)
        if level == "municipio":
            frame = frame.merge(self.towns[["CD_MUNICIPIO", "SG_UF", "NM_MUNICIPIO"]], on="CD_MUNICIPIO", how="left", validate="one_to_one")
        frame["PERCENTUAL"] = (100 * frame.NUMERADOR / frame.DENOMINADOR).where(frame.DENOMINADOR.gt(0))
        return frame, int(mask.sum())

    # ------------------------------------------------------------------ simulação hipotética
    def composition(self, territory, dimensions):
        """Composição oficial do eleitorado do território; com mais de uma dimensão, a distribuição conjunta do cadastro."""
        columns = [DIMENSIONS[d] for d in dimensions]
        mask = self._profile_mask(territory, {})
        table = self.profile.loc[mask].groupby(columns, observed=True).QT_ELEITORES.sum().reset_index()
        for column in columns:
            table[column] = table[column].astype(str)
        table = table[table.QT_ELEITORES.gt(0)].rename(columns={DIMENSIONS[d]: d for d in dimensions})
        total = int(table.QT_ELEITORES.sum())
        table["PARTICIPACAO"] = table.QT_ELEITORES / total if total else float("nan")
        if len(dimensions) == 1 and dimensions[0] == "idade":
            table = table.assign(_k=table.idade.map(lambda b: (self.age_bands.get(b) or (999,))[0])).sort_values("_k").drop(columns="_k")
        else:
            table = table.sort_values("QT_ELEITORES", ascending=False)
        return table.reset_index(drop=True), total, int(mask.sum())

    def simulate(self, period, territory, candidate, dimensions, factors=None):
        """Distribuição HIPOTÉTICA dos votos oficiais de uma candidatura pela composição do eleitorado.

        Proporcional: votos_g = V × eleitores_g ÷ eleitores. Ponderado: votos_g = V × (p_g × f_g) ÷ Σ(p × f).
        Não mede o voto de nenhum grupo: supõe a mesma distribuição relativa em todos os grupos.
        """
        result = self.result(period, territory)
        rows = result["rows"]
        votes = int(rows.loc[rows.NM_URNA_CANDIDATO.eq(candidate), "VOTOS"].sum())
        table, electorate, records = self.composition(territory, dimensions)
        weight = table.PARTICIPACAO.astype(float).copy()
        for name, chosen in (factors or {}).items():
            if name in table:
                weight = weight * table[name].map(lambda value: float(chosen.get(value, 1.0)))
        if not electorate or weight.sum() <= 0:
            raise ValueError("Sem eleitorado de referência ou pesos válidos para a simulação")
        table["PESO"] = weight
        table["VOTOS_EXATOS"] = votes * weight / weight.sum()
        table["VOTOS_SIMULADOS"] = largest_remainder(table.VOTOS_EXATOS, votes)
        return {"rows": table, "votes": votes, "electorate": electorate, "records": records + result["records"], "official_total": result["total"]}

    # ------------------------------------------------------------------ horários das urnas
    def timing_sections(self, period, territory):
        timing = self.data.timing
        if timing is None:
            return None
        year, turn = period
        rows = timing[timing.ANO_ELEICAO.eq(year) & timing.NR_TURNO.eq(turn)]
        if territory.kind not in {"brasil", "total"}:
            rows = rows[rows.CD_MUNICIPIO.isin(self.codes(territory))]
        return rows

    def timing_coverage(self, period, territory):
        """Municípios do recorte com registros de horário e quantos, com seções totalizadas, ficaram sem nenhum."""
        timing = self.data.timing
        year, turn = period
        logged = set(timing.loc[timing.ANO_ELEICAO.eq(year) & timing.NR_TURNO.eq(turn), "CD_MUNICIPIO"]) if timing is not None else set()
        codes = set(self.codes(territory))
        totals = self.data.totalization
        if totals is not None:
            rows = totals[totals.ANO_ELEICAO.eq(year) & totals.NR_TURNO.eq(turn) & totals.SECOES_TOTALIZADAS.gt(0)]
            if len(rows):
                codes &= set(rows.CD_MUNICIPIO)
        return sorted(codes & logged), len(codes - logged)

    def totalization(self, period, territory):
        """Totais oficiais da totalização (aptos, comparecimento, abstenção, brancos, nulos), sem exterior."""
        totals = self.data.totalization
        if totals is None:
            return None
        year, turn = period
        rows = totals[totals.ANO_ELEICAO.eq(year) & totals.NR_TURNO.eq(turn) & totals.SG_UF.ne("ZZ")]
        if territory.kind not in {"brasil", "total"}:
            rows = rows[rows.CD_MUNICIPIO.isin(self.codes(territory))]
        if not len(rows):
            return None
        columns = ["SECOES", "SECOES_TOTALIZADAS", "ELEITORADO_APTO", "COMPARECIMENTO", "ABSTENCAO", "VOTOS_VALIDOS", "VOTOS_BRANCOS", "VOTOS_NULOS"]
        return {name: int(rows[name].sum()) for name in columns} | {"final": bool(rows.TOTALIZACAO_FINAL.all())}

    def expected_sections(self, period, territory):
        """Seções totalizadas pela divulgação do TSE no território (denominador de cobertura)."""
        totals = self.totalization(period, territory)
        return {"secoes": totals["SECOES_TOTALIZADAS"], "comparecimento": totals["COMPARECIMENTO"]} if totals else None

    def timing_hours(self, period, territory):
        """Votos computados por hora de Brasília, somente se todas as seções do recorte têm a linha do tempo completa."""
        hours = self.data.timing_hours
        sections = self.timing_sections(period, territory)
        if hours is None or sections is None or sections.empty:
            return None, 0, 0 if sections is None else len(sections)
        year, turn = period
        rows = hours[hours.ANO_ELEICAO.eq(year) & hours.NR_TURNO.eq(turn)]
        if territory.kind not in {"brasil", "total"}:
            rows = rows[rows.CD_MUNICIPIO.isin(self.codes(territory))]
        covered = rows[["CD_MUNICIPIO", "ZONA", "SECAO"]].drop_duplicates()
        if not len(covered):
            return None, 0, len(sections)
        table = rows.groupby("HORA", as_index=False).VOTOS.sum().sort_values("HORA")
        return table, len(covered), len(sections)

    def timing_ranking(self, period, scope, level):
        sections = self.timing_sections(period, scope)
        key = ["SG_UF"] if level == "uf" else ["SG_UF", "CD_MUNICIPIO"]
        frame = sections.assign(COM_VOTO_APOS_17H=sections.VOTOS_APOS_17H.gt(0)).groupby(key, as_index=False).agg(
            URNAS=("SECAO", "size"), ESTENDIDAS=("ESTENDIDA", "sum"), VOTOS_APOS_17H=("VOTOS_APOS_17H", "sum"), VOTOS_LOG=("VOTOS_LOG", "sum"),
            ULTIMO_ENCERRAMENTO=("ENCERRAMENTO", "max"))
        frame["PCT_ESTENDIDAS"] = 100 * frame.ESTENDIDAS / frame.URNAS
        return frame

    # ------------------------------------------------------------------ comparação entre turnos
    def compare_turns(self, year, territory, candidates=()):
        turns = [t for (y, t) in self.kb.periods if y == year]
        rows = []
        for turn in turns:
            result = self.result((year, turn), territory)
            for r in result["rows"].itertuples():
                if not candidates or r.NM_URNA_CANDIDATO in candidates:
                    rows.append({"NR_TURNO": turn, "NM_URNA_CANDIDATO": r.NM_URNA_CANDIDATO, "VOTOS": int(r.VOTOS), "PERCENTUAL": r.PERCENTUAL,
                                 "TOTAL_VALIDOS": result["total"]})
        return pd.DataFrame(rows), turns

    def candidates_table(self, period):
        year, turn = period
        info = self.info[self.info.ANO_ELEICAO.eq(year) & self.info.NR_TURNO.eq(turn)].copy()
        total = int(info.VOTOS_BRASIL.sum())
        info["PERCENTUAL"] = 100 * info.VOTOS_BRASIL / total if total else float("nan")
        return info.sort_values(["VOTOS_BRASIL", "NM_URNA_CANDIDATO"], ascending=[False, True]).reset_index(drop=True), total


def largest_remainder(exact, total):
    """Inteiros que somam ``total`` preservando a proporção (método dos maiores restos)."""
    exact = pd.Series(exact, dtype="float64")
    floors = exact.map(math.floor).astype("int64")
    missing = int(total - floors.sum())
    if missing:
        remainders = (exact - floors).sort_values(ascending=False, kind="mergesort")
        floors.loc[remainders.index[:missing]] += 1
    return floors


def engine_for(data):
    """Um motor por base carregada (as agregações ficam em memória junto aos dados)."""
    if data is None:
        raise DataUnavailable("Base eleitoral não carregada")
    engine = getattr(data, "_lampiadim_engine", None)
    if engine is None:
        engine = Engine(data)
        try:
            data._lampiadim_engine = engine
        except AttributeError:
            pass
    return engine
