from dataclasses import replace
import io
import pandas as pd
import pytest

from lampiadim.data import ROOT, DIMENSIONS, Filters, csv_bytes
from lampiadim import charts


def test_full_reconciliation_with_original_files(data):
    old_votes = pd.read_csv(ROOT / "Lampiadim_MVP/resultado_presidencial_2026_brasil.csv")
    old_profile = pd.read_csv(ROOT / "Lampiadim_MVP/perfil_demografico_municipios_2026.csv")
    r = data.query(Filters())
    assert r["votes"] == int(old_votes.VOTOS.sum()) == 118_969_906
    assert r["registered"] == int(old_profile.QT_ELEITORES.sum()) == 157_826_587
    keys = ["SG_UF", "CD_MUNICIPIO", "DS_GENERO", "DS_IDENTIDADE_GENERO"]
    old_profile.CD_MUNICIPIO = old_profile.CD_MUNICIPIO.astype(str).str.zfill(5)
    actual = data.profile.groupby(keys, observed=True).QT_ELEITORES.sum().reset_index()
    for key in keys:
        actual[key] = actual[key].astype(str)
    pd.testing.assert_series_equal(actual.set_index(keys).QT_ELEITORES.sort_index(), old_profile.set_index(keys).QT_ELEITORES.sort_index(), check_names=False)


def test_state_totals_reconcile_and_names_exist(data):
    assert len(data.states) == 27
    assert all(isinstance(x, str) for x in data.states.values())
    results = [data.query(Filters(uf=uf)) for uf in data.states]
    assert sum(r["votes"] for r in results) == data.query(Filters())["votes"]
    assert sum(r["registered"] for r in results) == data.query(Filters())["registered"]
    assert sum(r["municipalities"] for r in results) == 5571


def test_americana_real_values(data):
    r = data.query(Filters(uf="SP", municipality="61310"))
    assert r["votes"] == 136589
    assert r["registered"] == 180962
    assert r["municipalities"] == 1
    assert r["difference"] == 49086
    assert r["all_candidates"].PERCENTUAL.sum() == pytest.approx(100)


def test_candidate_selection_does_not_change_denominator(data):
    r = data.query(Filters(uf="SP", municipality="61310", candidate="LULA"))
    assert len(r["candidates"]) == 1
    assert r["candidates"].iloc[0].VOTOS == 37768
    assert r["candidates"].iloc[0].PERCENTUAL == pytest.approx(100 * 37768 / 136589)
    assert r["votes"] == 136589
    assert r["difference"] == 49086


def test_joint_demographic_filters_do_not_attribute_votes(data):
    f = Filters(uf="SP", municipality="61310", sexo="FEMININO", idade="35 a 39 anos", escolaridade="SUPERIOR COMPLETO", identidade="Cisgênero")
    r = data.query(f)
    expected = data.profile[(data.profile.CD_MUNICIPIO == "61310") & (data.profile.DS_GENERO == "FEMININO") & (data.profile.DS_FAIXA_ETARIA == "35 a 39 anos") & (data.profile.DS_GRAU_ESCOLARIDADE == "SUPERIOR COMPLETO") & (data.profile.DS_IDENTIDADE_GENERO == "Cisgênero")].QT_ELEITORES.sum()
    assert r["selected_profile"] == int(expected) > 0
    assert r["votes"] == 136589 and r["registered"] == 180962
    for table in r["demographics"].values():
        assert table.QT_ELEITORES.sum() == expected
        assert table.PERCENTUAL.sum() == pytest.approx(100)


def test_ddd_never_multiplies_municipalities(data):
    towns = data.geography(Filters(ddd=19))
    assert towns.CD_MUNICIPIO.is_unique
    assert towns.DDD_STATUS.eq("validado Anatel").all()
    original = pd.read_csv(ROOT / "Lampiadim_MVP/resultado_presidencial_2026_brasil.csv", dtype={"CD_MUNICIPIO": str})
    original.CD_MUNICIPIO = original.CD_MUNICIPIO.str.zfill(5)
    expected = original[original.CD_MUNICIPIO.isin(towns.CD_MUNICIPIO)].VOTOS.sum()
    assert data.query(Filters(ddd=19))["votes"] == expected == 3213063


def test_empty_intersection_is_empty_and_rates_are_not_zero(data):
    r = data.query(Filters(uf="RJ", municipality="61310"))
    assert r["municipalities"] == 0
    assert r["candidates"].empty and r["difference_pp"] is None
    assert all(t.empty for t in r["demographics"].values())


@pytest.mark.parametrize("changes", [{"year": 2022}, {"turn": 2}, {"uf": "ZZ"}, {"candidate": "FAKE"}, {"ddd": 0}, {"municipality": "00000"}, {"idade": "Inventada"}])
def test_unsupported_filters_rejected(data, changes):
    with pytest.raises(ValueError):
        data.query(replace(Filters(), **changes))


def test_csv_reopens_with_same_filtered_values(data):
    f = Filters(uf="SP", municipality="61310", candidate="LULA")
    table = data.analytical_table(f)
    reopened = pd.read_csv(io.BytesIO(csv_bytes(table)), sep=";", decimal=",", encoding="utf-8-sig")
    assert len(reopened) == 1
    assert reopened.iloc[0]["Votos"] == 37768
    assert reopened.iloc[0]["% válidos"] == pytest.approx(100 * 37768 / 136589)
    assert reopened.iloc[0]["Município"] == "AMERICANA"


def test_csv_formula_cells_are_neutralized():
    content = csv_bytes(pd.DataFrame({"nome": ["=1+1", " +SUM(A1)", "Americana"]})).decode("utf-8-sig")
    assert "'=1+1" in content and "' +SUM(A1)" in content


def test_maps_have_real_geometry_and_selection_payload(data):
    assert len(charts.geometry("uf")) == 27
    sp = [f for f in charts.geometry("municipality") if str(f["properties"]["codarea"]).startswith("35")]
    assert len(sp) == 645
    chart = charts.territorial(data, Filters(uf="SP"), "municipality", "SP")
    assert len(chart.data) >= 646
    assert any(row[0] == "61310" for row in chart.data[-1].customdata)
    assert any("Americana" in str(row) for row in chart.data[-1].customdata)
