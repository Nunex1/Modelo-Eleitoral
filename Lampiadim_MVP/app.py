"""Lampiadim | Painel descritivo eleitoral 2026.

Fontes locais: agregados oficiais TSE e tabela geográfica auxiliar de DDD.
Votos individuais e votos por gênero não são identificáveis nesses dados.
"""

from pathlib import Path
import re
import unicodedata

import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
VOTOS_ARQ = BASE / "resultado_presidencial_2026_brasil.csv"
PERFIL_ARQ = BASE / "perfil_demografico_municipios_2026.csv"
GEO_ARQ = BASE / "base cidades completa.xlsx"

st.set_page_config(page_title="Lampiadim | Modelo Eleitoral", page_icon="💡", layout="wide")


def normalizar(texto):
    valor = unicodedata.normalize("NFKD", str(texto))
    valor = "".join(c for c in valor if not unicodedata.combining(c)).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", valor).split())


def formato_inteiro(valor):
    return f"{int(valor):,}".replace(",", ".")


def formato_pct(valor):
    return f"{float(valor):.1f}%".replace(".", ",")


@st.cache_data(show_spinner="Carregando bases eleitorais...")
def carregar():
    for caminho in [VOTOS_ARQ, PERFIL_ARQ, GEO_ARQ]:
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo ausente: {caminho.name}")

    votos = pd.read_csv(VOTOS_ARQ, encoding="utf-8-sig", dtype={"CD_MUNICIPIO": "string"})
    perfil = pd.read_csv(PERFIL_ARQ, encoding="utf-8-sig", dtype={"CD_MUNICIPIO": "string"})
    geo = pd.read_excel(GEO_ARQ)
    geo.columns = geo.columns.str.strip().str.lower()

    requeridos_votos = {"SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NM_URNA_CANDIDATO", "VOTOS"}
    requeridos_perfil = {"SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "DS_GENERO", "DS_IDENTIDADE_GENERO", "QT_ELEITORES"}
    requeridos_geo = {"uf", "cidade", "ddd"}
    for titulo, frame, required in [
        ("Resultados eleitorais", votos, requeridos_votos),
        ("Perfil cadastral", perfil, requeridos_perfil),
        ("Geografia", geo, requeridos_geo),
    ]:
        faltam = required - set(frame.columns)
        if faltam:
            raise ValueError(f"{titulo}: colunas ausentes: {', '.join(sorted(faltam))}")

    for frame in [votos, perfil]:
        frame["SG_UF"] = frame["SG_UF"].astype(str).str.strip().str.upper()
        frame["NM_MUNICIPIO"] = frame["NM_MUNICIPIO"].astype(str).str.strip().str.upper()
        frame["CD_MUNICIPIO"] = frame["CD_MUNICIPIO"].astype(str).str.replace(r"\.0$", "", regex=True)
        frame["CHAVE_CIDADE"] = frame["NM_MUNICIPIO"].map(normalizar)

    votos["VOTOS"] = pd.to_numeric(votos["VOTOS"], errors="raise")
    perfil["QT_ELEITORES"] = pd.to_numeric(perfil["QT_ELEITORES"], errors="raise")
    if (votos["VOTOS"] < 0).any() or (perfil["QT_ELEITORES"] < 0).any():
        raise ValueError("Encontradas quantidades negativas de votos ou eleitores.")

    geo["SG_UF"] = geo["uf"].astype(str).str.upper().str.strip()
    geo["CHAVE_CIDADE"] = geo["cidade"].map(normalizar)
    geo["DDD"] = pd.to_numeric(geo["ddd"], errors="coerce").astype("Int64")
    if geo.duplicated(["SG_UF", "CHAVE_CIDADE"]).any():
        repetidos = geo.loc[geo.duplicated(["SG_UF", "CHAVE_CIDADE"], keep=False), ["SG_UF", "cidade"]]
        raise ValueError(f"Tabela geográfica contém chaves duplicadas: {repetidos.head().to_dict('records')}")

    mapa = geo[["SG_UF", "CHAVE_CIDADE", "DDD"]].copy()
    for frame in [votos, perfil]:
        antes = len(frame)
        frame = frame  # checagem do mapa feita na junção abaixo
        assert len(frame) == antes

    votos = votos.merge(mapa, on=["SG_UF", "CHAVE_CIDADE"], how="left", validate="many_to_one")
    perfil = perfil.merge(mapa, on=["SG_UF", "CHAVE_CIDADE"], how="left", validate="many_to_one")

    perfil["DS_GENERO"] = perfil["DS_GENERO"].fillna("NÃO INFORMADO").astype(str).str.strip().str.upper()
    identidade = perfil["DS_IDENTIDADE_GENERO"].fillna("NÃO INFORMADO").astype(str).str.strip()
    perfil["IDENTIDADE_AGRUPADA"] = identidade.map(
        lambda x: "NÃO INFORMADO / PREFERE NÃO INFORMAR"
        if normalizar(x) in {"NAO INFORMADO", "PREFERE NAO INFORMAR"} else x
    )

    chaves = ["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"]
    votos_locs = votos[chaves + ["DDD"]].drop_duplicates()
    perfil_locs = perfil[chaves + ["DDD"]].drop_duplicates()
    faltantes = pd.concat([
        votos_locs[votos_locs["DDD"].isna()][chaves],
        perfil_locs[perfil_locs["DDD"].isna()][chaves],
    ]).drop_duplicates()
    return votos, perfil, faltantes


def filtrar_geografia(frame, uf="Todos", cidade="Todos", ddd="Todos"):
    selecionado = frame
    if uf != "Todos":
        selecionado = selecionado[selecionado["SG_UF"] == uf]
    if cidade != "Todos":
        selecionado = selecionado[selecionado["NM_MUNICIPIO"] == cidade]
    if ddd != "Todos":
        selecionado = selecionado[selecionado["DDD"].eq(int(ddd)).fillna(False)]
    return selecionado


def votos_por_candidatura(dados):
    tab = dados.groupby("NM_URNA_CANDIDATO", as_index=False)["VOTOS"].sum()
    tab = tab.sort_values("VOTOS", ascending=False).reset_index(drop=True)
    denominador = tab["VOTOS"].sum()
    tab["PERCENTUAL"] = 100 * tab["VOTOS"] / denominador if denominador else 0.0
    return tab


def genero_do_eleitorado(dados):
    tab = dados.groupby("DS_GENERO", as_index=False)["QT_ELEITORES"].sum()
    tab = tab.sort_values("QT_ELEITORES", ascending=False)
    denominador = tab["QT_ELEITORES"].sum()
    tab["PERCENTUAL"] = 100 * tab["QT_ELEITORES"] / denominador if denominador else 0.0
    return tab


def exibir_tabela_votos(tab):
    exibir = tab.copy()
    exibir["VOTOS"] = exibir["VOTOS"].map(formato_inteiro)
    exibir["PERCENTUAL"] = exibir["PERCENTUAL"].map(formato_pct)
    st.dataframe(exibir, hide_index=True, width="stretch")


def exibir_tabela_genero(tab):
    exibir = tab.copy()
    exibir["QT_ELEITORES"] = exibir["QT_ELEITORES"].map(formato_inteiro)
    exibir["PERCENTUAL"] = exibir["PERCENTUAL"].map(formato_pct)
    st.dataframe(exibir, hide_index=True, width="stretch")


st.title("💡 Lampiadim")
st.caption("Eleições presidenciais de 2026 | Primeiro turno | Votos e perfil do eleitorado agregados")

try:
    votos, perfil, sem_ddd = carregar()
except (FileNotFoundError, ValueError, KeyError) as exc:
    st.error(str(exc))
    st.info("Confira os nomes e as colunas dos três arquivos na pasta do app.py.")
    st.stop()

if not sem_ddd.empty:
    st.warning(
        f"Correspondência incompleta de DDD: {len(sem_ddd)} município(s) "
        "sem associação. Totais dos filtros por DDD podem estar incompletos."
    )
    with st.expander("Ver municípios sem DDD"):
        st.dataframe(sem_ddd, hide_index=True, width="stretch")

ufs = sorted(perfil["SG_UF"].unique().tolist())
with st.sidebar:
    st.header("Filtros geográficos")
    uf = st.selectbox("Estado", ["Todos"] + ufs)
    municipios_uf = perfil if uf == "Todos" else perfil[perfil["SG_UF"] == uf]
    cidades = sorted(municipios_uf["NM_MUNICIPIO"].dropna().unique().tolist())
    cidade = st.selectbox("Cidade", ["Todos"] + cidades)
    scope_ddd = filtrar_geografia(perfil, uf, cidade)
    ddds = sorted(scope_ddd["DDD"].dropna().astype(int).unique().tolist())
    ddd = st.selectbox("DDD", ["Todos"] + ddds)
    st.divider()
    st.header("Filtros de análise")
    candidaturas = sorted(votos["NM_URNA_CANDIDATO"].dropna().unique().tolist())
    candidato = st.selectbox("Candidatura presidencial", ["Todas"] + candidaturas)
    generos = sorted(perfil["DS_GENERO"].dropna().unique().tolist())
    genero = st.selectbox("Gênero cadastral", ["Todos"] + generos)
    identidades = sorted(perfil["IDENTIDADE_AGRUPADA"].dropna().unique().tolist())
    identidade = st.selectbox("Identidade de gênero", ["Todos"] + identidades)
    st.caption("Gênero e identidade filtram apenas o cadastro do eleitorado; não os votos dos candidatos.")

votos_escopo = filtrar_geografia(votos, uf, cidade, ddd)
perfil_escopo = filtrar_geografia(perfil, uf, cidade, ddd)
perfil_selecionado = perfil_escopo.copy()
if genero != "Todos":
    perfil_selecionado = perfil_selecionado[perfil_selecionado["DS_GENERO"] == genero]
if identidade != "Todos":
    perfil_selecionado = perfil_selecionado[perfil_selecionado["IDENTIDADE_AGRUPADA"] == identidade]

tab_votos = votos_por_candidatura(votos_escopo)
tab_genero = genero_do_eleitorado(perfil_escopo)
if candidato != "Todas":
    tab_votos_exibido = tab_votos[tab_votos["NM_URNA_CANDIDATO"] == candidato]
else:
    tab_votos_exibido = tab_votos

aba_dashboard, aba_chat = st.tabs(["Dashboard", "Pergunte ao Lampiadim"])

with aba_dashboard:
    c1, c2, c3 = st.columns(3)
    c1.metric("Votos nominais válidos", formato_inteiro(votos_escopo["VOTOS"].sum()))
    c2.metric("Eleitores cadastrados", formato_inteiro(perfil_escopo["QT_ELEITORES"].sum()))
    c3.metric("Eleitores no perfil selecionado", formato_inteiro(perfil_selecionado["QT_ELEITORES"].sum()))
    st.caption("O eleitorado cadastrado não é equivalente à quantidade de eleitores que compareceram à votação.")

    esquerda, direita = st.columns(2)
    with esquerda:
        st.subheader("Votos por candidatura")
        if tab_votos_exibido.empty:
            st.info("Não há votos para os filtros selecionados.")
        else:
            st.bar_chart(tab_votos_exibido, x="NM_URNA_CANDIDATO", y="PERCENTUAL", horizontal=True)
            exibir_tabela_votos(tab_votos_exibido)
    with direita:
        st.subheader("Composição do eleitorado por gênero cadastral")
        if tab_genero.empty:
            st.info("Não há registros cadastrais para os filtros selecionados.")
        else:
            st.bar_chart(tab_genero, x="DS_GENERO", y="PERCENTUAL", horizontal=True)
            exibir_tabela_genero(tab_genero)

    st.subheader("Identidade de gênero registrada")
    tabela_ident = perfil_escopo.groupby("IDENTIDADE_AGRUPADA", as_index=False)["QT_ELEITORES"].sum()
    if not tabela_ident.empty:
        denom = tabela_ident["QT_ELEITORES"].sum()
        tabela_ident["PERCENTUAL"] = 100 * tabela_ident["QT_ELEITORES"] / denom if denom else 0.0
        exibir_tabela_genero(tabela_ident)

    st.download_button(
        "Baixar tabela eleitoral filtrada (CSV)",
        data=tab_votos_exibido.to_csv(index=False).encode("utf-8-sig"),
        file_name="lampiadim_votos_filtrados.csv",
        mime="text/csv",
    )
    st.info("Os resultados eleitorais são agregados. Não existe vínculo individual entre voto e gênero, identidade ou renda.")

with aba_chat:
    st.subheader("Pergunte em português")
    st.caption('Exemplo: "Lampiadim, em Americana, compare os votos de Lula e Bolsonaro e mostre homens e mulheres cadastrados."')
    pergunta = st.chat_input("Faça sua pergunta sobre uma cidade ou um DDD...")
    if pergunta:
        with st.chat_message("user"):
            st.write(pergunta)
        with st.chat_message("assistant"):
            pergunta_norm = normalizar(pergunta)
            uf_q, cidade_q, ddd_q = uf, cidade, ddd

            encontrou_ddd = re.search(r"\bDDD\s*(\d{2})\b", pergunta_norm)
            if encontrou_ddd:
                ddd_q = int(encontrou_ddd.group(1))
                cidade_q = "Todos"

            cidades_disponiveis = perfil[["SG_UF", "NM_MUNICIPIO"]].drop_duplicates()
            cidades_disponiveis = cidades_disponiveis.assign(
                TEXTO=cidades_disponiveis["NM_MUNICIPIO"].map(normalizar)
            )
            cidades_disponiveis = cidades_disponiveis.sort_values("TEXTO", key=lambda s: s.str.len(), ascending=False)
            encontradas = cidades_disponiveis[
                cidades_disponiveis["TEXTO"].map(
                    lambda nome: bool(re.search(r"\b" + re.escape(nome) + r"\b", pergunta_norm))
                    if nome else False
                )
            ]
            if not encontradas.empty:
                melhor_nome = encontradas.iloc[0]["TEXTO"]
                correspondentes = encontradas[encontradas["TEXTO"] == melhor_nome]
                if len(correspondentes) > 1 and uf == "Todos":
                    st.warning("Há municípios homônimos. Selecione o estado na barra lateral e repita a pergunta.")
                    st.stop()
                if uf != "Todos":
                    possiveis = correspondentes[correspondentes["SG_UF"] == uf]
                    if not possiveis.empty:
                        correspondentes = possiveis
                uf_q = correspondentes.iloc[0]["SG_UF"]
                cidade_q = correspondentes.iloc[0]["NM_MUNICIPIO"]
                ddd_q = "Todos"

            vq = filtrar_geografia(votos, uf_q, cidade_q, ddd_q)
            pq = filtrar_geografia(perfil, uf_q, cidade_q, ddd_q)
            if vq.empty or pq.empty:
                st.write("Não encontrei dados completos para essa localidade. Confira o estado, a cidade ou o DDD.")
            else:
                local = cidade_q if cidade_q != "Todos" else f"DDD {ddd_q}" if ddd_q != "Todos" else uf_q if uf_q != "Todos" else "Brasil (sem exterior)"
                st.write(f"**Localidade analisada:** {local}")
                if any(p in pergunta_norm for p in ["SEXO", "GENERO", "HOMEM", "MULHER", "MASCULINO", "FEMININO"]):
                    st.info(
                        "Não é possível identificar o gênero dos votantes de uma candidatura. "
                        "Os resultados são agregados e o voto individual é secreto. "
                        "Abaixo mostro os votos totais e a composição cadastral separadamente."
                    )

                quadro = votos_por_candidatura(vq)
                solicitados = [nome for nome in quadro["NM_URNA_CANDIDATO"]
                               if normalizar(nome) in pergunta_norm
                               or ("BOLSONARO" in pergunta_norm and "BOLSONARO" in normalizar(nome))]
                if solicitados:
                    quadro = quadro[quadro["NM_URNA_CANDIDATO"].isin(solicitados)]
                else:
                    quadro = quadro.head(5)
                st.write("**Votação nominal válida das candidaturas:**")
                exibir_tabela_votos(quadro)
                st.write("**Eleitores cadastrados por gênero:**")
                exibir_tabela_genero(genero_do_eleitorado(pq))
                st.caption("Percentuais das candidaturas: votos válidos da localidade. Percentuais demográficos: eleitores cadastrados da localidade.")

st.caption("Fontes: TSE, votação presidencial e perfil do eleitorado 2026. DDD: tabela geográfica auxiliar. Renda municipal será integrada em etapa posterior.")
