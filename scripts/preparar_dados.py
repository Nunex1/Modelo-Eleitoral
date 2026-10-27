"""ETL reexecutável: preserva insumos, reconcilia notebook, audita DDD e salva linhagem."""
from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unicodedata
from zipfile import ZipFile

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dados/tratados/lampiadim"
ASSETS = ROOT / "Lampiadim_MVP/assets"
UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
ANATEL = "https://www.anatel.gov.br/dadosabertos/PDA/Codigo_Nacional/PGCN.csv"
MALHAS = "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&qualidade=minima&intrarregiao="


def normalizar(value):
    text = unicodedata.normalize("NFKD", str(value))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c)).upper()).split())


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def source(path):
    return {"file": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size}


def save(frame, name):
    temp = OUT / (name + ".tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(OUT / name)


def votes():
    path = ROOT / "dados/brutos/votacao_candidato_munzona_2026.zip"
    cols = ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO"]
    with ZipFile(path) as z:
        member = "votacao_candidato_munzona_2026_BR.csv"
        with z.open(member) as f:
            frame = pd.read_csv(f, sep=";", encoding="latin1", usecols=cols + ["DS_CARGO", "QT_VOTOS_NOMINAIS_VALIDOS", "DT_GERACAO"], dtype={"CD_MUNICIPIO": "str"})
    dates = sorted(frame.DT_GERACAO.unique().tolist())
    frame["CD_MUNICIPIO"] = frame.CD_MUNICIPIO.str.zfill(5)
    frame = frame[frame.SG_UF.isin(UFS) & frame.DS_CARGO.str.upper().eq("PRESIDENTE")]
    frame = frame.groupby(cols, observed=True, as_index=False, dropna=False).QT_VOTOS_NOMINAIS_VALIDOS.sum().rename(columns={"QT_VOTOS_NOMINAIS_VALIDOS": "VOTOS"})
    if frame.VOTOS.isna().any() or (frame.VOTOS < 0).any():
        raise ValueError("Votos negativos/ausentes no arquivo bruto")
    original = pd.read_csv(ROOT / "Lampiadim_MVP/resultado_presidencial_2026_brasil.csv", dtype={"CD_MUNICIPIO": "str"})
    original["CD_MUNICIPIO"] = original.CD_MUNICIPIO.str.zfill(5)
    keys = ["SG_UF", "CD_MUNICIPIO", "NR_CANDIDATO"]
    check = frame[(frame.ANO_ELEICAO == 2026) & (frame.NR_TURNO == 1)].set_index(keys).VOTOS.sort_index()
    expected = original.set_index(keys).VOTOS.sort_index()
    pd.testing.assert_series_equal(check, expected, check_names=False)
    save(frame, "votos.parquet")
    return {**source(path), "member": member, "generated_dates": dates, "years": sorted(frame.ANO_ELEICAO.unique().tolist()), "turns": sorted(frame.NR_TURNO.unique().tolist()), "rows": len(frame), "total": int(frame.VOTOS.sum()), "reconciled_original": True}


def candidates():
    """Metadados oficiais por candidatura: nome completo, partido, situação e votos no exterior.

    Reconcilia os votos sem exterior com votos.parquet; o exterior (ZZ) fica em coluna própria.
    """
    path = ROOT / "dados/brutos/votacao_candidato_munzona_2026.zip"
    member = "votacao_candidato_munzona_2026_BR.csv"
    meta = ["ANO_ELEICAO", "NR_TURNO", "DS_CARGO", "NR_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "NM_SOCIAL_CANDIDATO", "SG_PARTIDO", "NM_PARTIDO", "NM_COLIGACAO", "DS_COMPOSICAO_COLIGACAO", "DS_SIT_TOT_TURNO"]
    with ZipFile(path) as z, z.open(member) as f:
        frame = pd.read_csv(f, sep=";", encoding="latin1", usecols=meta + ["SG_UF", "QT_VOTOS_NOMINAIS_VALIDOS"])
    frame = frame[frame.DS_CARGO.str.upper().eq("PRESIDENTE") & (frame.SG_UF.isin(UFS) | frame.SG_UF.eq("ZZ"))]
    frame["ESCOPO"] = frame.SG_UF.where(frame.SG_UF.eq("ZZ"), "BR")
    votes_by_scope = frame.pivot_table(index=["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO"], columns="ESCOPO", values="QT_VOTOS_NOMINAIS_VALIDOS", aggfunc="sum", fill_value=0)
    info = frame[meta].drop_duplicates()
    if info.duplicated(["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO"]).any():
        raise ValueError("Metadados divergentes para a mesma candidatura")
    table = info.merge(votes_by_scope.rename(columns={"BR": "VOTOS_BRASIL", "ZZ": "VOTOS_EXTERIOR"}).reset_index(), on=["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO"], how="left", validate="one_to_one")
    for column in ["VOTOS_BRASIL", "VOTOS_EXTERIOR"]:
        table[column] = (table[column] if column in table else pd.Series(0, index=table.index)).fillna(0).astype("int64")
    table["NM_SOCIAL_CANDIDATO"] = table.NM_SOCIAL_CANDIDATO.where(~table.NM_SOCIAL_CANDIDATO.isin(["#NULO", "#NE"]))
    prepared = pd.read_parquet(OUT / "votos.parquet").groupby(["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO", "NM_URNA_CANDIDATO"], as_index=False).VOTOS.sum()
    check = table.merge(prepared, on=["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO", "NM_URNA_CANDIDATO"], how="outer", validate="one_to_one", indicator=True)
    if not check._merge.eq("both").all() or not check.VOTOS.eq(check.VOTOS_BRASIL).all():
        raise ValueError("Candidaturas não reconciliam com votos.parquet")
    save(table.drop(columns="DS_CARGO").sort_values(["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO"]), "candidatos.parquet")
    return {**source(path), "member": member, "rows": len(table), "total_brasil": int(table.VOTOS_BRASIL.sum()), "total_exterior": int(table.VOTOS_EXTERIOR.sum()), "reconciled_votes": True, "columns": meta[3:] + ["VOTOS_BRASIL", "VOTOS_EXTERIOR"]}


DIVULGACAO = {"6257": (2026, 1), "6258": (2026, 2)}


def _int(value):
    return int(str(value or "0").replace(".", "") or 0)


def divulgacao():
    """Resultados oficiais do portal de divulgação do TSE (-u.json por município).

    Turnos já presentes no arquivo consolidado (votos.parquet) servem só para validar a
    equivalência das duas fontes; turnos ausentes dele (2º turno) viram votos_divulgacao.parquet.
    Também grava a totalização por município (seções, aptos, comparecimento, brancos, nulos).
    """
    base = ROOT / "dados/brutos/divulgacao_2026"
    consolidated = pd.read_parquet(OUT / "votos.parquet")
    present = set(map(tuple, consolidated[["ANO_ELEICAO", "NR_TURNO"]].drop_duplicates().itertuples(index=False)))
    towns = pd.read_parquet(OUT / "municipios.parquet")
    names = dict(zip(towns.CD_MUNICIPIO.astype(str), towns.NM_MUNICIPIO))
    votes_rows, totals_rows, people, report = [], [], [], {}
    for election, (year, turn) in DIVULGACAO.items():
        folder = base / election
        if not (folder / "_coleta.json").exists():
            continue
        collected = json.loads((folder / "_coleta.json").read_text(encoding="utf-8"))
        if collected["falhas"] or collected["arquivos"] != collected["esperados"]:
            raise ValueError(f"Coleta {election} incompleta: execute scripts/baixar_divulgacao.py {election} novamente")
        config = json.loads((folder / f"mun-e00{election}-cm.json").read_text(encoding="utf-8"))
        by_uf, generated = {}, set()
        for state in config["abr"]:
            uf = state["cd"].upper()
            for m in state["mu"]:
                doc = json.loads((folder / uf.lower() / f"{uf.lower()}{m['cd']}-c0001-e00{election}-u.json").read_text(encoding="utf-8"))
                if doc["ele"] != election or doc["t"] != str(turn) or doc["cdabr"] != m["cd"] or doc["tpabr"] != "mu":
                    raise ValueError(f"Arquivo inconsistente: {uf} {m['cd']} ({election})")
                generated.add(f"{doc['dg']} {doc['hg']}")
                s, e, v = doc["s"], doc["e"], doc["v"]
                totals_rows.append({"ANO_ELEICAO": year, "NR_TURNO": turn, "SG_UF": uf, "CD_MUNICIPIO": m["cd"], "SECOES": _int(s["ts"]),
                                    "SECOES_TOTALIZADAS": _int(s["st"]), "ELEITORADO_APTO": _int(e["te"]), "COMPARECIMENTO": _int(e["c"]),
                                    "ABSTENCAO": _int(e["a"]), "VOTOS_VALIDOS": _int(v["vv"]), "VOTOS_BRANCOS": _int(v["vb"]), "VOTOS_NULOS": _int(v["tvn"]),
                                    "TOTALIZACAO_FINAL": doc.get("tf") == "s"})
                for group in doc["carg"][0]["agr"]:
                    for party in group["par"]:
                        for cand in party["cand"]:
                            row = {"ANO_ELEICAO": year, "NR_TURNO": turn, "SG_UF": uf, "CD_MUNICIPIO": m["cd"], "NM_MUNICIPIO": names.get(m["cd"], m["nm"]),
                                   "NR_CANDIDATO": int(cand["n"]), "NM_URNA_CANDIDATO": cand["nmu"], "SG_PARTIDO": party["sg"], "VOTOS": _int(cand["vap"])}
                            votes_rows.append(row)
                            by_uf.setdefault((uf, row["NR_CANDIDATO"]), 0)
                            by_uf[(uf, row["NR_CANDIDATO"])] += row["VOTOS"]
                            people.append({"ANO_ELEICAO": year, "NR_TURNO": turn, "NR_CANDIDATO": int(cand["n"]), "NM_CANDIDATO": cand["nm"],
                                           "NM_URNA_CANDIDATO": cand["nmu"], "NM_SOCIAL_CANDIDATO": None, "SG_PARTIDO": party["sg"], "NM_PARTIDO": party["nm"],
                                           "NM_COLIGACAO": group["nm"], "DS_COMPOSICAO_COLIGACAO": group.get("com", ""), "DS_SIT_TOT_TURNO": cand["st"].upper(),
                                           "EXTERIOR": uf == "ZZ", "VOTOS": row["VOTOS"]})
        # Somas municipais = arquivo da UF; UFs + exterior = arquivo do Brasil.
        national = {}
        for state in config["abr"]:
            uf = state["cd"].lower()
            doc = json.loads((folder / uf / f"{uf}-c0001-e00{election}-u.json").read_text(encoding="utf-8"))
            for group in doc["carg"][0]["agr"]:
                for party in group["par"]:
                    for cand in party["cand"]:
                        if by_uf.get((uf.upper(), int(cand["n"])), 0) != _int(cand["vap"]):
                            raise ValueError(f"Soma municipal difere do total da UF {uf.upper()} ({election})")
                        national[int(cand["n"])] = national.get(int(cand["n"]), 0) + _int(cand["vap"])
        doc = json.loads((folder / "br" / f"br-c0001-e00{election}-u.json").read_text(encoding="utf-8"))
        brasil = {int(c["n"]): _int(c["vap"]) for g in doc["carg"][0]["agr"] for p in g["par"] for c in p["cand"]}
        if brasil != national:
            raise ValueError(f"Soma das UFs difere do total nacional ({election})")
        report[election] = {"ano": year, "turno": turn, "fonte": collected["fonte"], "sha256_conjunto": collected["sha256_conjunto"],
                            "arquivos": collected["arquivos"], "geracao_na_origem": sorted(generated)[-1], "baixado_em": collected["baixado_em"],
                            "totais_nacionais_com_exterior": {str(k): v for k, v in sorted(brasil.items())}, "reconciliado_ufs_e_brasil": True}
    if not report:
        return None, None, None
    frame = pd.DataFrame(votes_rows)
    # Equivalência das fontes: onde há arquivo consolidado, a divulgação precisa coincidir integralmente.
    for (year, turn) in present:
        check = frame[(frame.ANO_ELEICAO == year) & (frame.NR_TURNO == turn) & frame.SG_UF.ne("ZZ")]
        if check.empty:
            continue
        keys = ["SG_UF", "CD_MUNICIPIO", "NR_CANDIDATO"]
        merged = check.merge(consolidated[(consolidated.ANO_ELEICAO == year) & (consolidated.NR_TURNO == turn)], on=keys, how="outer", suffixes=("_div", "_csv"), indicator=True)
        divergent = merged[merged._merge.ne("both") | merged.VOTOS_div.ne(merged.VOTOS_csv)]
        if len(divergent):
            raise ValueError(f"Divulgação e arquivo consolidado divergem em {len(divergent)} linhas ({year}, {turn}º turno)")
        election = next(k for k, v in DIVULGACAO.items() if v == (year, turn))
        report[election]["equivalente_ao_consolidado"] = {"linhas_comparadas": len(merged), "divergencias": 0}
    new = frame[~frame[["ANO_ELEICAO", "NR_TURNO"]].apply(tuple, axis=1).isin(present) & frame.SG_UF.ne("ZZ")]
    save(new.sort_values(["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_CANDIDATO"]).reset_index(drop=True), "votos_divulgacao.parquet")
    save(pd.DataFrame(totals_rows).sort_values(["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO"]).reset_index(drop=True), "totalizacao.parquet")
    people = pd.DataFrame(people)
    people = people[~people[["ANO_ELEICAO", "NR_TURNO"]].apply(tuple, axis=1).isin(present)]
    meta = [c for c in people.columns if c not in {"EXTERIOR", "VOTOS"}]
    info = people.groupby(meta, dropna=False, as_index=False).agg(VOTOS_BRASIL=("VOTOS", lambda s: int(s[~people.loc[s.index, "EXTERIOR"]].sum())),
                                                                   VOTOS_EXTERIOR=("VOTOS", lambda s: int(s[people.loc[s.index, "EXTERIOR"]].sum())))
    if info.duplicated(["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO"]).any():
        raise ValueError("Metadados divergentes de candidatura na divulgação")
    table = pd.read_parquet(OUT / "candidatos.parquet")
    table = table[~table[["ANO_ELEICAO", "NR_TURNO"]].apply(tuple, axis=1).isin(set(map(tuple, info[["ANO_ELEICAO", "NR_TURNO"]].itertuples(index=False))))]
    save(pd.concat([table, info[table.columns]], ignore_index=True).sort_values(["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO"]).reset_index(drop=True), "candidatos.parquet")
    return report, len(new), len(totals_rows)


HORARIO_ESTENDIDA = 17 * 3600 + 45 * 60  # encerramento após 17h45 de Brasília (critério do urnas-tardias)


def _seconds(text):
    h, m, s = (list(map(int, str(text).split(":"))) + [0, 0])[:3]
    return h * 3600 + m * 60 + s


def _hms(seconds):
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def horarios():
    """Linha do tempo das urnas: secoes.csv do urnas-tardias (2º turno) e coleta própria dos logs do TSE.

    Gera horarios_secoes.parquet (uma linha por seção e turno, horário de Brasília) e
    horarios_faixas.parquet (votos computados por hora, só onde a coleta própria cobre os logs).
    Nenhuma tabela associa horários a candidaturas: os logs não registram o voto escolhido.
    """
    pinned = sorted((ROOT / "dados/brutos/urnas_tardias").glob("*/secoes.csv"))
    if not pinned:
        return None
    source = pinned[-1]
    commit = source.parent.name
    tardias = pd.read_csv(source, dtype={"cd_mun": str, "zona": str, "secao": str})
    tardias = tardias[tardias.uf.ne("ZZ")]  # exterior vota no horário local de cada país
    sections = pd.DataFrame({"ANO_ELEICAO": 2026, "NR_TURNO": 2, "SG_UF": tardias.uf, "CD_MUNICIPIO": tardias.cd_mun, "ZONA": tardias.zona,
                             "SECAO": tardias.secao, "FUSO_H": tardias.fuso_h.astype(int), "ABERTURA": tardias.abertura_brt, "ENCERRAMENTO": tardias.encerramento_brt,
                             "ULTIMO_VOTO": tardias.ultimo_voto_brt.fillna(""), "VOTOS_APOS_17H": tardias.votos_apos_17h.astype(int),
                             "VOTOS_APOS_17H20": tardias.votos_apos_17h20.astype(int), "VOTOS_LOG": tardias.votos_total.astype(int),
                             "ESTENDIDA": tardias.classe.eq("estendida"), "FONTE": f"urnas-tardias@{commit[:7]} (logs TSE)"})
    own_rows, hours, compared, mismatches, coverage = [], [], 0, [], {}
    logs = ROOT / "dados/brutos/logs_urna_2026"
    for pleito, turn in [("3220", 1), ("3221", 2)]:
        # Municípios só entram quando todas as seções da configuração oficial foram registradas
        # (com log ou com o motivo da ausência); seções avulsas da amostra entram individualmente.
        expected = collections.defaultdict(set)
        for path in (logs / pleito / "config").glob("*.json"):
            for m in json.loads(path.read_text(encoding="utf-8"))["abr"][0]["mu"]:
                expected[m["cd"]] |= {(z["cd"], s["ns"]) for z in m["zon"] for s in z["sec"]}
        records, seen = [], collections.defaultdict(set)
        for path in sorted((logs / pleito).glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # linha interrompida; a seção é coletada de novo na retomada
                if path.stem == "municipios":
                    seen[r["cd_mun"]].add((r["zona"], r["secao"]))
                if not r.get("erro") and r.get("abertura_local") and r.get("encerramento_local"):
                    records.append({**r, "_completo": path.stem != "municipios"})
        complete = {mun for mun, sections in seen.items() if expected.get(mun) and expected[mun] <= sections}
        records = {(r["cd_mun"], r["zona"], r["secao"]): r for r in records if r["_completo"] or r["cd_mun"] in complete}.values()
        offsets = {}
        for r in records:
            offsets.setdefault(r["cd_mun"], collections.Counter())[round((_seconds(r["abertura_local"][0]) - 8 * 3600) / 3600)] += 1
        offsets = {k: c.most_common(1)[0][0] for k, c in offsets.items()}
        for r in records:
            shift = offsets[r["cd_mun"]] * 3600
            minutes = {(_seconds(t + ":00") - shift): n for t, n in r["votos_por_minuto_local"].items()}
            closing = _seconds(r["encerramento_local"][-1]) - shift
            last = _seconds(r["ultimo_voto_local"]) - shift if r.get("ultimo_voto_local") else None
            row = {"ANO_ELEICAO": 2026, "NR_TURNO": turn, "SG_UF": r["uf"], "CD_MUNICIPIO": r["cd_mun"], "ZONA": r["zona"], "SECAO": r["secao"],
                   "FUSO_H": -offsets[r["cd_mun"]], "ABERTURA": _hms(_seconds(r["abertura_local"][0]) - shift), "ENCERRAMENTO": _hms(closing),
                   "ULTIMO_VOTO": _hms(last) if last is not None else "", "VOTOS_APOS_17H": sum(n for s, n in minutes.items() if s >= 17 * 3600),
                   "VOTOS_APOS_17H20": sum(n for s, n in minutes.items() if s >= 17 * 3600 + 20 * 60), "VOTOS_LOG": r["votos"],
                   "ESTENDIDA": closing >= HORARIO_ESTENDIDA, "FONTE": "coleta própria (logs TSE)"}
            own_rows.append(row)
            for second, n in minutes.items():
                hours.append({"ANO_ELEICAO": 2026, "NR_TURNO": turn, "SG_UF": r["uf"], "CD_MUNICIPIO": r["cd_mun"], "ZONA": r["zona"], "SECAO": r["secao"],
                              "HORA": second // 3600, "VOTOS": n})
        coverage[turn] = sorted(complete)
    own = pd.DataFrame(own_rows)
    if len(own):
        # Validação cruzada: a coleta própria do 2º turno precisa reproduzir o secoes.csv publicado.
        check = own[own.NR_TURNO.eq(2)].merge(sections, on=["SG_UF", "CD_MUNICIPIO", "ZONA", "SECAO"], suffixes=("", "_tardias"))
        fields = ["ABERTURA", "ENCERRAMENTO", "VOTOS_APOS_17H", "VOTOS_APOS_17H20", "VOTOS_LOG", "ESTENDIDA"]
        compared = len(check)
        for _, row in check.iterrows():
            diff = [f for f in fields if row[f] != row[f + "_tardias"]]
            # O urnas-tardias só registra o último voto entre os computados após 13h locais.
            if row["ULTIMO_VOTO_tardias"] and row["ULTIMO_VOTO"] != row["ULTIMO_VOTO_tardias"]:
                diff.append("ULTIMO_VOTO")
            if diff:
                mismatches.append({"secao": f"{row.SG_UF}-{row.CD_MUNICIPIO}-{row.ZONA}-{row.SECAO}", "campos": diff})
    # 1º turno: só a coleta própria; 2º turno: secoes.csv nacional (a coleta própria valida).
    table = pd.concat([sections, own[own.NR_TURNO.eq(1)]], ignore_index=True) if len(own) else sections
    # Votos computados nos logs × comparecimento oficial da divulgação, por município e turno.
    reconciliation = {}
    if (OUT / "totalizacao.parquet").exists():
        totals = pd.read_parquet(OUT / "totalizacao.parquet")
        for turn, rows in table.groupby("NR_TURNO"):
            logs_by_town = rows.groupby("CD_MUNICIPIO").agg(VOTOS=("VOTOS_LOG", "sum"), URNAS=("SECAO", "size"))
            official = totals[totals.NR_TURNO.eq(turn) & totals.SG_UF.ne("ZZ")].set_index("CD_MUNICIPIO")
            merged = logs_by_town.join(official[["COMPARECIMENTO", "SECOES_TOTALIZADAS"]], how="inner")
            if merged.empty:
                continue
            diff = merged.VOTOS - merged.COMPARECIMENTO
            reconciliation[str(turn)] = {"municipios": len(merged), "municipios_iguais": int(diff.eq(0).sum()), "municipios_com_mais_votos_no_log": int(diff.gt(0).sum()),
                                         "votos_nos_logs": int(merged.VOTOS.sum()), "comparecimento_oficial": int(merged.COMPARECIMENTO.sum()),
                                         "diferenca": int(diff.sum()), "secoes_sem_log": int((merged.SECOES_TOTALIZADAS - merged.URNAS).clip(lower=0).sum()),
                                         "explicacao": "o log considerado é o do último pacote de cada seção; votos registrados em urna substituída ou em seção sem log não aparecem"}
    save(table.sort_values(["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "ZONA", "SECAO"]).reset_index(drop=True), "horarios_secoes.parquet")
    faixas = pd.DataFrame(hours, columns=["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "ZONA", "SECAO", "HORA", "VOTOS"])
    faixas = faixas.groupby(["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "ZONA", "SECAO", "HORA"], as_index=False).VOTOS.sum()
    save(faixas, "horarios_faixas.parquet")
    return {"urnas_tardias": {"repositorio": "https://github.com/apolinario/urnas-tardias", "commit": commit, "arquivo": "secoes.csv",
                              "sha256": sha(source), "secoes_brasil": len(sections), "turno": 2, "licenca": "não declarada no repositório; usado como dado derivado com atribuição"},
            "coleta_propria": {"fonte": "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/", "script": "scripts/coletar_logs_urna.py",
                               "municipios_cobertos": {str(t): codes for t, codes in coverage.items()}, "secoes": len(own)},
            "validacao_cruzada": {"secoes_comparadas": compared, "divergentes": len(mismatches), "exemplos": mismatches[:20]},
            "reconciliacao_comparecimento": reconciliation,
            "regra_estendida": "encerramento a partir de 17h45 (horário de Brasília)", "fuso": "moda de (abertura local − 8h) por município"}


def profile():
    path = ROOT / "dados/brutos/perfil_eleitorado_2026.zip"
    dims = ["AA_ELEICAO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "DS_GENERO", "DS_IDENTIDADE_GENERO", "DS_FAIXA_ETARIA", "DS_GRAU_ESCOLARIDADE"]
    parts, dates, members = [], set(), []
    with ZipFile(path) as z:
        members = sorted(x for x in z.namelist() if re.search(r"_([A-Z]{2})\.csv$", x) and x[-6:-4] in UFS)
        if len(members) != 27 or {m[-6:-4] for m in members} != UFS:
            raise ValueError("São necessárias exatamente as 27 partições estaduais")
        for member in members:
            chunks = []
            with z.open(member) as f:
                for block in pd.read_csv(f, sep=";", encoding="latin1", usecols=dims + ["QT_ELEITORES", "DT_GERACAO"], dtype={"CD_MUNICIPIO": "str"}, chunksize=150_000):
                    dates.update(block.DT_GERACAO.unique())
                    block["CD_MUNICIPIO"] = block.CD_MUNICIPIO.str.zfill(5)
                    if block.QT_ELEITORES.isna().any() or (block.QT_ELEITORES < 0).any():
                        raise ValueError("Quantidade inválida no perfil")
                    if not block.SG_UF.eq(member[-6:-4]).all():
                        raise ValueError("Partição estadual contém outra UF")
                    block[dims[4:]] = block[dims[4:]].fillna("NÃO INFORMADO")
                    chunks.append(block.groupby(dims, observed=True, dropna=False, as_index=False).QT_ELEITORES.sum())
            state = pd.concat(chunks).groupby(dims, observed=True, dropna=False, as_index=False).QT_ELEITORES.sum()
            parts.append(state)
            print(f"Perfil {member[-6:-4]}: {len(state):,} grupos, {int(state.QT_ELEITORES.sum()):,} eleitores", flush=True)
    frame = pd.concat(parts, ignore_index=True)
    old = pd.read_csv(ROOT / "Lampiadim_MVP/perfil_demografico_municipios_2026.csv", dtype={"CD_MUNICIPIO": "str"})
    old["CD_MUNICIPIO"] = old.CD_MUNICIPIO.str.zfill(5)
    keys = dims[1:6]
    pd.testing.assert_series_equal(frame.groupby(keys).QT_ELEITORES.sum().sort_index(), old.groupby(keys).QT_ELEITORES.sum().sort_index(), check_names=False)
    for col in dims:
        frame[col] = frame[col].astype("category")
    save(frame, "perfil.parquet")
    return {**source(path), "members": members, "generated_dates": sorted(dates), "rows": len(frame), "total": int(frame.QT_ELEITORES.sum()), "reconciled_original": True, "dimensions": dims}


def geography():
    path = ROOT / "Lampiadim_MVP/base cidades completa.xlsx"
    geo = pd.read_excel(path)
    geo["SG_UF"] = geo.uf.str.upper().str.strip()
    geo["CHAVE"] = geo.cidade.map(normalizar)
    geo["codigo_ibge"] = geo.codigo_ibge.astype(str)
    if geo.duplicated(["SG_UF", "CHAVE"]).any() or geo.codigo_ibge.duplicated().any():
        raise ValueError("Chaves geográficas duplicadas: resolver antes de continuar")
    response = requests.get(ANATEL, timeout=60)
    response.raise_for_status()
    text = response.content.decode("utf-8-sig") if response.content.startswith(b'\xef\xbb\xbf') else response.content.decode("latin1")
    official = pd.read_csv(io.StringIO(text), sep=";", dtype=str)
    # Original header is validated, then positional aliases are recorded in provenance.
    if len(official.columns) != 4 or "IBGE" not in normalizar(official.columns[0]) or "NACIONAL" not in normalizar(official.columns[3]):
        raise ValueError(f"Schema Anatel inesperado: {list(official.columns)}")
    headers = official.columns.tolist()
    official.columns = ["codigo_ibge", "uf_anatel", "municipio_anatel", "ddd_anatel"]
    official = official.drop_duplicates()
    official["codigo_ibge"] = official.codigo_ibge.str.strip()
    official["ddd_anatel"] = pd.to_numeric(official.ddd_anatel, errors="raise").astype("Int64")
    ambiguous = set(official.groupby("codigo_ibge").ddd_anatel.nunique().loc[lambda x: x > 1].index)
    safe = official[~official.codigo_ibge.isin(ambiguous)].drop_duplicates("codigo_ibge")
    geo = geo.merge(safe, on="codigo_ibge", how="left", validate="one_to_one")
    geo["DDD_STATUS"] = "validado Anatel"
    geo.loc[geo.ddd_anatel.isna(), "DDD_STATUS"] = "sem correspondência Anatel"
    geo.loc[geo.codigo_ibge.isin(ambiguous), "DDD_STATUS"] = "ambíguo Anatel"
    geo.loc[geo.uf_anatel.notna() & geo.uf_anatel.ne(geo.SG_UF), "DDD_STATUS"] = "UF divergente"
    geo["DDD"] = geo.ddd_anatel.where(geo.DDD_STATUS.eq("validado Anatel")).astype("Int64")
    local = pd.read_csv(ROOT / "Lampiadim_MVP/resultado_presidencial_2026_brasil.csv", dtype={"CD_MUNICIPIO": "str"})[["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"]].drop_duplicates()
    local["CD_MUNICIPIO"] = local.CD_MUNICIPIO.str.zfill(5)
    local["CHAVE"] = local.NM_MUNICIPIO.map(normalizar)
    towns = local.merge(geo[["SG_UF", "CHAVE", "codigo_ibge", "DDD", "DDD_STATUS", "estado"]], on=["SG_UF", "CHAVE"], how="left", validate="one_to_one")
    # A segunda fonte oficial pode resolver grafias diferentes da planilha local.
    # Exigir coincidência exata após normalização + UF, sem aproximação/fuzzy.
    safe["CHAVE"] = safe.municipio_anatel.map(normalizar)
    counts = safe.groupby(["uf_anatel", "CHAVE"]).codigo_ibge.nunique()
    exact = safe.set_index(["uf_anatel", "CHAVE"])
    resolved_official = []
    for index, row in towns[towns.codigo_ibge.isna()].iterrows():
        key = (row.SG_UF, row.CHAVE)
        if counts.get(key, 0) == 1:
            match = exact.loc[key]
            if isinstance(match, pd.DataFrame):
                match = match.iloc[0]
            if match.codigo_ibge in set(geo.codigo_ibge):
                towns.loc[index, ["codigo_ibge", "DDD", "DDD_STATUS"]] = [match.codigo_ibge, match.ddd_anatel, "validado Anatel"]
                resolved_official.append({"uf": row.SG_UF, "tse": row.CD_MUNICIPIO, "ibge": match.codigo_ibge, "name": row.NM_MUNICIPIO})
    state_names = geo.dropna(subset=["estado"]).drop_duplicates("SG_UF").set_index("SG_UF").estado
    towns["estado"] = towns.SG_UF.map(state_names)
    towns["DDD_STATUS"] = towns.DDD_STATUS.fillna("nome sem correspondência")
    save(towns, "municipios.parquet")
    (OUT / "anatel_original.csv").write_bytes(response.content)
    unavailable = towns[towns.DDD.isna()][["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "DDD_STATUS"]].to_dict("records")
    return {**source(path), "anatel_url": ANATEL, "anatel_sha256": hashlib.sha256(response.content).hexdigest(), "anatel_original_columns": headers, "municipalities": len(towns), "matched_ibge": int(towns.codigo_ibge.notna().sum()), "validated_ddd": int(towns.DDD.notna().sum()), "ambiguous_ibge": sorted(ambiguous), "corrected_local_ddd": int((geo.ddd_anatel.notna() & geo.ddd.ne(geo.ddd_anatel)).sum()), "resolved_by_anatel_name_uf": resolved_official, "unavailable": unavailable}


def maps():
    sources = []
    for level, filename in [("UF", "brasil_uf.geojson"), ("municipio", "brasil_municipios.geojson")]:
        url = MALHAS + level
        r = requests.get(url, timeout=90)
        r.raise_for_status()
        data = r.json()
        if data.get("type") != "FeatureCollection" or not data.get("features"):
            raise ValueError("Malha IBGE inválida")
        for feature in data["features"]:
            if "codarea" not in feature.get("properties", {}):
                raise ValueError("Malha sem codarea")
        (ASSETS / filename).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        sources.append({"url": url, "file": filename, "features": len(data["features"]), "sha256": sha(ASSETS / filename), "projection": "WGS84, visualização Mercator", "quality": "minima"})
        print(f"Malha {level}: {len(data['features'])} regiões", flush=True)
    return sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-profile", action="store_true", help="Reusar perfil já processado, verificando hash do ZIP")
    parser.add_argument("--only-candidates", action="store_true", help="Gerar somente candidatos.parquet sobre uma preparação concluída")
    parser.add_argument("--divulgacao", action="store_true", help="Integrar resultados do portal de divulgação (2º turno) sobre uma preparação concluída")
    parser.add_argument("--horarios", action="store_true", help="Integrar horários das urnas (urnas-tardias e coleta própria de logs)")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    old = json.loads((OUT / "manifest.json").read_text(encoding="utf-8")) if (OUT / "manifest.json").exists() else {}
    if args.only_candidates or args.divulgacao or args.horarios:
        # Não reprocessa votos, perfil, geografia nem malhas: exige derivados íntegros.
        rebuilt = {"candidatos.parquet"} if args.only_candidates else set()
        rebuilt |= {"votos_divulgacao.parquet", "totalizacao.parquet", "candidatos.parquet"} if args.divulgacao else set()
        rebuilt |= {"horarios_secoes.parquet", "horarios_faixas.parquet"} if args.horarios else set()
        if not old or any(sha(OUT / name) != digest for name, digest in old["outputs"].items() if name not in rebuilt):
            raise ValueError("Preparação ausente ou alterada. Execute a preparação completa.")
        if args.only_candidates:
            old["sources"]["candidates"] = candidates()
        if args.divulgacao:
            report, rows, totals = divulgacao()
            if report is None:
                raise ValueError("Coleta de divulgação ausente: execute scripts/baixar_divulgacao.py")
            old["sources"]["divulgacao"] = {"elections": report, "rows_new_periods": rows, "totalization_rows": totals}
        if args.horarios:
            report = horarios()
            if report is None:
                raise ValueError("secoes.csv do urnas-tardias ausente em dados/brutos/urnas_tardias/<commit>/")
            old["sources"]["timing"] = report
        old["outputs"].update({name: sha(OUT / name) for name in rebuilt if (OUT / name).exists()})
        temp = OUT / "manifest.tmp"
        temp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(OUT / "manifest.json")
        if args.divulgacao:
            from auditar_totalizacao import audit
            audit()
        print(json.dumps({"success": True, "outputs": sorted(rebuilt)}, ensure_ascii=False), flush=True)
        return
    manifest = {"schema_version": 1, "prepared_at": datetime.now(timezone.utc).isoformat(), "classification": "arquivos TSE fornecidos no projeto; agregados reconciliados com os originais locais", "scope": "Brasil sem exterior", "sources": {}}
    manifest["sources"]["votes"] = votes()
    manifest["sources"]["candidates"] = candidates()
    if args.skip_profile:
        if not (OUT / "perfil.parquet").exists() or old.get("sources", {}).get("profile", {}).get("sha256") != sha(ROOT / "dados/brutos/perfil_eleitorado_2026.zip"):
            raise ValueError("Perfil ausente ou origem alterada. Reprocesse sem --skip-profile.")
        manifest["sources"]["profile"] = old["sources"]["profile"]
    else:
        manifest["sources"]["profile"] = profile()
    manifest["sources"]["geography"] = geography()
    manifest["sources"]["maps"] = maps()
    report, rows, totals = divulgacao()
    if report:
        manifest["sources"]["divulgacao"] = {"elections": report, "rows_new_periods": rows, "totalization_rows": totals}
    timing = horarios()
    if timing:
        manifest["sources"]["timing"] = timing
    manifest["outputs"] = {p.name: sha(p) for p in OUT.glob("*.parquet")}
    temp = OUT / "manifest.tmp"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT / "manifest.json")
    if report:
        from auditar_totalizacao import audit
        audit()
    print(json.dumps({"success": True, "votes": manifest["sources"]["votes"]["total"], "profile": manifest["sources"]["profile"]["total"], "ddd": manifest["sources"]["geography"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
