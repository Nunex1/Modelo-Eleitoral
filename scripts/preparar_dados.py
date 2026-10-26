"""ETL reexecutável: preserva insumos, reconcilia notebook, audita DDD e salva linhagem."""
from __future__ import annotations

import argparse
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
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    old = json.loads((OUT / "manifest.json").read_text(encoding="utf-8")) if (OUT / "manifest.json").exists() else {}
    manifest = {"schema_version": 1, "prepared_at": datetime.now(timezone.utc).isoformat(), "classification": "arquivos TSE fornecidos no projeto; agregados reconciliados com os originais locais", "scope": "Brasil sem exterior", "sources": {}}
    manifest["sources"]["votes"] = votes()
    if args.skip_profile:
        if not (OUT / "perfil.parquet").exists() or old.get("sources", {}).get("profile", {}).get("sha256") != sha(ROOT / "dados/brutos/perfil_eleitorado_2026.zip"):
            raise ValueError("Perfil ausente ou origem alterada. Reprocesse sem --skip-profile.")
        manifest["sources"]["profile"] = old["sources"]["profile"]
    else:
        manifest["sources"]["profile"] = profile()
    manifest["sources"]["geography"] = geography()
    manifest["sources"]["maps"] = maps()
    manifest["outputs"] = {p.name: sha(p) for p in OUT.glob("*.parquet")}
    temp = OUT / "manifest.tmp"
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT / "manifest.json")
    print(json.dumps({"success": True, "votes": manifest["sources"]["votes"]["total"], "profile": manifest["sources"]["profile"]["total"], "ddd": manifest["sources"]["geography"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
