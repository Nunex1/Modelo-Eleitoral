"""Enriquece a totalização com categorias técnicas e reconcilia município → UF → BR.

Executar após preparar_dados.py --divulgacao. Não altera os arquivos brutos.
--verificar-remoto confere BR, Americana e Campinas contra o portal do TSE.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dados/tratados/lampiadim"
FIELDS = {
    "ELEITORADO_APTO": ("e", "te"), "COMPARECIMENTO": ("e", "c"), "ABSTENCAO": ("e", "a"),
    "APTOS_SECOES_NAO_INSTALADAS": ("e", "esni"), "APTOS_SECOES_NAO_APURADAS": ("e", "esna"),
    "VOTOS_VALIDOS": ("v", "vv"), "VOTOS_BRANCOS": ("v", "vb"), "VOTOS_NULOS": ("v", "tvn"),
    "NULOS_URNA": ("v", "vn"), "NULOS_TECNICOS": ("v", "vnt"), "ANULADOS": ("v", "van"),
    "ANULADOS_SUB_JUDICE": ("v", "vansj"), "VOTOS_SECOES_ANULADAS": ("v", "vsan"),
    "VOTOS_SEM_CANDIDATO_VALIDO": ("v", "vscv"),
}


def counts(doc):
    result = {}
    for name, (section, key) in FIELDS.items():
        value = doc[section][key]  # Ausência não é zero.
        if value is None or not str(value).isdigit():
            raise ValueError(f"Campo obrigatório inválido: {section}.{key}")
        result[name] = int(value)
    return result


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def audit(verify_remote=False):
    current = pd.read_parquet(OUT / "totalizacao.parquet")
    records, references, remote = [], {}, []
    for election, turn in [("6257", 1), ("6258", 2)]:
        folder = ROOT / "dados/brutos/divulgacao_2026" / election
        read = lambda path: json.loads(path.read_text(encoding="utf-8"))
        config = read(folder / f"mun-e00{election}-cm.json")
        national = {name: 0 for name in FIELDS}
        states = {}
        for state in config["abr"]:
            uf = state["cd"].lower()
            aggregated = {name: 0 for name in FIELDS}
            for city in state["mu"]:
                path = folder / uf / f"{uf}{city['cd']}-c0001-e00{election}-u.json"
                doc = read(path)
                if (doc["ele"], doc["t"], doc["cdabr"], doc["tpabr"]) != (election, str(turn), city["cd"], "mu"):
                    raise ValueError(f"Identificação divergente: {path}")
                values = counts(doc)
                records.append({"ANO_ELEICAO": 2026, "NR_TURNO": turn, "SG_UF": uf.upper(), "CD_MUNICIPIO": city["cd"],
                                **values, "FONTE": f"https://resultados.tse.jus.br/oficial/ele2026/{election}/dados/{uf}/{path.name}",
                                "GERACAO": f"{doc['dg']} {doc['hg']}", "SHA256": sha(path)})
                for key, value in values.items():
                    aggregated[key] += value
            control = counts(read(folder / uf / f"{uf}-c0001-e00{election}-u.json"))
            if aggregated != control:
                raise ValueError(f"Soma municipal diverge da UF {uf}: {aggregated} != {control}")
            states[uf.upper()] = control
            for key, value in control.items():
                national[key] += value
        path = folder / "br" / f"br-c0001-e00{election}-u.json"
        doc = read(path)
        if national != counts(doc):
            raise ValueError(f"Soma das UFs diverge do Brasil no turno {turn}")
        references[str(turn)] = {"brasil_com_exterior": national, "ufs": states, "sha256_br": sha(path),
                                "geracao": f"{doc['dg']} {doc['hg']}", "eleicao": election}
        if verify_remote:
            import requests
            for uf, code in [("br", ""), ("sp", "61310"), ("sp", "62910")]:
                filename = f"{uf}{code}-c0001-e00{election}-u.json"
                url = f"https://resultados.tse.jus.br/oficial/ele2026/{election}/dados/{uf}/{filename}"
                response = requests.get(url, timeout=40)
                response.raise_for_status()
                live, local = response.json(), read(folder / uf / filename)
                live_votes = {c['n']: c['vap'] for g in live['carg'][0]['agr'] for p in g['par'] for c in p['cand']}
                local_votes = {c['n']: c['vap'] for g in local['carg'][0]['agr'] for p in g['par'] for c in p['cand']}
                if counts(live) != counts(local) or live_votes != local_votes:
                    raise ValueError(f"A fonte remota mudou: {url}. Recolete antes de publicar.")
                remote.append({"url": url, "conferido_em": datetime.now(timezone.utc).isoformat(),
                               "sha256": hashlib.sha256(response.content).hexdigest(), "contagens_e_votos_conferem": True})
    frame = pd.DataFrame(records)
    keys = ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO"]
    if frame.duplicated(keys).any():
        raise ValueError("Município duplicado")
    merged = current.merge(frame, on=keys, validate="one_to_one", how="outer", indicator=True, suffixes=("_old", "_new"))
    if not merged._merge.eq("both").all():
        raise ValueError("Cobertura difere da totalização preparada")
    for key in set(FIELDS) & set(current):
        if not merged[key + "_old"].eq(merged[key + "_new"]).all():
            raise ValueError(f"Divergência na totalização preparada: {key}")
    report = {"verificado_em": datetime.now(timezone.utc).isoformat(), "referencias": references, "verificacao_remota": remote,
              "reconciliacao": "Todas as contagens: municípios = UFs; UFs + exterior = Brasil",
              "ajuste_tte": {"fonte": "https://dadosabertos.tse.jus.br/dataset/resultados-2026", "registros_duplicados": 39,
                             "registros_publicados": 158745502, "eleitorado_efetivo_nacional": 158745463,
                             "aplicacao": "Somente referência nacional; sem alocação territorial oficial dos duplicados. Não subtrair de cada recorte."}}
    frame.to_parquet(OUT / "totalizacao_detalhada.parquet", index=False)
    (OUT / "referencias_totalizacao.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    for name in ["totalizacao_detalhada.parquet", "referencias_totalizacao.json"]:
        manifest["outputs"][name] = sha(OUT / name)
    manifest["sources"]["auditoria_totalizacao"] = {"verificado_em": report["verificado_em"], "linhas": len(frame), "referencias": "referencias_totalizacao.json"}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"municipios_turnos": len(frame), "verificacoes_remotas": len(remote), "reconciliacao": report["reconciliacao"]}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verificar-remoto", action="store_true")
    audit(parser.parse_args().verificar_remoto)
