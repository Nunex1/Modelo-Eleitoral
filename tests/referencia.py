"""Consultas de referência independentes do assistente.

Calculadas diretamente dos CSVs originais do notebook (votação e perfil por sexo) e,
para idade/escolaridade/DDD, dos derivados preparados lidos com Pandas puro. Os
valores esperados dos testes e da avaliação vêm daqui, nunca de um modelo de linguagem.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def br(value):
    return f"{int(value):,}".replace(",", ".")


def pct(value, places=1):
    return f"{value:.{places}f}".replace(".", ",") + "%"


class Reference:
    def __init__(self):
        votes = pd.read_csv(ROOT / "Lampiadim_MVP/resultado_presidencial_2026_brasil.csv", dtype={"CD_MUNICIPIO": str})
        votes["CD_MUNICIPIO"] = votes.CD_MUNICIPIO.str.zfill(5)
        profile = pd.read_csv(ROOT / "Lampiadim_MVP/perfil_demografico_municipios_2026.csv", dtype={"CD_MUNICIPIO": str})
        profile["CD_MUNICIPIO"] = profile.CD_MUNICIPIO.str.zfill(5)
        self.votes, self.profile = votes, profile
        self.towns = pd.read_parquet(ROOT / "dados/tratados/lampiadim/municipios.parquet")

    def code(self, name, uf):
        rows = self.votes[(self.votes.NM_MUNICIPIO == name) & (self.votes.SG_UF == uf)]
        return rows.CD_MUNICIPIO.iloc[0]

    def candidate_votes(self, candidate, code=None, uf=None):
        v = self.votes[self.votes.NM_URNA_CANDIDATO == candidate]
        if code:
            v = v[v.CD_MUNICIPIO == code]
        if uf:
            v = v[v.SG_UF == uf]
        return int(v.VOTOS.sum())

    def valid(self, code=None, uf=None):
        v = self.votes
        if code:
            v = v[v.CD_MUNICIPIO == code]
        if uf:
            v = v[v.SG_UF == uf]
        return int(v.VOTOS.sum())

    def share(self, candidate, code=None, uf=None):
        return 100 * self.candidate_votes(candidate, code, uf) / self.valid(code, uf)

    def ranking(self, candidate, uf=None, n=5):
        v = self.votes[self.votes.NM_URNA_CANDIDATO == candidate]
        if uf:
            v = v[v.SG_UF == uf]
        return v.sort_values(["VOTOS", "CD_MUNICIPIO"], ascending=[False, True]).head(n)[["CD_MUNICIPIO", "NM_MUNICIPIO", "SG_UF", "VOTOS"]]

    def electorate(self, code=None, sexo=None, codes=None, uf=None):
        p = self.profile
        if code:
            p = p[p.CD_MUNICIPIO == code]
        if uf:
            p = p[p.SG_UF == uf]
        if codes is not None:
            p = p[p.CD_MUNICIPIO.isin(codes)]
        if sexo:
            p = p[p.DS_GENERO == sexo]
        return int(p.QT_ELEITORES.sum())

    def expected(self, spec):
        """Números esperados (já formatados em pt-BR) para uma especificação de referência."""
        kind = spec["tipo"]
        code = self.code(*spec["municipio"]) if spec.get("municipio") else None
        uf = spec.get("uf")
        if kind == "votos":
            return [br(self.candidate_votes(spec["candidato"], code, uf))]
        if kind == "percentual":
            return [pct(self.share(spec["candidato"], code, uf))]
        if kind == "validos":
            return [br(self.valid(code, uf))]
        if kind == "eleitorado":
            return [br(self.electorate(code, spec.get("sexo"), uf=uf))]
        if kind == "diferenca":
            a, b = (self.candidate_votes(c, code, uf) for c in spec["candidatos"])
            return [br(abs(a - b)), f"{abs(100 * (a - b) / self.valid(code, uf)):.1f}".replace(".", ",")]
        if kind == "comparacao":
            return [br(self.candidate_votes(c, code, uf)) for c in spec["candidatos"]]
        if kind == "ranking":
            return [br(v) for v in self.ranking(spec["candidato"], uf, spec["n"]).VOTOS]
        if kind == "ddd_eleitorado":
            codes = set(self.towns.loc[self.towns.DDD.eq(spec["ddd"]).fillna(False), "CD_MUNICIPIO"].astype(str))
            return [br(self.electorate(codes=codes))]
        raise ValueError(kind)
