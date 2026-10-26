"""Motor estatístico determinístico sobre as bases preparadas.

Votos (resultado por candidatura e município) e cadastro (perfil do eleitorado)
são conjuntos distintos: nenhuma função aqui cruza votos com categorias demográficas.
"""
from __future__ import annotations

from functools import lru_cache
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

    def candidates_table(self, period):
        year, turn = period
        info = self.info[self.info.ANO_ELEICAO.eq(year) & self.info.NR_TURNO.eq(turn)].copy()
        total = int(info.VOTOS_BRASIL.sum())
        info["PERCENTUAL"] = 100 * info.VOTOS_BRASIL / total if total else float("nan")
        return info.sort_values(["VOTOS_BRASIL", "NM_URNA_CANDIDATO"], ascending=[False, True]).reset_index(drop=True), total


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
