from pathlib import Path
import hashlib
import json
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Lampiadim_MVP"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lampiadim.data import ElectoralData
from referencia import Reference, br, pct  # noqa: F401 - reexportados para os testes


@pytest.fixture(scope="session")
def data():
    return ElectoralData()


@pytest.fixture(scope="session")
def ref():
    """Consultas de referência independentes do assistente (tests/referencia.py)."""
    return Reference()


# ---------------------------------------------------------------------------
# Base sintética mínima, no mesmo contrato dos arquivos preparados, para cenários
# que a base real não contém (dois anos, dois turnos, empates, território sem votos).

def _sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


@pytest.fixture(scope="session")
def synthetic(tmp_path_factory):
    directory = tmp_path_factory.mktemp("sintetica")
    towns = pd.DataFrame({"SG_UF": ["SP", "SP", "RJ", "RJ", "SP"], "CD_MUNICIPIO": ["90001", "90002", "90003", "90004", "90005"],
                          "NM_MUNICIPIO": ["ALFAVILLE", "BETANOPOLIS", "GAMALANDIA", "DELTARIO", "EXEMPLOPOLIS"],
                          "CHAVE": ["ALFAVILLE", "BETANOPOLIS", "GAMALANDIA", "DELTARIO", "EXEMPLOPOLIS"],
                          "codigo_ibge": ["1", "2", "3", "4", "5"], "DDD": pd.array([19, 19, 21, 21, 19], dtype="Int64"), "DDD_STATUS": ["validado Anatel"] * 5,
                          "estado": ["São Paulo", "São Paulo", "Rio de Janeiro", "Rio de Janeiro", "São Paulo"]})
    rows = []
    # Exemplopolis reproduz o exemplo obrigatório do simulador: 100 votos, eleitorado 60% / 30% / 10%.
    results = {(2022, 1): {"90001": (300, 200), "90002": (50, 80), "90003": (10, 10), "90004": (0, 0), "90005": (0, 0)},
               (2022, 2): {"90001": (400, 250), "90002": (90, 70), "90003": (20, 5), "90004": (0, 0), "90005": (0, 0)},
               (2026, 1): {"90001": (100, 100), "90002": (100, 40), "90003": (7, 30), "90004": (0, 0), "90005": (100, 50)}}
    for (year, turn), towns_votes in results.items():
        for code, (lula, other) in towns_votes.items():
            town = towns[towns.CD_MUNICIPIO == code].iloc[0]
            rows.append({"ANO_ELEICAO": year, "NR_TURNO": turn, "SG_UF": town.SG_UF, "CD_MUNICIPIO": code, "NM_MUNICIPIO": town.NM_MUNICIPIO,
                         "NR_CANDIDATO": 13, "NM_URNA_CANDIDATO": "LULA", "SG_PARTIDO": "PT", "VOTOS": lula})
            rows.append({"ANO_ELEICAO": year, "NR_TURNO": turn, "SG_UF": town.SG_UF, "CD_MUNICIPIO": code, "NM_MUNICIPIO": town.NM_MUNICIPIO,
                         "NR_CANDIDATO": 45, "NM_URNA_CANDIDATO": "ZEFERINO", "SG_PARTIDO": "XYZ", "VOTOS": other})
    votes = pd.DataFrame(rows)
    info = votes.groupby(["ANO_ELEICAO", "NR_TURNO", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO"], as_index=False).VOTOS.sum().rename(columns={"VOTOS": "VOTOS_BRASIL"})
    info["NM_CANDIDATO"] = info.NM_URNA_CANDIDATO.map({"LULA": "LUIZ INÁCIO LULA DA SILVA", "ZEFERINO": "JOSE ZEFERINO TESTE"})
    info["NM_PARTIDO"] = info.SG_PARTIDO.map({"PT": "PARTIDO DOS TRABALHADORES", "XYZ": "PARTIDO SINTETICO"})
    info["NM_SOCIAL_CANDIDATO"] = None
    info["NM_COLIGACAO"] = "PARTIDO ISOLADO"
    info["DS_COMPOSICAO_COLIGACAO"] = ""
    info["DS_SIT_TOT_TURNO"] = "2º TURNO"
    info["VOTOS_EXTERIOR"] = 0
    profile = pd.DataFrame([{"AA_ELEICAO": 2026, "SG_UF": t.SG_UF, "CD_MUNICIPIO": t.CD_MUNICIPIO, "NM_MUNICIPIO": t.NM_MUNICIPIO, "DS_GENERO": sexo,
                             "DS_IDENTIDADE_GENERO": "NÃO INFORMADO", "DS_FAIXA_ETARIA": age, "DS_GRAU_ESCOLARIDADE": "SUPERIOR COMPLETO", "QT_ELEITORES": n}
                            for t in towns.itertuples() for sexo, age, n in
                            ([("FEMININO", "18 anos", 60), ("MASCULINO", "21 a 24 anos", 30), ("NÃO INFORMADO", "60 a 64 anos", 10)] if t.CD_MUNICIPIO == "90005" else
                             [("FEMININO", "18 anos", 30), ("MASCULINO", "21 a 24 anos", 20), ("NÃO INFORMADO", "60 a 64 anos", 0 if t.CD_MUNICIPIO == "90004" else 1)])])
    for column in ["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "DS_GENERO", "DS_IDENTIDADE_GENERO", "DS_FAIXA_ETARIA", "DS_GRAU_ESCOLARIDADE"]:
        profile[column] = profile[column].astype("category")
    # Linha do tempo de três urnas do 1º turno de 2026 (uma estendida), sem qualquer coluna de candidatura.
    sections = pd.DataFrame({"ANO_ELEICAO": 2026, "NR_TURNO": 1, "SG_UF": "SP", "CD_MUNICIPIO": ["90001", "90001", "90005"], "ZONA": "0001",
                             "SECAO": ["0001", "0002", "0003"], "FUSO_H": 0, "ABERTURA": ["08:00:01", "08:00:03", "08:00:02"],
                             "ENCERRAMENTO": ["17:02:10", "17:05:00", "18:10:44"], "ULTIMO_VOTO": ["16:58:00", "16:40:00", "18:05:12"],
                             "VOTOS_APOS_17H": [0, 0, 7], "VOTOS_APOS_17H20": [0, 0, 4], "VOTOS_LOG": [120, 80, 130], "ESTENDIDA": [False, False, True],
                             "FONTE": "sintética"})
    hours = pd.DataFrame([{"ANO_ELEICAO": 2026, "NR_TURNO": 1, "SG_UF": "SP", "CD_MUNICIPIO": mun, "ZONA": "0001", "SECAO": sec, "HORA": h, "VOTOS": v}
                          for mun, sec, split in [("90001", "0001", {8: 50, 12: 40, 16: 30}), ("90001", "0002", {9: 30, 15: 50}),
                                                  ("90005", "0003", {8: 60, 13: 50, 16: 13, 17: 3, 18: 4})] for h, v in split.items()])
    outputs = {}
    for name, frame in [("votos.parquet", votes), ("perfil.parquet", profile), ("municipios.parquet", towns), ("candidatos.parquet", info),
                        ("horarios_secoes.parquet", sections), ("horarios_faixas.parquet", hours)]:
        frame.to_parquet(directory / name, index=False)
        outputs[name] = _sha(directory / name)
    manifest = {"schema_version": 1, "prepared_at": "2026-10-26T00:00:00+00:00", "outputs": outputs,
                "sources": {"votes": {"file": "sintetico", "generated_dates": ["01/01/2026"], "sha256": "0" * 64},
                            "profile": {"file": "sintetico", "generated_dates": ["01/01/2026"], "sha256": "0" * 64},
                            "candidates": {"file": "sintetico", "sha256": "0" * 64},
                            "geography": {"unavailable": [], "sha256": "0" * 64},
                            "timing": {"urnas_tardias": {"commit": "sintetico", "sha256": "0" * 64}, "coleta_propria": {"municipios_cobertos": {"1": ["90001", "90005"]}},
                                       "validacao_cruzada": {"secoes_comparadas": 0, "divergentes": 0}, "regra_estendida": "17h45", "fuso": "moda"}}}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ElectoralData(directory=directory)
