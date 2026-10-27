"""Estatística eleitoral auditável, sem dependência da interface ou do intérprete.

Contagens são inteiras; taxas são razões de somas. A decomposição usa frações
exatas. Fluxos hipotéticos ficam em transfers.py, separados dos resultados.
"""
from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
import json

import numpy as np
import pandas as pd

from .data import integer, percent
from .engine import DataUnavailable

KEYS = ["SG_UF", "CD_MUNICIPIO"]
COUNTS = ["ELEITORADO_APTO", "COMPARECIMENTO", "ABSTENCAO", "VOTOS_VALIDOS", "VOTOS_BRANCOS", "VOTOS_NULOS"]
TECH = ["APTOS_SECOES_NAO_INSTALADAS", "APTOS_SECOES_NAO_APURADAS", "NULOS_URNA", "NULOS_TECNICOS",
        "ANULADOS", "ANULADOS_SUB_JUDICE", "VOTOS_SECOES_ANULADAS", "VOTOS_SEM_CANDIDATO_VALIDO"]
LABELS = {"LULA": "Lula", "FLAVIO": "Flávio Bolsonaro", "OUTROS": "Demais candidatos", "VOTOS_VALIDOS": "Votos válidos",
          "ELEITORADO_APTO": "Eleitorado apto", "COMPARECIMENTO": "Comparecimento", "ABSTENCAO": "Abstenção",
          "VOTOS_BRANCOS": "Votos brancos", "VOTOS_NULOS": "Votos nulos", "BRANCOS_NULOS": "Brancos e nulos"}
COMPOSITION = ["LULA", "FLAVIO", "OUTROS", "VOTOS_BRANCOS", "VOTOS_NULOS", "ABSTENCAO"]
WARNING = "O crescimento líquido de votos não revela, isoladamente, de quais candidatos ou categorias de eleitores esses votos vieram."
DEMOGRAPHIC_NOTE = "Os filtros demográficos não se aplicam: não há cruzamento oficial entre perfil e comparecimento, abstenção, brancos ou nulos. Os valores são do território inteiro."
FORMULAS = "Taxas: abstenção e comparecimento / aptos; brancos e nulos / comparecimento; candidaturas / válidos. Variação relativa = 100 × (final − inicial) / inicial. Diferença de taxas em pontos percentuais."


def ratio(numerator, denominator):
    return 100.0 * numerator / denominator if denominator > 0 else None


def decompose(l1, l2, v1, v2):
    if min(l1, l2, v1, v2) < 0 or l1 > v1 or l2 > v2:
        raise ValueError("Contagens inválidas para a decomposição")
    if not v1 or not v2:
        return None
    p1, p2 = Fraction(int(l1), int(v1)), Fraction(int(l2), int(v2))
    share = (p2 - p1) * Fraction(int(v1 + v2), 2)
    base = Fraction(int(v2 - v1), 2) * (p1 + p2)
    assert share + base == l2 - l1
    return {"participacao": share, "base": base, "delta": int(l2 - l1)}


def require(condition, message):
    if not condition:
        raise DataUnavailable(message)


def validate_counts(rows, detailed=False):
    require(not rows.empty, "Totalização indisponível neste recorte")
    require(not rows.duplicated(KEYS).any(), "Município duplicado na totalização")
    columns = COUNTS + (TECH if detailed else [])
    require(set(columns).issubset(rows), "Campos obrigatórios ausentes na totalização")
    values = rows[columns]
    require(not values.isna().any().any(), "Contagens ausentes; não podem ser convertidas em zero")
    require(np.isfinite(values.to_numpy(dtype=float)).all() and (values >= 0).all().all() and
            (values % 1 == 0).all().all(), "Contagens negativas, fracionárias ou não finitas")
    require(rows.TOTALIZACAO_FINAL.eq(True).all() and rows.SECOES.eq(rows.SECOES_TOTALIZADAS).all(), "Totalização ainda parcial")
    technical = rows.APTOS_SECOES_NAO_INSTALADAS + rows.APTOS_SECOES_NAO_APURADAS if detailed else 0
    require(rows.ELEITORADO_APTO.eq(rows.COMPARECIMENTO + rows.ABSTENCAO + technical).all(), "Aptos não reconciliam com comparecimento, abstenção e categorias técnicas")
    # Não somar van/vansj/vnt novamente: podem ser subconjuntos. Definição atual
    # vv + vb + tvn reconcilia; uma nova categoria não explicada bloqueia a consulta.
    require(rows.COMPARECIMENTO.eq(rows.VOTOS_VALIDOS + rows.VOTOS_BRANCOS + rows.VOTOS_NULOS).all(), "Composição do comparecimento não conciliada")
    if detailed:
        require(rows.VOTOS_NULOS.eq(rows.NULOS_URNA + rows.NULOS_TECNICOS).all(), "Subcategorias de nulos não conciliadas")


class Evolution:
    def __init__(self, engine):
        self.engine, self.data = engine, engine.data
        self.details = self.data._optional("totalizacao_detalhada.parquet")
        path = self.data.directory / "referencias_totalizacao.json"
        self.references = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.name in self.data.manifest["outputs"] else {}

    @lru_cache(maxsize=8)
    def period(self, year, turn):
        source = self.data.totalization
        require(source is not None, "Totalização oficial não disponível")
        require(set(COUNTS + KEYS + ["ANO_ELEICAO", "NR_TURNO", "TOTALIZACAO_FINAL", "SECOES", "SECOES_TOTALIZADAS"]).issubset(source), "Esquema de totalização incompleto")
        rows = source[source.ANO_ELEICAO.eq(year) & source.NR_TURNO.eq(turn)].copy()
        require(not rows.duplicated(KEYS).any(), "Totalização duplicada por município")
        if self.details is not None:
            require(set(COUNTS + TECH + KEYS + ["ANO_ELEICAO", "NR_TURNO"]).issubset(self.details), "Esquema de categorias técnicas incompleto")
            detail = self.details[self.details.ANO_ELEICAO.eq(year) & self.details.NR_TURNO.eq(turn)]
            require(not detail.duplicated(KEYS).any(), "Detalhamento duplicado")
            merged = rows.merge(detail, on=["ANO_ELEICAO", "NR_TURNO"] + KEYS, how="outer", suffixes=("", "_audit"), indicator=True, validate="one_to_one")
            require(merged._merge.eq("both").all(), "Cobertura do detalhamento diverge")
            require(all(merged[c].eq(merged[c + "_audit"]).all() for c in COUNTS), "Fontes de totalização divergentes")
            rows = merged.drop(columns=[c + "_audit" for c in COUNTS] + ["_merge"])
        if rows.duplicated(KEYS).any():
            raise DataUnavailable("Totalização duplicada por município")
        control = self.references.get("referencias", {}).get(str(turn)) if year == 2026 else None
        if control:
            for uf, values in control["ufs"].items():
                local = rows[rows.SG_UF.eq(uf)]
                require(not local.empty, "UF ausente da totalização")
                for key, value in values.items():
                    if key in rows:
                        require(not local[key].isna().any() and int(local[key].sum()) == value, f"Total de {key} diverge da referência oficial de {uf}")
            require(set(rows.SG_UF) == set(control["ufs"]), "UF inesperada na totalização")
        v = self.engine._period_votes((year, turn))
        require(set(KEYS + ["NR_CANDIDATO", "VOTOS"]).issubset(v), "Esquema de votos incompleto")
        require(not v.duplicated(KEYS + ["NR_CANDIDATO"]).any(), "Candidatura duplicada na chave oficial")
        require(not v.VOTOS.isna().any() and (v.VOTOS >= 0).all() and (v.VOTOS % 1 == 0).all(), "Votos nominais inválidos")
        domestic = rows[rows.SG_UF.ne("ZZ")]
        require(set(map(tuple, domestic[KEYS].to_numpy())) == set(map(tuple, v[KEYS].drop_duplicates().to_numpy())), "Cobertura municipal dos votos e totalização diverge")
        nominal = v.groupby(KEYS).VOTOS.sum()
        check = domestic.set_index(KEYS).VOTOS_VALIDOS
        require(check.eq(nominal.reindex(check.index)).all(), "Soma nominal difere dos válidos")
        # Chave oficial da candidatura; nome de urna serve apenas para apresentação.
        pivot = v.pivot(index=KEYS, columns="NR_CANDIDATO", values="VOTOS")
        for number, name in [(13, "LULA"), (22, "FLAVIO")]:
            require(number in pivot and not pivot[number].isna().any(), f"Candidatura {number} ausente em parte do território")
            rows = rows.merge(pivot[[number]].rename(columns={number: name}), on=KEYS, how="left", validate="one_to_one")
        return rows

    def selected(self, year, turn, territory, codes=None):
        rows = self.period(year, turn)
        if territory.kind == "total":
            chosen = rows.copy()
        elif territory.kind == "exterior":
            chosen = rows[rows.SG_UF.eq("ZZ")].copy()
        else:
            codes = codes if codes is not None else self.engine.codes(territory)
            chosen = rows[rows.SG_UF.ne("ZZ") & rows.CD_MUNICIPIO.isin(codes)].copy()
            require(set(chosen.CD_MUNICIPIO) == set(codes), "Cobertura territorial incompleta")
        validate_counts(chosen, self.details is not None)
        return chosen

    @lru_cache(maxsize=128)
    def snapshot(self, year, turn, territory, codes=None):
        rows = self.selected(year, turn, territory, codes)
        columns = COUNTS + (TECH if self.details is not None else [])
        totals = {c: int(rows[c].sum()) for c in columns}
        if territory.kind in {"total", "exterior"}:
            candidates = self.engine.result((year, turn), territory)["rows"].set_index("NM_URNA_CANDIDATO")
            require({"LULA", "FLAVIO BOLSONARO"}.issubset(candidates.index), "Metadados dos finalistas indisponíveis")
            require(int(candidates.VOTOS.sum()) == totals["VOTOS_VALIDOS"], "Votos nacionais e totalização divergem")
            totals.update(LULA=int(candidates.loc["LULA", "VOTOS"]), FLAVIO=int(candidates.loc["FLAVIO BOLSONARO", "VOTOS"]))
        else:
            require(not rows[["LULA", "FLAVIO"]].isna().any().any(), "Votos dos finalistas ausentes")
            totals.update({c: int(rows[c].sum()) for c in ["LULA", "FLAVIO"]})
        totals["OUTROS"] = totals["VOTOS_VALIDOS"] - totals["LULA"] - totals["FLAVIO"]
        require(totals["OUTROS"] >= 0 and (turn != 2 or totals["OUTROS"] == 0), "Finalistas incompatíveis com a totalização")
        totals["BRANCOS_NULOS"] = totals["VOTOS_BRANCOS"] + totals["VOTOS_NULOS"]
        totals["APTOS_PUBLICADOS"] = totals["ELEITORADO_APTO"]
        notes = []
        adjustment = self.references.get("ajuste_tte", {})
        if adjustment:
            notes.append("A nota TSE informa 39 duplicidades nacionais. Não há alocação territorial desses registros nesta base; os aptos territoriais são os publicados, sem correção arbitrária.")
            if territory.kind == "total":
                raw, effective = adjustment["registros_publicados"], adjustment["eleitorado_efetivo_nacional"]
                require(totals["ELEITORADO_APTO"] in {raw, effective}, "Eleitorado nacional mudou; revisar a nota de ajuste TTE")
                totals["ELEITORADO_APTO"] = effective  # idempotente, nunca subtrai duas vezes
                notes.append("Denominador nacional efetivo conforme nota TSE. A composição não é fechada porque os registros técnicos não permitem alocar a correção.")
        denominators = {c: "VOTOS_VALIDOS" for c in ["LULA", "FLAVIO", "OUTROS"]}
        denominators.update({c: "ELEITORADO_APTO" for c in ["COMPARECIMENTO", "ABSTENCAO"]})
        denominators.update({c: "COMPARECIMENTO" for c in ["VOTOS_BRANCOS", "VOTOS_NULOS", "BRANCOS_NULOS", "VOTOS_VALIDOS"]})
        rates = {c: ratio(totals[c], totals[d]) for c, d in denominators.items()}
        reports = self.data.manifest["sources"].get("divulgacao", {}).get("elections", {}).values()
        report = next((r for r in reports if r["ano"] == year and r["turno"] == turn), {})
        source = report.get("fonte", "TSE · totalizacao.parquet")
        stamp = report.get("geracao_na_origem", self.data.manifest.get("prepared_at", "Indisponível"))
        return {"year": year, "turn": turn, "scope": territory.label, "totals": totals, "rates": rates, "denominators": denominators,
                "rows": len(rows), "source": source, "updated": stamp, "version": self.data.manifest["outputs"].get("totalizacao.parquet", ""),
                "notes": notes, "closed": sum(totals[c] for c in COMPOSITION) == totals["ELEITORADO_APTO"]}

    @lru_cache(maxsize=128)
    def compare(self, year, territory, codes=None):
        first = self.snapshot(year, 1, territory, codes)
        second = self.snapshot(year, 2, territory, codes)
        a, b = self.selected(year, 1, territory, codes), self.selected(year, 2, territory, codes)
        require(set(map(tuple, a[KEYS].to_numpy())) == set(map(tuple, b[KEYS].to_numpy())), "Territórios incompatíveis entre turnos")
        records = []
        for key, label in LABELS.items():
            x, y = first["totals"][key], second["totals"][key]
            p, q = first["rates"].get(key), second["rates"].get(key)
            records.append({"Métrica": label, "Chave": key, "1º turno": x, "2º turno": y, "Variação absoluta": y - x,
                            "Variação relativa (%)": ratio(y - x, x), "% 1º turno": p, "% 2º turno": q,
                            "Variação (p.p.)": q - p if p is not None and q is not None else None,
                            "Denominador da taxa": LABELS.get(first["denominators"].get(key, ""), "Não se aplica")})
        t1, t2 = first["totals"], second["totals"]
        return {"first": first, "second": second, "table": pd.DataFrame(records),
                "decomposition": decompose(t1["LULA"], t2["LULA"], t1["VOTOS_VALIDOS"], t2["VOTOS_VALIDOS"])}

    @lru_cache(maxsize=64)
    def territorial(self, year, territory, level="municipio", codes=None):
        require(territory.kind not in {"total", "exterior"}, "Ranking territorial abrange apenas o Brasil sem exterior")
        group = KEYS if level == "municipio" else ["SG_UF"]
        tables = []
        for turn in [1, 2]:
            rows = self.selected(year, turn, territory, codes)
            counts = rows.groupby(group)[COUNTS + ["LULA", "FLAVIO"]].sum()
            counts["BRANCOS_NULOS"] = counts.VOTOS_BRANCOS + counts.VOTOS_NULOS
            for key, denominator in [("ABSTENCAO", "ELEITORADO_APTO"), ("COMPARECIMENTO", "ELEITORADO_APTO"),
                                     ("VOTOS_BRANCOS", "COMPARECIMENTO"), ("VOTOS_NULOS", "COMPARECIMENTO"),
                                     ("BRANCOS_NULOS", "COMPARECIMENTO"), ("LULA", "VOTOS_VALIDOS"), ("FLAVIO", "VOTOS_VALIDOS")]:
                counts[key + "_TAXA"] = (100 * counts[key] / counts[denominator]).where(counts[denominator].gt(0))
            tables.append(counts.add_suffix(f"_{turn}"))
        require(tables[0].index.equals(tables[1].index), "Cobertura territorial desigual entre turnos")
        table = tables[0].join(tables[1], validate="one_to_one").reset_index()
        for key in ["ABSTENCAO", "COMPARECIMENTO", "VOTOS_BRANCOS", "VOTOS_NULOS", "BRANCOS_NULOS", "LULA", "FLAVIO"]:
            table[key + "_DELTA"] = table[key + "_2"] - table[key + "_1"]
            table[key + "_PP"] = table[key + "_TAXA_2"] - table[key + "_TAXA_1"]
            table[key + "_REL"] = (100 * table[key + "_DELTA"] / table[key + "_1"]).where(table[key + "_1"].gt(0))
        if level == "municipio":
            table = table.merge(self.data.towns[KEYS + ["NM_MUNICIPIO", "codigo_ibge"]], on=KEYS, validate="one_to_one")
            table["Localidade"] = table.NM_MUNICIPIO.str.title() + "/" + table.SG_UF
        else:
            table["Localidade"] = table.SG_UF
        return table


def summary(comparison):
    a, b = comparison["first"], comparison["second"]
    x, y = a["totals"], b["totals"]
    return (f"Lula obteve {integer(x['LULA'])} votos no primeiro turno e {integer(y['LULA'])} no segundo turno, "
            f"registrando variação líquida de {integer(y['LULA'] - x['LULA'])} votos. Sua participação nos votos válidos "
            f"passou de {percent(a['rates']['LULA'])} para {percent(b['rates']['LULA'])}. No mesmo intervalo, "
            f"o comparecimento eleitoral variou em {integer(y['COMPARECIMENTO'] - x['COMPARECIMENTO'])} eleitores.")


def export_table(comparison):
    table = comparison["table"].copy()
    first, second = comparison["first"], comparison["second"]
    for key, value in {"Análise": "Evolução eleitoral", "Ano": first["year"], "Turnos": "1 e 2", "Território": first["scope"],
                       "Fonte 1": first["source"], "Fonte 2": second["source"], "Atualização 1": first["updated"], "Atualização 2": second["updated"],
                       "SHA256 totalização": first["version"], "Natureza": "DADO OFICIAL (contagens); CÁLCULO ESTATÍSTICO (taxas e diferenças)",
                       "Definições": FORMULAS, "Aviso": WARNING, "Notas": " ".join(first["notes"])}.items():
        table[key] = value
    return table


@lru_cache(maxsize=4)
def evolution_for(engine):
    return Evolution(engine)
