"""Consultas de referência independentes do assistente.

Calculadas diretamente dos CSVs originais do notebook (votação e perfil por sexo) e,
para idade/escolaridade/DDD, dos derivados preparados lidos com Pandas puro. Os
valores esperados dos testes e da avaliação vêm daqui, nunca de um modelo de linguagem.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

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

    def divulgacao(self, election, uf, code=None):
        """Votos por candidatura num arquivo oficial de divulgação do TSE (-u.json), lido sem o pipeline."""
        folder = ROOT / "dados/brutos/divulgacao_2026" / election / uf.lower()
        path = folder / (f"{uf.lower()}{code}-c0001-e00{election}-u.json" if code else f"{uf.lower()}-c0001-e00{election}-u.json")
        if not path.exists():
            pytest.skip("arquivos brutos de divulgação ausentes nesta máquina")
        doc = json.loads(path.read_text(encoding="utf-8"))
        return {c["nmu"]: int(c["vap"]) for g in doc["carg"][0]["agr"] for party in g["par"] for c in party["cand"]}

    def second_round(self, candidate, code=None, uf=None):
        """Votos do 2º turno: município, UF ou Brasil sem exterior (Brasil − exterior)."""
        if code:
            town = self.towns[self.towns.CD_MUNICIPIO.astype(str) == code].iloc[0]
            return self.divulgacao("6258", town.SG_UF, code)[candidate]
        if uf:
            return self.divulgacao("6258", uf)[candidate]
        return self.divulgacao("6258", "br")[candidate] - self.divulgacao("6258", "zz")[candidate]

    def second_round_share(self, candidate, code=None, uf=None):
        votes = {c: self.second_round(c, code, uf) for c in ["LULA", "FLAVIO BOLSONARO"]}
        return 100 * votes[candidate] / sum(votes.values())

    def timing(self):
        """secoes.csv do urnas-tardias, fixado por commit, lido diretamente (sem o pipeline)."""
        files = sorted((ROOT / "dados/brutos/urnas_tardias").glob("*/secoes.csv"))
        if not files:
            pytest.skip("secoes.csv do urnas-tardias ausente nesta máquina")
        frame = pd.read_csv(files[-1], dtype={"cd_mun": str, "zona": str, "secao": str})
        return frame[frame.uf != "ZZ"]

    def simulation(self, candidate, code, turn):
        """Simulação proporcional por sexo: votos oficiais × participação no cadastro, maiores restos."""
        votes = self.second_round(candidate, code) if turn == 2 else self.candidate_votes(candidate, code)
        groups = self.profile[self.profile.CD_MUNICIPIO == code].groupby("DS_GENERO").QT_ELEITORES.sum()
        exact = {group: votes * n / groups.sum() for group, n in groups.items()}
        result = {group: int(value) for group, value in exact.items()}
        for group in sorted(exact, key=lambda g: exact[g] - result[g], reverse=True)[:votes - sum(result.values())]:
            result[group] += 1
        return result

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
        if kind == "votos_2t":
            return [br(self.second_round(spec["candidato"], code, uf))]
        if kind == "turnos":
            return [br(n) for c in spec["candidatos"] for n in (self.candidate_votes(c, code, uf), self.second_round(c, code, uf))]
        if kind == "simulacao_sexo":
            return [br(n) for n in self.simulation(spec["candidato"], code, spec["turno"]).values()]
        if kind == "horarios":
            sections = self.timing()
            sections = sections[sections.cd_mun == code]
            if spec["metrica"] == "estendidas":
                return [br(sections.classe.eq("estendida").sum()), br(len(sections))]
            return [br(sections.votos_apos_17h.sum())]
        raise ValueError(kind)
