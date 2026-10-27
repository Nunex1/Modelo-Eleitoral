"""Infográficos integrados ao dashboard existente; lógica estatística em evolution."""
from dataclasses import asdict, replace
import json

import pandas as pd
import streamlit as st

from . import evolution_charts as figures
from .data import csv_bytes, integer, percent
from .engine import DataUnavailable, engine_for
from .entities import BRASIL, REGIONS, Territory
from .evolution import COMPOSITION, DEMOGRAPHIC_NOTE, FORMULAS, LABELS, WARNING, evolution_for, export_table, ratio, summary
from .evolution_exports import export_pdf, export_png
from .transfers import Assumptions, FLOW_WARNING, IncompatibleScenario, identification_bounds, margins, sensitivity, solve


def decimal(value, signed=False):
    return format(float(value), "+,.2f" if signed else ",.2f").replace(",", "_").replace(".", ",").replace("_", ".")


def selected_territory(data, filters):
    kb = engine_for(data).kb
    if filters.municipality:
        return kb.city_by_code[filters.municipality]
    if filters.ddd:
        return replace(kb.ddd(filters.ddd), uf=filters.uf)
    if filters.uf:
        return kb.state(filters.uf)
    if filters.region:
        return Territory("regiao", filters.region, REGIONS[filters.region][0])
    return BRASIL


def plot(fig, key, description):
    if fig is None:
        st.info("Gráfico indisponível: denominador igual a zero.")
        return
    st.plotly_chart(fig, key=key, width="stretch", config={"displayModeBar": False, "displaylogo": False})
    st.caption(description)


def show_table(frame):
    st.dataframe(frame, hide_index=True, width="stretch")


def stage(snapshot):
    t = snapshot["totals"]
    for row in [["LULA", "FLAVIO", "OUTROS"], ["VOTOS_VALIDOS", "COMPARECIMENTO", "ABSTENCAO"], ["VOTOS_BRANCOS", "VOTOS_NULOS"]]:
        for col, key in zip(st.columns(len(row)), row):
            with col:
                rate = snapshot["rates"].get(key)
                st.metric(LABELS[key], integer(t[key]), percent(rate) + " · " + LABELS[snapshot["denominators"][key]].lower(), delta_color="off")
    plot(figures.candidate_bars(snapshot), f"evolution_candidates_{snapshot['turn']}", "Barras: votos de cada candidatura divididos pelos votos válidos deste turno; demais candidatos são agregados.")


def lab(comparison):
    with st.expander("DE ONDE PODERIAM TER VINDO OS NOVOS VOTOS?"):
        st.warning(FLOW_WARNING)
        st.write("Uma matriz compatível com as margens não identifica os caminhos reais. Retenção e transferências abaixo são premissas escolhidas por você.")
        try:
            margins(comparison)
        except IncompatibleScenario as exc:
            st.info(str(exc))
            return
        st.caption("Modelo: programação linear de transporte, com margens fixas, não negatividade e restrições explícitas. O objetivo seleciona uma das matrizes possíveis; não estima probabilidades individuais.")
        constant = st.checkbox("Assumir, apenas para este cenário, que são as mesmas pessoas nos dois turnos", key="flow_constant")
        st.caption("A igualdade das contagens foi verificada. A identidade das pessoas não é observável nestes dados agregados.")
        left, right = st.columns(2)
        with left:
            lula = st.slider("Retenção mínima de Lula (%)", 0, 100, 80, key="flow_lula") / 100
            others_on = st.checkbox("Fixar parcela dos demais candidatos destinada a Lula", key="flow_others_on")
            others = st.slider("Demais candidatos → Lula (%)", 0, 100, 50, disabled=not others_on, key="flow_others") / 100 if others_on else None
        with right:
            flavio = st.slider("Retenção mínima de Flávio Bolsonaro (%)", 0, 100, 80, key="flow_flavio") / 100
            absent_on = st.checkbox("Fixar parcela da abstenção destinada a Lula", key="flow_absent_on")
            absent = st.slider("Abstenção → Lula (%)", 0, 100, 5, disabled=not absent_on, key="flow_absent") / 100 if absent_on else None
        invalid = st.slider("Máximo de brancos/nulos que passam a votos válidos (%)", 0, 100, 100, key="flow_invalid") / 100
        objective = st.selectbox("Objetivo exploratório", ["retencao", "outros", "abstencao"], key="flow_objective",
                                 format_func=lambda x: {"retencao": "Maximizar permanência nas categorias", "outros": "Maximizar demais candidatos → Lula", "abstencao": "Maximizar abstenção → Lula"}[x])
        if not constant:
            st.info("Declare a hipótese acima para executar o cenário.")
            return
        assumptions = Assumptions(constant, lula, flavio, others, absent, invalid, objective)
        try:
            scenario = solve(comparison, assumptions)
        except (IncompatibleScenario, ImportError) as exc:
            st.info(str(exc) if not isinstance(exc, ImportError) else "Solucionador indisponível. Instale as dependências da aplicação.")
            return
        plot(figures.sankey(scenario), "evolution_sankey", FLOW_WARNING)
        show_table(scenario["matrix"].rename_axis("Origem / destino").reset_index())
        low, high = scenario["conditional_bounds"]
        st.caption(f"Demais candidatos → Lula: limites compatíveis com estas restrições, {decimal(low)} a {decimal(high)}. São limites matemáticos, não intervalos de confiança.")
        with st.expander("Sensibilidade e limites de identificação"):
            show_table(sensitivity(comparison, assumptions))
            st.caption("Variam retenção mínima e objetivo. Resultados distintos sob as mesmas margens mostram a não identificação dos fluxos.")
            show_table(identification_bounds(comparison))
            st.caption("Limites sem restrições adicionais: máximo(0, origem + destino − total) até mínimo(origem, destino), condicionados à população fechada.")
        export = scenario["matrix"].rename_axis("Origem").reset_index()
        export["Aviso"] = FLOW_WARNING
        export["Hipóteses"] = json.dumps(asdict(assumptions), ensure_ascii=False)
        for column in ["Ano", "Território", "Fonte 1", "Fonte 2", "Atualização 1", "Atualização 2"]:
            export[column] = export_table(comparison)[column].iloc[0]
        st.download_button("Exportar cenário hipotético · CSV", csv_bytes(export), "lampiadim_cenario_hipotetico.csv", "text/csv", key="flow_csv")
        if st.button("Preparar PDF deste cenário", key="flow_pdf_prepare"):
            payload = export_pdf(comparison, scenario=scenario)
            st.download_button("Baixar PDF · simulação hipotética", payload, "lampiadim_cenario_hipotetico.pdf", "application/pdf", key="flow_pdf")


def geographic(service, filters, territory, codes):
    st.subheader("Onde as mudanças foram maiores?")
    st.caption("Mesmo recorte dos indicadores. Percentuais são calculados depois da soma das contagens oficiais.")
    columns = st.columns(3)
    with columns[0]:
        level = st.selectbox("Unidade territorial", ["uf", "municipio"], index=1 if filters.uf or filters.municipality else 0, key="evolution_level", format_func=lambda x: "Estados" if x == "uf" else "Municípios")
    with columns[1]:
        metric = st.selectbox("Indicador territorial", ["ABSTENCAO", "COMPARECIMENTO", "VOTOS_BRANCOS", "VOTOS_NULOS", "BRANCOS_NULOS", "LULA", "FLAVIO"], key="evolution_metric", format_func=lambda x: LABELS[x])
    with columns[2]:
        measures = {f"_TAXA_{filters.turn}": f"Taxa no {filters.turn}º turno (%)", f"_{filters.turn}": f"Quantidade no {filters.turn}º turno", "_PP": "Variação entre turnos (p.p.)", "_DELTA": "Variação entre turnos (eleitores/votos)", "_REL": "Crescimento relativo entre turnos (%)"}
        measure = st.selectbox("Medida e denominador", list(measures), index=2, key="evolution_measure", format_func=lambda x: measures[x])
    table = service.territorial(filters.year, territory, level, codes).copy()
    field = metric + measure
    valid = table[table[field].notna()]
    unit = "p.p." if measure == "_PP" else "%" if measure == "_REL" or "TAXA" in measure else "eleitores/votos"
    if level == "uf" or len(table) <= 800:
        plot(figures.territorial_map(service.data, table, field, level, unit), "evolution_map", f"Mapa de {LABELS[metric].lower()} · {measures[measure]}. A tabela abaixo oferece os mesmos valores e localidades em texto.")
        if level == "municipio":
            missing = table.codigo_ibge.isna() | table.codigo_ibge.eq("")
            st.caption(f"Malha IBGE disponível no projeto. {int(missing.sum())} localidades sem código IBGE permanecem na tabela; limites ausentes não são inventados.")
    else:
        st.info("Selecione uma UF para desenhar o mapa municipal com boa legibilidade. O ranking e o CSV abaixo incluem todos os municípios do recorte.")
    ascending = st.radio("Ordenação do ranking", ["Maior aumento / maior valor", "Maior redução / menor valor"], horizontal=True, key="evolution_order").startswith("Maior redução")
    ordered = valid.sort_values([field, "Localidade"], ascending=[ascending, True])
    shown = ordered[["Localidade", metric + "_1", metric + "_2", metric + "_TAXA_1", metric + "_TAXA_2", metric + "_DELTA", metric + "_PP", metric + "_REL"]].rename(columns={
        metric + "_1": "1º turno", metric + "_2": "2º turno", metric + "_TAXA_1": "% 1º turno", metric + "_TAXA_2": "% 2º turno", metric + "_DELTA": "Diferença absoluta", metric + "_PP": "Diferença (p.p.)", metric + "_REL": "Variação relativa (%)"})
    st.caption("Maiores reduções são as diferenças mais negativas. Crescimento relativo usa a quantidade inicial; taxa zero inicial não recebe crescimento inventado.")
    show_table(shown.head(20))
    if len(valid):
        q = valid[field].quantile([.1, .5, .9])
        st.caption(f"Dispersão entre {len(valid)} localidades: P10 {decimal(q.loc[.1])}; mediana {decimal(q.loc[.5])}; P90 {decimal(q.loc[.9])} {unit}. Quantis não ponderados de localidades; não são a taxa do território.")
    for name, value in {"Indicador": LABELS[metric], "Medida de ordenação": measures[measure], "Ano": filters.year, "Território": service.data.scope(filters), "Natureza": "CÁLCULO ESTATÍSTICO", "Fonte": "TSE · totalizacao.parquet + votos.parquet / votos_divulgacao.parquet", "Atualização": service.snapshot(filters.year, filters.turn, territory, codes)["updated"], "Definição": FORMULAS}.items():
        shown[name] = value
    st.download_button("Exportar ranking completo · CSV", csv_bytes(shown), "lampiadim_ranking_territorial.csv", "text/csv", key="evolution_ranking_csv")
    return shown.iloc[:20, :8], f"20 primeiras localidades · {LABELS[metric]} · {measures[measure]} · {'crescente' if ascending else 'decrescente'}"


def render(data, filters):
    service = evolution_for(engine_for(data))
    territory = selected_territory(data, filters)
    codes = tuple(data.geography(filters).CD_MUNICIPIO)
    compare_enabled = filters.turn == 2 or st.checkbox("Comparar explicitamente os dois turnos", value=True, key="evolution_compare")
    try:
        snapshot = service.snapshot(filters.year, filters.turn, territory, codes)
        comparison = service.compare(filters.year, territory, codes) if compare_enabled and {1, 2}.issubset(data.turns(filters.year)) else None
    except DataUnavailable as exc:
        st.warning(f"Análise indisponível: {exc}. Nenhum indicador desta seção foi apresentado.")
        return
    with st.container(key="evolution"):
        st.caption(f"{data.scope(filters)} · {filters.year} · Fonte: {snapshot['source']} · atualização: {snapshot['updated']}")
        st.caption("DADO OFICIAL: contagens. CÁLCULO ESTATÍSTICO: taxas, diferenças e decomposição. " + DEMOGRAPHIC_NOTE)
        if comparison and filters.turn == 2:
            st.header("COMO LULA EVOLUIU DO PRIMEIRO PARA O SEGUNDO TURNO?")
            st.markdown("### 1. Ponto de partida")
            stage(comparison["first"])
            st.markdown("### 2. O que mudou entre os turnos?")
            row = comparison["table"].set_index("Chave").loc["LULA"]
            for col, label, value in zip(st.columns(3), ["Variação absoluta", "Crescimento relativo", "Participação nos válidos"],
                                         [integer(row["Variação absoluta"]) + " votos", percent(row["Variação relativa (%)"]), decimal(row['Variação (p.p.)'], True) + " p.p."]):
                col.metric(label, value)
            st.caption("Absoluta = votos finais − iniciais. Relativa = diferença / votos iniciais. Participação = diferença entre as taxas sobre os válidos de cada turno.")
            plot(figures.waterfall(comparison), "evolution_waterfall", "Cascata: votação inicial + efeito participação + efeito tamanho da base = votação final. Parcelas matemáticas; não são fluxos observados de eleitores.")
            parts = comparison["decomposition"]
            if parts:
                st.caption(f"Efeito participação: {decimal(parts['participacao'])} votos. Efeito base válida: {decimal(parts['base'])} votos. Soma: {integer(parts['delta'])} votos.")
            st.markdown("### 3. Resultado final")
            stage(comparison["second"])
            st.write(summary(comparison))
            st.info(WARNING)
        st.subheader("COMPARECIMENTO E ABSTENÇÃO ELEITORAL")
        t = snapshot["totals"]
        for col, key in zip(st.columns(3), ["ELEITORADO_APTO", "COMPARECIMENTO", "ABSTENCAO"]):
            col.metric(LABELS[key], integer(t[key]), percent(snapshot["rates"].get(key)) if key != "ELEITORADO_APTO" else "Totalização oficial", delta_color="off")
        if comparison:
            r = comparison["table"].set_index("Chave").loc["ABSTENCAO"]
            st.write(f"Diferença entre turnos: {integer(r['Variação absoluta'])} abstencionistas; {decimal(r['Variação (p.p.)'], True)} pontos percentuais na taxa.")
            plot(figures.composition(comparison, "turnout"), "evolution_turnout", "Comparecimento e abstenção sobre o eleitorado apto publicado em cada turno. Redução de abstenção não comprova transferência para qualquer candidato.")
        st.subheader("VOTOS BRANCOS E NULOS")
        for col, key in zip(st.columns(3), ["VOTOS_BRANCOS", "VOTOS_NULOS", "BRANCOS_NULOS"]):
            col.metric(LABELS[key], integer(t[key]), percent(snapshot["rates"][key]) + " do comparecimento", delta_color="off")
        if "NULOS_TECNICOS" in t:
            st.caption(f"Nulos totais: nulos de urna {integer(t['NULOS_URNA'])} + nulos técnicos {integer(t['NULOS_TECNICOS'])}. Anulados: {integer(t['ANULADOS'])}; anulados sub judice: {integer(t['ANULADOS_SUB_JUDICE'])}. Subcategorias técnicas não são somadas novamente.")
        st.caption("Brancos e nulos são votos de quem compareceu. Não equivalem à abstenção, nem sua redução identifica o destino de votos.")
        if not comparison:
            return
        plot(figures.composition(comparison, "ballots"), "evolution_ballots", "Barras de composição do comparecimento: válidos, brancos e nulos; cada turno usa seu próprio total de comparecimento.")
        st.subheader("PARA ONDE MUDOU A DISTRIBUIÇÃO DO ELEITORADO?")
        if comparison["first"]["closed"] and comparison["second"]["closed"]:
            plot(figures.composition(comparison), "evolution_composition", "Cada barra usa o eleitorado apto do próprio turno. Mostra composição agregada; não trajetórias individuais.")
            category = st.selectbox("Examinar uma categoria", COMPOSITION, format_func=lambda x: LABELS[x], key="evolution_category")
            a, b = comparison["first"]["totals"], comparison["second"]["totals"]
            p, q = ratio(a[category], a["ELEITORADO_APTO"]), ratio(b[category], b["ELEITORADO_APTO"])
            delta_pp = decimal(q-p, True) + " p.p." if p is not None and q is not None else "taxa indisponível"
            st.write(f"{LABELS[category]}: {integer(a[category])} ({percent(p)} dos aptos) → {integer(b[category])} ({percent(q)}). Variação: {integer(b[category] - a[category])}; {delta_pp} dos aptos.")
        else:
            st.info("As categorias não esgotam o eleitorado apto: composição fechada indisponível neste recorte.")
        with st.expander("Indicadores, denominadores e variações · tabela acessível"):
            show_table(comparison["table"].drop(columns="Chave"))
        with st.expander("Distribuição territorial e rankings", expanded=False):
            ranking, ranking_title = geographic(service, filters, territory, codes)
        lab(comparison)
        with st.expander("Metodologia e fontes"):
            st.write(FORMULAS)
            st.code("Efeito participação = (p2 − p1) × (V1 + V2) / 2\nEfeito base = (V2 − V1) × (p1 + p2) / 2", language=None)
            st.write("A decomposição usa frações exatas e arredonda somente a exibição. As chaves oficiais de município e número de candidatura controlam as junções. Dados ausentes, duplicados, divergentes ou parciais bloqueiam a análise.")
            st.write(WARNING + " " + DEMOGRAPHIC_NOTE)
            for note in snapshot["notes"]:
                st.write(note)
            st.markdown("[Resultados e nota sobre transferência temporária · TSE](https://dadosabertos.tse.jus.br/dataset/resultados-2026)")
            st.caption(f"Versão da totalização (SHA256): {snapshot['version']}")
            refs = service.references
            if refs:
                st.write("Conciliação: municípios → UFs → Brasil com exterior; votos nominais → válidos; comparecimento → válidos + brancos + nulos.")
                national_rows = []
                for turn, ref in refs["referencias"].items():
                    official = ref["brasil_com_exterior"]
                    national_rows.append({"Turno": turn, "Aptos publicados": official["ELEITORADO_APTO"], "Aptos efetivos (nota TSE)": refs["ajuste_tte"]["eleitorado_efetivo_nacional"], "Comparecimento": official["COMPARECIMENTO"], "Abstenção": official["ABSTENCAO"], "Aptos em seções não instaladas": official["APTOS_SECOES_NAO_INSTALADAS"]})
                st.write("Referência nacional com exterior (abrangência diferente do painel):")
                show_table(pd.DataFrame(national_rows))
                st.caption("Seções não instaladas explicam por que comparecimento + abstenção não esgotam os aptos nacionais publicados. A nota dos 39 registros não fornece sua distribuição territorial; nenhuma correção local foi aplicada.")
        st.download_button("Exportar indicadores e fontes · CSV", csv_bytes(export_table(comparison)), "lampiadim_evolucao_eleitoral.csv", "text/csv", key="evolution_csv")
        signature = (filters, snapshot["version"], ranking_title)
        if st.button("Preparar infográfico PNG e análise PDF", key="evolution_export_prepare"):
            st.session_state.evolution_exports = (signature, export_png(comparison), export_pdf(comparison, ranking, ranking_title))
        cached = st.session_state.get("evolution_exports")
        if cached and cached[0] == signature:
            left, right = st.columns(2)
            left.download_button("Baixar infográfico · PNG", cached[1], "lampiadim_evolucao.png", "image/png", key="evolution_png")
            right.download_button("Baixar análise · PDF", cached[2], "lampiadim_evolucao.pdf", "application/pdf", key="evolution_pdf")
