"""Lampiadim · evolução do MVP Streamlit, preservando dados e notebooks."""
from dataclasses import replace
from html import escape
import json
from pathlib import Path
import sys
import uuid

import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from lampiadim.data import ASSETS, DATA, DIMENSIONS, ElectoralData, Filters, csv_bytes, integer, percent
from lampiadim.assistant import answer_question, provider_enabled
from lampiadim import charts
from lampiadim.branding import asset_uri, brand_html

st.set_page_config(page_title="Lampiadim · Inteligência eleitoral", page_icon=str(ASSETS / "lampiadim_favicon.svg"), layout="wide", initial_sidebar_state="auto")
st.html("<style>" + (ASSETS / "styles.css").read_text(encoding="utf-8") + "</style>")
AVATAR = asset_uri("lampiadim_avatar.svg")
MASCOT = asset_uri("lampiadim_mascote.webp")
PAGES = {"conversa": "Pergunte ao Lampiadim", "dashboard": "Dashboard eleitoral", "privacidade": "Política de Privacidade", "sobre": "Sobre o Lampiadim"}
PENDING_TURN = "Os dados do segundo turno ainda estão pendentes de integração à plataforma Lampiadim."


@st.cache_resource(show_spinner="Organizando os dados eleitorais…")
def load_data(version):
    return ElectoralData()


try:
    data = load_data(((DATA / "manifest.json").stat().st_mtime_ns, (BASE / "lampiadim/data.py").stat().st_mtime_ns))
except (FileNotFoundError, ValueError, KeyError) as exc:
    st.error(str(exc))
    st.code(r".\.venv\Scripts\python.exe scripts\preparar_dados.py", language="powershell")
    st.stop()

DEFAULTS = {"year": data.years[-1], "turn": data.turns(data.years[-1])[0], "uf": "", "municipality": "", "ddd": None, "candidate": "", **{k: "" for k in DIMENSIONS}}
for key, value in DEFAULTS.items():
    # Atribuição explícita desvincula o valor da limpeza de widgets ausentes
    # quando uma outra página é exibida (chat, privacidade ou segundo turno).
    st.session_state[key] = st.session_state.get(key, st.session_state.get("filter_memory", {}).get(key, value))
route = st.query_params.get("pagina", "conversa")
if st.session_state.get("route") != route:
    st.session_state.page = PAGES.get(route, PAGES["conversa"])
    st.session_state.route = route
st.session_state.setdefault("selected_turn", 1)
st.session_state.setdefault("conversations", {})


def navigate(page):
    slug = next(key for key, value in PAGES.items() if value == page)
    st.session_state.page = page
    st.session_state.route = slug
    st.query_params["pagina"] = slug
    st.session_state.update(st.session_state.get("filter_memory", {}))


def choose_turn(turn):
    st.session_state.selected_turn = turn
    if st.session_state.page not in (PAGES["conversa"], PAGES["dashboard"]):
        navigate(PAGES["conversa"])


def reset_filters():
    st.session_state.update(DEFAULTS)
    st.session_state.pop("pending_map", None)
    st.session_state.map_mode = "Brasil"
    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1


def select_state():
    st.session_state.update(municipality="", ddd=None)


def select_ddd():
    st.session_state.municipality = ""


def current_filters():
    return Filters(**{k: st.session_state[k] for k in DEFAULTS})


def new_conversation(open_chat=True):
    key = uuid.uuid4().hex
    st.session_state.conversations[key] = {"title": "Nova conversa", "messages": [], "context": current_filters()}
    st.session_state.active_conversation = key
    st.session_state.selected_turn = 1
    if open_chat:
        navigate(PAGES["conversa"])


def open_conversation(key):
    st.session_state.active_conversation = key
    st.session_state.selected_turn = 1
    navigate(PAGES["conversa"])


def clear_conversations():
    st.session_state.conversations = {}
    new_conversation(open_chat=False)
    st.session_state.history_cleared = True


def safe_select(label, choices, key, **kwargs):
    if st.session_state.get(key) not in choices:
        st.session_state[key] = choices[0]
    return st.selectbox(label, choices, key=key, **kwargs)


def display_table(frame, height="auto"):
    formats = {column: percent for column in frame.columns if column.startswith("%")}
    formats.update({column: integer for column in ["Votos", "Eleitores", "Total", "Votos válidos", "Eleitores cadastrados"] if column in frame})
    formats.update({column: lambda value: str(int(value)) for column in ["DDD", "Ano", "Turno", "Número"] if column in frame})
    st.dataframe(frame.style.format(formats, na_rep="Indisponível"), hide_index=True, width="stretch", height=height)


def shell():
    if "active_conversation" not in st.session_state:
        new_conversation(open_chat=False)
    with st.sidebar:
        st.html(brand_html(sidebar=True))
        st.html('<div class="sidebar-label">Eleições <span>2026</span></div>')
        available = 1 in data.turns(DEFAULTS["year"]) and data.query(Filters(year=DEFAULTS["year"], turn=1))["votes"] > 0
        with st.container(key="election-cards"):
            st.button("1º turno · Disponível" if available else "1º turno · Indisponível", key="round_1", icon=":material/check_circle:", width="stretch", type="primary" if st.session_state.selected_turn == 1 else "secondary", on_click=choose_turn, args=(1,), disabled=not available)
            st.button("2º turno · Pendente", key="round_2", icon=":material/schedule:", width="stretch", type="primary" if st.session_state.selected_turn == 2 else "secondary", on_click=choose_turn, args=(2,))
        st.html('<div class="sidebar-label">Conversas</div>')
        st.button("Nova conversa", icon=":material/add:", key="new_chat", on_click=new_conversation, width="stretch")
        with st.expander("Histórico desta sessão", expanded=True):
            with st.container(key="session-history", height=210 if len(st.session_state.conversations) > 4 else "content", border=False):
                for key, conversation in reversed(list(st.session_state.conversations.items())):
                    st.button(conversation["title"], key=f"history_{key}", icon=":material/chat_bubble_outline:", width="stretch", type="tertiary", on_click=open_conversation, args=(key,), help="Abrir esta conversa e seu contexto de consulta")
            st.caption("As conversas ficam nesta sessão.")
        st.html('<div class="sidebar-label">Informações</div>')
        with st.container(key="side-navigation"):
            for slug, icon in [("dashboard", "bar_chart"), ("privacidade", "shield"), ("sobre", "info")]:
                page = PAGES[slug]
                st.button(page, icon=f":material/{icon}:", key=f"nav_{slug}", width="stretch", type="primary" if st.session_state.page == page else "tertiary", on_click=navigate, args=(page,))
        st.html('<div class="sidebar-bottom"><span class="status-dot"></span> Dados públicos, perguntas abertas.</div>')
        st.caption("IA externa habilitada" if provider_enabled() else "Consultas locais em português")
    with st.container(key="header"):
        brand, navigation = st.columns([1.35, 1], vertical_alignment="center")
        with brand:
            st.html(brand_html())
        with navigation, st.container(key="navigation"):
            left, right = st.columns(2)
            left.button("Conversar", icon=":material/chat_bubble_outline:", key="header_chat", type="primary" if st.session_state.page == PAGES["conversa"] else "tertiary", width="stretch", on_click=navigate, args=(PAGES["conversa"],))
            right.button("Dashboard", icon=":material/bar_chart:", key="header_dashboard", type="primary" if st.session_state.page == PAGES["dashboard"] else "tertiary", width="stretch", on_click=navigate, args=(PAGES["dashboard"],))


def filters_panel():
    with st.container(key="filters"):
        cols = st.columns([.7, .9, 1.45, .65, 1.7])
        with cols[0]:
            safe_select("Ano da eleição", data.years, "year", on_change=lambda: st.session_state.update(turn=data.turns(st.session_state.year)[0]))
        with cols[1]:
            safe_select("Turno", data.turns(st.session_state.year), "turn", format_func=lambda x: f"{x}º turno", help="Somente turnos presentes nos arquivos locais.")
        with cols[2]:
            safe_select("Estado", [""] + sorted(data.states), "uf", format_func=lambda x: "Todo o Brasil" if not x else f"{x} · {data.states[x]}", on_change=select_state)
        towns = data.towns if not st.session_state.uf else data.towns[data.towns.SG_UF.eq(st.session_state.uf)]
        with cols[3]:
            safe_select("DDD", [None] + sorted(towns.DDD.dropna().astype(int).unique().tolist()), "ddd", format_func=lambda x: "Todos" if x is None else str(x), on_change=select_ddd, placeholder="Todos", help="Somente associações validadas contra a Anatel. Consulte a cobertura em Fontes e método.")
        if st.session_state.ddd:
            towns = towns[towns.DDD.eq(st.session_state.ddd).fillna(False)]
        labels = {r.CD_MUNICIPIO: f"{r.NM_MUNICIPIO.title()} · {r.SG_UF}" for r in towns.itertuples()}
        with cols[4]:
            safe_select("Município", [""] + sorted(labels, key=lambda x: labels[x]), "municipality", format_func=lambda x: labels.get(x, "Todos os municípios"))
        more, clear = st.columns([5, 1], vertical_alignment="bottom")
        with more:
            safe_select("Candidatura à Presidência", [""] + data.candidates, "candidate", format_func=lambda x: x or "Todas as candidaturas", help="O percentual conserva o denominador de todas as candidaturas do território.")
        with clear:
            st.button("Limpar filtros", on_click=reset_filters, width="stretch")
        with st.expander("Refinar o perfil do eleitorado"):
            st.caption("Esses filtros alteram apenas os indicadores cadastrais. Os votos são agregados e não podem ser atribuídos a grupos demográficos.")
            columns = st.columns(4)
            labels_d = {"sexo": "Sexo (DS_GENERO)", "identidade": "Identidade de gênero", "idade": "Faixa etária", "escolaridade": "Escolaridade"}
            _, population, _ = data.frames(replace(current_filters(), **{k: "" for k in DIMENSIONS}))
            for column, (name, field) in zip(columns, DIMENSIONS.items()):
                with column:
                    options = sorted(population[field].dropna().unique().tolist())
                    value = safe_select(labels_d[name], [""] + options, name, format_func=lambda x: x.capitalize() if x else "Todas as categorias")
                    if value:
                        population = population[population[field].eq(value)]
    return current_filters()


def map_selection(event, level):
    points = event.selection.points if event and hasattr(event, "selection") else []
    if not points:
        return
    custom = points[-1].get("customdata", [])
    if not custom or not custom[0]:
        return
    key = str(custom[0])
    if level == "uf" and key in data.states and (st.session_state.uf != key or st.session_state.municipality or st.session_state.ddd):
        st.session_state.pending_map = {"uf": key, "municipality": "", "ddd": None}
        st.rerun()
    if level != "uf":
        town = data.towns[data.towns.CD_MUNICIPIO.eq(key)]
        if len(town) and st.session_state.municipality != key:
            st.session_state.pending_map = {"uf": town.iloc[0].SG_UF, "municipality": key, "ddd": None}
            st.rerun()


def dashboard():
    if "pending_map" in st.session_state:
        st.session_state.update(st.session_state.pop("pending_map"))
    st.html('<div class="hero"><div class="eyebrow">Territórios, pessoas e democracia</div><h1>Descubra o Brasil pelos números.</h1><p class="intro">Explore o mapa eleitoral e conheça as histórias que os dados revelam.</p></div>')
    filters = filters_panel()
    st.session_state.filter_memory = filters.__dict__.copy()
    result = data.query(filters)
    municipality_unit = "município" if result["municipalities"] == 1 else "municípios"
    st.html(f'<div class="scope"><strong>{escape(result["scope"])}</strong> &nbsp; / &nbsp; {result["period"]} &nbsp; / &nbsp; {integer(result["municipalities"])} {municipality_unit}</div>')
    if filters.ddd and data.manifest["sources"]["geography"]["unavailable"]:
        st.caption("Recorte por DDD: cobertura parcial. Municípios sem associação Anatel validada são excluídos; veja Fontes e método.")
    if not result["municipalities"]:
        st.info("Nenhum município corresponde a este recorte. Limpe ou ajuste os filtros.")
        return
    with st.container(key="metrics"):
        cards = st.columns(4)
    cards[0].metric("Votos nominais válidos", integer(result["votes"]), "Soma das candidaturas no território", delta_color="off", help=f"{result['period']} · {result['scope']}. Não inclui brancos/nulos.")
    cards[1].metric("Eleitorado cadastrado", integer(result["registered"]), "Cadastro territorial · 2026", delta_color="off", help="Cadastro de 14/07/2026; não equivale a aptos da totalização nem a comparecimento.")
    cards[2].metric("Eleitores no perfil", integer(result["selected_profile"]), "Após os filtros demográficos", delta_color="off", help="Soma de QT_ELEITORES na interseção das quatro dimensões demográficas.")
    cards[3].metric("Diferença entre os 2 mais votados", integer(result["difference"]) if result["difference"] is not None else "—", (f"{result['difference_pp']:.2f}".replace('.', ',') + " p.p. dos válidos" if result["difference_pp"] is not None else "Sem comparação disponível"), delta_color="off", help="Primeira menos segunda votação do território, independentemente do filtro de candidatura.")
    overview, demographics, table_tab, source_tab = st.tabs(["Panorama eleitoral", "Perfil do eleitorado", "Tabela analítica", "Fontes e método"])
    with overview:
        with st.container(key="overview-charts"):
            left, right = st.columns([1.12, 1], gap="large")
        with left:
            with st.container(key="map"):
                st.subheader("Explore o mapa eleitoral")
                mode = st.segmented_control("Abrangência do mapa", ["Brasil", "São Paulo", "Estado selecionado"], default="Brasil", key="map_mode", label_visibility="collapsed")
                level = "uf" if mode == "Brasil" else "municipality"
                state = "SP" if mode == "São Paulo" else (filters.uf or "SP")
                signature = repr((filters, mode, state))
                if st.session_state.get("map_signature") != signature:
                    st.session_state.map_signature = signature
                    st.session_state.map_revision = st.session_state.get("map_revision", 0) + 1
                map_filters = filters
                if level != "uf" and not filters.uf:
                    map_filters = replace(filters, uf=state)
                if mode == "São Paulo" and filters.uf and filters.uf != "SP":
                    st.info("O recorte está em outro estado. Selecione São Paulo no filtro Estado para explorar seus municípios.")
                caption = "Total de votos válidos" if not filters.candidate else f"% de votos válidos · {filters.candidate}"
                st.caption(f"{caption} · {result['period']}" + (f" · {data.states[state]}" if level != "uf" else ""))
                try:
                    figure = charts.territorial(data, map_filters, level, state)
                    event = st.plotly_chart(figure, key=f"map_{level}_{state}_{st.session_state.map_revision}", on_select="rerun", selection_mode="points", width="stretch", config={"displayModeBar": True, "displaylogo": False, "scrollZoom": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "toImage"]})
                    map_selection(event, level)
                except (FileNotFoundError, ValueError) as exc:
                    st.warning(f"Malha indisponível: {exc}")
                upper = "100%" if filters.candidate else integer(max(data.map_values(map_filters, level).values(), default=0))
                st.html(f'<div class="legend">0 <span class="legend-bar"></span> {upper} &nbsp; · &nbsp; Cinza: fora do recorte / sem dados</div>')
                st.caption("Selecione pelo ponto no mapa ou pelos filtros acima. Amplie para explorar municípios. Malhas simplificadas do IBGE.")
                if level != "uf":
                    available_codes = {str(f["properties"]["codarea"]) for f in charts.geometry("municipality")}
                    eligible = data.geography(map_filters)
                    missing = eligible[~eligible.codigo_ibge.isin(available_codes)]
                    if len(missing):
                        st.caption(f"{len(missing)} município(s) do recorte não possuem geometria associada; continuam nos totais e na tabela.")
        with right:
            with st.container(key="results"):
                st.subheader("Comparativo entre candidaturas")
                chart_mode = st.segmented_control("Unidade da votação", ["Percentual", "Votos"], default="Percentual", label_visibility="collapsed")
                st.caption(f"Denominador: {integer(result['votes'])} votos nominais válidos do recorte.")
                if result["candidates"].empty:
                    st.info("Não há votos para a candidatura neste recorte.")
                else:
                    st.plotly_chart(charts.candidates(result["candidates"], chart_mode or "Percentual"), width="stretch", config={"displayModeBar": False})
                st.caption("A mesma cor representa todas as candidaturas. Ordenação por quantidade de votos.")
        with st.container(key="history"):
            st.subheader("Evolução histórica")
            st.info("Somente a eleição de 2026 está disponível. A comparação entre eleições será habilitada quando houver outro ano com dados equivalentes.")
        st.html('<div class="note">Comparecimento, abstenção e eleitores aptos da totalização: indisponíveis nos arquivos atuais. O cadastro não substitui esses indicadores.</div>')
    with demographics:
        st.subheader("Entenda o perfil do eleitorado")
        st.caption(f"{result['scope']} · cadastro 2026 · denominador: {integer(result['selected_profile'])} eleitores após os filtros demográficos.")
        if any(getattr(filters, name) for name in DIMENSIONS):
            st.info("Recorte cadastral: " + "; ".join(f"{name}: {getattr(filters, name)}" for name in DIMENSIONS if getattr(filters, name)))
        if not result["selected_profile"]:
            st.info("Não há eleitores na interseção dos filtros demográficos.")
        else:
            for pair in [("sexo", "idade"), ("escolaridade", "identidade")]:
                with st.container(key=f"profile-row-{pair[0]}"):
                    profile_columns = st.columns(2, gap="large")
                for column, name in zip(profile_columns, pair):
                    with column:
                        with st.container(border=True):
                            titles = {"sexo": "Sexo no cadastro eleitoral", "idade": "Distribuição por faixa etária", "escolaridade": "Escolaridade do eleitorado", "identidade": "Identidade de gênero registrada"}
                            st.subheader(titles[name])
                            st.plotly_chart(charts.demographic(result["demographics"][name], name), width="stretch", config={"displayModeBar": False})
                            with st.expander("Consultar valores e exportar"):
                                shown = result["demographics"][name].rename(columns={"CATEGORIA": "Categoria", "QT_ELEITORES": "Eleitores", "PERCENTUAL": "% do perfil"})
                                display_table(shown)
                                st.download_button("Baixar CSV do perfil", csv_bytes(shown), f"lampiadim_{name}_{filters.year}.csv", "text/csv", key=f"download_{name}")
            st.caption("Categorias originais preservadas. ‘Não informado’ e ‘Prefere não informar’ permanecem distintas. Sexo cadastral corresponde a DS_GENERO na fonte.")
    with table_tab:
        with st.container(key="detail"):
            st.subheader("Dos números ao detalhe")
            st.caption("Resultados municipais por candidatura. Território, ano, turno e candidatura se aplicam a esta tabela. Filtros demográficos se aplicam somente à aba de perfil.")
            search_col, sort_col = st.columns([2, 1])
            search = search_col.text_input("Buscar município, candidatura ou partido", placeholder="Ex.: Americana, Lula, PL…")
            order = sort_col.selectbox("Ordenar tabela", ["Mais votos", "Menos votos", "Município (A–Z)", "Maior percentual"])
            table = data.analytical_table(filters)
            if search:
                from lampiadim.data import normalize
                term = normalize(search)
                mask = table[["Município", "Candidatura", "Partido"]].astype(str).agg(" ".join, axis=1).map(normalize).str.contains(term, regex=False)
                table = table[mask]
            field, asc = {"Mais votos": ("Votos", False), "Menos votos": ("Votos", True), "Município (A–Z)": ("Município", True), "Maior percentual": ("% válidos", False)}[order]
            table = table.sort_values([field, "Código TSE", "Candidatura"], ascending=[asc, True, True])
            st.caption(f"{integer(len(table))} {'registro' if len(table) == 1 else 'registros'} · percentuais calculados sobre os votos válidos de cada município.")
            page_count = max(1, (len(table) + 99) // 100)
            if st.session_state.get("table_page", 1) > page_count:
                st.session_state.table_page = 1
            page = st.number_input("Página da tabela", min_value=1, max_value=page_count, value=1, step=1, key="table_page")
            st.caption(f"Página {page} de {page_count} · até 100 registros por página. A exportação inclui todos os registros da busca e dos filtros; a ordenação acima se aplica ao conjunto completo.")
            display_table(table.iloc[(page-1)*100:page*100], height=470)
            st.download_button("Exportar tabela filtrada · CSV", csv_bytes(table), f"lampiadim_votos_{filters.year}_turno{filters.turn}.csv", "text/csv", type="primary")
            st.download_button("Exportar contexto e fontes · JSON", json.dumps({"filters": filters.__dict__, "search": search, "sort": order, "scope": result["scope"], "vote_denominator": "soma dos votos nominais válidos de cada município, antes de selecionar candidatura", "rows": len(table), "sources": data.manifest}, ensure_ascii=False, indent=2), "lampiadim_contexto.json", "application/json")
    with source_tab:
        st.subheader("Dados que você pode conferir")
        st.write("A aplicação consulta os arquivos do TSE presentes neste projeto. A preparação reconcilia integralmente os votos do primeiro turno e o perfil cadastral com os CSVs do notebook. As fontes originais permanecem preservadas.")
        sources = data.manifest["sources"]
        st.dataframe(pd.DataFrame([{"Base": "Votação presidencial", "Geração na origem": ", ".join(sources["votes"]["generated_dates"]), "Abrangência": "Brasil sem exterior", "Total": sources["votes"]["total"]}, {"Base": "Perfil cadastral", "Geração na origem": ", ".join(sources["profile"]["generated_dates"]), "Abrangência": "27 UFs, sem exterior", "Total": sources["profile"]["total"]}]), hide_index=True, width="stretch")
        st.markdown("- **Votos válidos:** soma de `QT_VOTOS_NOMINAIS_VALIDOS` para Presidente, por ano e turno.\n- **Percentual por candidatura:** votos da candidatura ÷ votos nominais válidos de todas as candidaturas no mesmo território.\n- **Perfil:** soma de `QT_ELEITORES` na interseção das categorias selecionadas; percentuais usam esse total.\n- **Diferença:** votos da primeira menos os da segunda candidatura; pontos percentuais usam o mesmo denominador territorial.\n- **Comparações:** diferenças descritivas não demonstram relações causais. Não existe identificação individual de voto.")
        geo = sources["geography"]
        st.subheader("Correspondência territorial e DDD")
        st.write(f"{integer(geo['validated_ddd'])} de {integer(geo['municipalities'])} municípios com DDD validado. Associação por código IBGE à tabela Anatel; vínculo TSE–IBGE por nome normalizado e UF, exigindo chave única. A cobertura por DDD é parcial.")
        if geo["unavailable"]:
            with st.expander(f"Ver {len(geo['unavailable'])} municípios sem DDD validado"):
                missing = pd.DataFrame(geo["unavailable"])
                st.dataframe(missing, hide_index=True, width="stretch")
                st.download_button("Baixar pendências de correspondência", csv_bytes(missing), "lampiadim_pendencias_ddd.csv", "text/csv")
        st.caption("A malha municipal simplificada contém 5.570 geometrias. Municípios sem correspondência cartográfica permanecem nos totais. DDD representa área telefônica, não limite eleitoral.")
        st.markdown(f"[Portal de dados abertos do TSE](https://dadosabertos.tse.jus.br/) · [Tabela de códigos nacionais da Anatel]({geo['anatel_url']}) · [Malhas geográficas do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3)")
        with st.expander("Linhagem técnica e hashes SHA-256"):
            st.json(data.manifest, expanded=False)
        st.subheader("O que ainda não pode ser medido")
        st.write("Aptos da totalização, votantes, comparecimento, abstenção, votos brancos e nulos exigem a base de detalhe da apuração. Evolução histórica exige outros anos. Só são oferecidos anos e turnos encontrados nos arquivos.")


def render_answer(answer):
    st.markdown(answer.text)
    for title, frame in answer.tables:
        st.caption(title)
        display_table(frame)
    if answer.sources:
        with st.expander("Consultar fontes e denominadores"):
            for source in answer.sources:
                st.caption(source)
            st.caption("Percentual eleitoral: votos da candidatura / votos válidos do território. Perfil: eleitores da categoria / eleitores no recorte cadastral. Não são percentuais de comparecimento.")
    st.caption(answer.mode)


def chat():
    conversation = st.session_state.conversations[st.session_state.active_conversation]
    if not conversation["messages"]:
        conversation["context"] = current_filters()
    with st.container(key="chat-page"):
        prompt = None
        if not conversation["messages"]:
            st.html(f'<div class="chat-welcome"><img class="welcome-mascot" src="{MASCOT}" alt="Lampiadim: gênio brasileiro azul, com chapéu de cangaço, óculos e vestimentas de couro"><div class="eyebrow">Inteligência brasileira. Curiosidade sem limites.</div><h1>Os dados contam uma história.<br><span>Vamos entendê-la?</span></h1><p>Pergunte ao Lampiadim sobre votos, municípios e o perfil do eleitorado brasileiro.</p></div>')
            with st.container(key="chat-suggestions"):
                suggestions = [("Compare os votos em Americana/SP", "bar_chart"), ("Qual o perfil por sexo no DDD 19?", "groups"), ("Como se distribui a idade em Campinas/SP?", "donut_small"), ("Compare Americana e Campinas", "location_on")]
                for i in range(0, len(suggestions), 2):
                    for col, (suggestion, icon) in zip(st.columns(2), suggestions[i:i+2]):
                        if col.button(suggestion, icon=f":material/{icon}:", key=f"suggestion_{i}_{icon}", width="stretch", wrap=True):
                            prompt = suggestion
        st.caption(f"Contexto da conversa: {data.scope(conversation['context'])} · {conversation['context'].year} · {conversation['context'].turn}º turno")
        with st.container(key="conversation"):
            for message in conversation["messages"]:
                with st.chat_message(message["role"], avatar=AVATAR if message["role"] == "assistant" else None):
                    if message["role"] == "user":
                        st.write(message["text"])
                    else:
                        render_answer(message["answer"])
        if conversation["messages"]:
            transcript = "\n\n".join(("Você: " + m["text"]) if m["role"] == "user" else "Lampiadim: " + m["answer"].text for m in conversation["messages"])
            st.download_button("Baixar conversa", transcript, "conversa_lampiadim.txt", "text/plain")
    # Fora do container: o Streamlit fixa o compositor na base da área principal.
    typed = st.chat_input("Pergunte ao Lampiadim…", key="question", max_chars=2000)
    prompt = typed or prompt
    if prompt:
        if not conversation["messages"]:
            conversation["title"] = prompt[:48] + ("…" if len(prompt) > 48 else "")
        conversation["messages"].append({"role": "user", "text": prompt})
        with st.container(key="processing"):
            with st.chat_message("user"):
                st.write(prompt)
            with st.chat_message("assistant", avatar=AVATAR):
                with st.spinner("O Lampiadim está consultando os dados…", show_time=True):
                    answer = answer_question(prompt, data, conversation["context"])
                    conversation["messages"].append({"role": "assistant", "answer": answer})
                    if not answer.clarification:
                        conversation["context"] = answer.filters
        st.rerun()


def pending_turn():
    with st.container(key="pending-turn"):
        st.html(f'<div class="pending-illustration"><img src="{AVATAR}" alt="Lampiadim" width="86" height="86"></div><div class="eyebrow">Eleições 2026 · 2º turno</div><h1>Uma nova história está por vir.</h1>')
        st.info(PENDING_TURN, icon=":material/schedule:")
        st.write("Enquanto isso, explore os resultados e o perfil do eleitorado disponíveis no primeiro turno.")
        st.button("Explorar o primeiro turno", icon=":material/arrow_forward:", type="primary", on_click=choose_turn, args=(1,))


def privacy():
    with st.container(key="privacy-page"):
        st.html('<div class="eyebrow">Transparência desde o começo</div><h1>Política de Privacidade</h1><p class="intro">Como suas perguntas e os dados da plataforma são tratados.</p>')
        st.warning("Versão local · identificação do controlador, canal de contato, bases legais e condições de retenção precisam ser preenchidos antes da publicação.", icon=":material/edit_note:")
        st.caption("Modo atual: integração com OpenAI habilitada para interpretar perguntas." if provider_enabled() else "Modo atual: consultas locais. A integração com IA externa está desativada.")
        st.markdown((ASSETS / "politica_privacidade.md").read_text(encoding="utf-8"))
        with st.container(border=True):
            st.subheader("Seu histórico nesta sessão")
            st.write("Você pode remover as conversas acessíveis desta sessão. Isso não exclui arquivos já baixados ou registros de fornecedores.")
            st.button("Apagar conversas da sessão", icon=":material/delete_outline:", key="clear_history", on_click=clear_conversations)
            if st.session_state.pop("history_cleared", False):
                st.success("As conversas foram removidas desta sessão. Uma conversa vazia está disponível.")


def about():
    with st.container(key="about-page"):
        st.html(f'<div class="about-intro"><img src="{MASCOT}" alt="Mascote oficial do Lampiadim"><div><div class="eyebrow">Feito para explorar o Brasil</div><h1>Prazer, Lampiadim.</h1><p class="intro">Um jeito mais próximo de entender os dados eleitorais.</p></div></div>')
        st.write("O Lampiadim reúne consultas em português, mapas e tabelas para explorar resultados e conhecer o perfil cadastral do eleitorado brasileiro. Nosso personagem combina a imaginação de um gênio com a identidade do cangaço.")
        st.subheader("Dados que você pode conferir")
        st.write("As respostas são calculadas a partir dos arquivos locais do TSE e apresentam seu contexto e suas fontes. IBGE e Anatel apoiam a correspondência territorial. Cores dos gráficos não representam preferência por candidaturas.")
        st.subheader("O que está disponível")
        st.write("Resultados presidenciais do primeiro turno de 2026, perfil cadastral, municípios, UFs e recortes por DDD com cobertura validada. Segundo turno e séries históricas adicionais estão pendentes de integração. Votos agregados não revelam o voto de grupos demográficos nem de pessoas.")
        st.subheader("Como o Lampiadim responde")
        st.write("O modo local reconhece perguntas sobre os dados disponíveis. A interpretação por IA externa é opcional e depende da configuração do servidor. Em ambos os modos, os números são calculados pelo mesmo mecanismo de consulta.")
        st.caption("Projeto independente. Não é um serviço oficial do TSE, do IBGE ou da Anatel.")
        st.button("Explorar o dashboard", icon=":material/bar_chart:", on_click=navigate, args=(PAGES["dashboard"],))


shell()
if st.session_state.page == PAGES["privacidade"]:
    privacy()
elif st.session_state.page == PAGES["sobre"]:
    about()
elif st.session_state.selected_turn == 2:
    pending_turn()
elif st.session_state.page == PAGES["dashboard"]:
    dashboard()
else:
    chat()
with st.container(key="footer"):
    info, policy = st.columns([3, 1], vertical_alignment="center")
    with info:
        st.html('<footer class="footer"><strong>lampiadim.</strong><span>Dados: TSE · Territórios: IBGE / Anatel</span></footer>')
    policy.button("Política de Privacidade", key="footer_privacy", type="tertiary", on_click=navigate, args=(PAGES["privacidade"],))
