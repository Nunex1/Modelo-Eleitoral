"""Contrato analítico compartilhado pelo dashboard, exportações e conversa."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "dados/tratados/lampiadim"
ASSETS = Path(__file__).resolve().parents[1] / "assets"
DIMENSIONS = {"sexo": "DS_GENERO", "identidade": "DS_IDENTIDADE_GENERO", "idade": "DS_FAIXA_ETARIA", "escolaridade": "DS_GRAU_ESCOLARIDADE"}
STATE_CODES = dict(zip("RO AC AM RR PA AP TO MA PI CE RN PB PE AL SE BA MG ES RJ SP PR SC RS MS MT GO DF".split(), "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split()))


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c)).upper()).split())


def integer(value):
    return f"{int(value):,}".replace(",", ".")


def percent(value):
    return "Indisponível" if value is None or pd.isna(value) else f"{value:.2f}%".replace(".", ",")


@dataclass(frozen=True)
class Filters:
    year: int = 2026
    turn: int = 1
    uf: str = ""
    municipality: str = ""
    ddd: int | None = None
    candidate: str = ""
    sexo: str = ""
    identidade: str = ""
    idade: str = ""
    escolaridade: str = ""


class ElectoralData:
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        missing = [name for name in ["manifest.json", "votos.parquet", "perfil.parquet", "municipios.parquet"] if not (self.directory / name).exists()]
        if missing:
            raise FileNotFoundError("Dados preparados ausentes: " + ", ".join(missing) + ". Execute scripts/preparar_dados.py na raiz do projeto.")
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in self.manifest["outputs"].items():
            with (self.directory / name).open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != expected:
                    raise ValueError(f"O arquivo {name} foi alterado após a preparação. Reprocesse os dados.")
        self.votes = pd.read_parquet(self.directory / "votos.parquet")
        self.profile = pd.read_parquet(self.directory / "perfil.parquet")
        self.towns = pd.read_parquet(self.directory / "municipios.parquet")
        self.towns["CD_MUNICIPIO"] = self.towns.CD_MUNICIPIO.astype(str)
        self.votes["CD_MUNICIPIO"] = self.votes.CD_MUNICIPIO.astype(str)
        self.profile["CD_MUNICIPIO"] = self.profile.CD_MUNICIPIO.astype("category")
        self.years = sorted(self.votes.ANO_ELEICAO.unique().tolist())
        self.states = dict(self.towns[["SG_UF", "estado"]].dropna().drop_duplicates().itertuples(index=False, name=None))
        self.candidates = sorted(self.votes.NM_URNA_CANDIDATO.unique().tolist())
        self.categories = {name: sorted(self.profile[col].dropna().unique().tolist()) for name, col in DIMENSIONS.items()}
        self.city_records = self.towns.assign(NORMAL=self.towns.NM_MUNICIPIO.map(normalize)).to_dict("records")

    def turns(self, year):
        return sorted(self.votes.loc[self.votes.ANO_ELEICAO.eq(year), "NR_TURNO"].unique().tolist())

    def validate(self, filters):
        if filters.year not in self.years or filters.turn not in self.turns(filters.year):
            raise ValueError("Ano ou turno não disponível nesta base local.")
        if filters.uf and filters.uf not in self.states:
            raise ValueError("Estado não disponível.")
        if filters.candidate and filters.candidate not in self.candidates:
            raise ValueError("Candidatura não disponível.")
        for key in DIMENSIONS:
            value = getattr(filters, key)
            if value and value not in self.categories[key]:
                raise ValueError(f"Categoria de {key} não disponível.")
        if filters.ddd is not None and filters.ddd not in self.towns.DDD.dropna().tolist():
            raise ValueError("DDD sem correspondência validada na base.")
        if filters.municipality and filters.municipality not in self.towns.CD_MUNICIPIO.tolist():
            raise ValueError("Município não disponível.")

    def geography(self, filters):
        towns = self.towns
        if filters.uf:
            towns = towns[towns.SG_UF.eq(filters.uf)]
        if filters.ddd is not None:
            towns = towns[towns.DDD.eq(filters.ddd).fillna(False)]
        if filters.municipality:
            towns = towns[towns.CD_MUNICIPIO.eq(filters.municipality)]
        return towns

    def frames(self, filters):
        self.validate(filters)
        towns = self.geography(filters)
        codes = towns.CD_MUNICIPIO
        v = self.votes[self.votes.ANO_ELEICAO.eq(filters.year) & self.votes.NR_TURNO.eq(filters.turn) & self.votes.CD_MUNICIPIO.isin(codes)]
        p = self.profile[self.profile.AA_ELEICAO.eq(filters.year) & self.profile.CD_MUNICIPIO.isin(codes)]
        selected = p
        for name, column in DIMENSIONS.items():
            value = getattr(filters, name)
            if value:
                selected = selected[selected[column].eq(value)]
        return v, p, selected

    def scope(self, filters):
        if filters.municipality:
            rows = self.towns[self.towns.CD_MUNICIPIO.eq(filters.municipality)]
            label = f"{rows.iloc[0].NM_MUNICIPIO.title()} · {rows.iloc[0].SG_UF}" if len(rows) else "Município indisponível"
        else:
            label = self.states.get(filters.uf, "Brasil · sem exterior")
        return label + (f" · DDD {filters.ddd}" if filters.ddd else "")

    @lru_cache(maxsize=64)
    def query(self, filters):
        v, p, selected = self.frames(filters)
        total = int(v.VOTOS.sum())
        candidates = v.groupby(["NM_URNA_CANDIDATO", "SG_PARTIDO"], observed=True, as_index=False).VOTOS.sum().sort_values(["VOTOS", "NM_URNA_CANDIDATO"], ascending=[False, True])
        candidates["PERCENTUAL"] = 100 * candidates.VOTOS / total if total else float("nan")
        shown = candidates[candidates.NM_URNA_CANDIDATO.eq(filters.candidate)] if filters.candidate else candidates
        difference = int(candidates.iloc[0].VOTOS - candidates.iloc[1].VOTOS) if len(candidates) >= 2 else None
        demographics = {}
        population = int(selected.QT_ELEITORES.sum())
        for name, col in DIMENSIONS.items():
            table = selected.groupby(col, observed=True, as_index=False).QT_ELEITORES.sum().rename(columns={col: "CATEGORIA"})
            table["CATEGORIA"] = table.CATEGORIA.astype(str)
            table["PERCENTUAL"] = 100 * table.QT_ELEITORES / population if population else float("nan")
            if name == "idade":
                table = table.sort_values("CATEGORIA", key=lambda s: s.map(lambda x: int(re.search(r"\d+", x).group()) if re.search(r"\d+", x) else 999))
            else:
                table = table.sort_values("QT_ELEITORES", ascending=False)
            demographics[name] = table
        return {"scope": self.scope(filters), "period": f"{filters.year} · {filters.turn}º turno", "votes": total, "registered": int(p.QT_ELEITORES.sum()), "selected_profile": population, "municipalities": len(self.geography(filters)), "candidates": shown, "all_candidates": candidates, "difference": difference, "difference_pp": 100 * difference / total if difference is not None and total else None, "demographics": demographics, "filters": filters}

    def analytical_table(self, filters):
        v, _, _ = self.frames(filters)
        table = v.copy()
        totals = table.groupby(["SG_UF", "CD_MUNICIPIO"], observed=True).VOTOS.transform("sum")
        table["PERCENTUAL"] = (100 * table.VOTOS / totals).where(totals.gt(0))
        if filters.candidate:
            table = table[table.NM_URNA_CANDIDATO.eq(filters.candidate)]
        table = table.merge(self.towns[["SG_UF", "CD_MUNICIPIO", "DDD"]], on=["SG_UF", "CD_MUNICIPIO"], how="left", validate="many_to_one")
        return table.rename(columns={"ANO_ELEICAO": "Ano", "NR_TURNO": "Turno", "SG_UF": "UF", "CD_MUNICIPIO": "Código TSE", "NM_MUNICIPIO": "Município", "NM_URNA_CANDIDATO": "Candidatura", "SG_PARTIDO": "Partido", "VOTOS": "Votos", "PERCENTUAL": "% válidos", "NR_CANDIDATO": "Número"})

    def map_values(self, filters, level):
        v, _, _ = self.frames(filters)
        group = "SG_UF" if level == "uf" else "CD_MUNICIPIO"
        total = v.groupby(group, observed=True).VOTOS.sum()
        chosen = v[v.NM_URNA_CANDIDATO.eq(filters.candidate)] if filters.candidate else v
        value = chosen.groupby(group, observed=True).VOTOS.sum().reindex(total.index, fill_value=0)
        if filters.candidate:
            value = (100 * value / total).where(total.gt(0))
        return value.to_dict()


def csv_bytes(frame):
    """Excel pt-BR: BOM, ponto e vírgula, decimal local e neutralização de fórmulas."""
    export = frame.copy()
    for column in export.select_dtypes(include=["object", "str", "category"]).columns:
        export[column] = export[column].map(lambda x: "'" + x if isinstance(x, str) and x.lstrip().startswith(("=", "+", "-", "@")) else x)
    return export.to_csv(index=False, sep=";", decimal=",", lineterminator="\n").encode("utf-8-sig")


def reset_demographics(filters):
    return replace(filters, sexo="", identidade="", idade="", escolaridade="")
