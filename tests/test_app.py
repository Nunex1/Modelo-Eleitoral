from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "Lampiadim_MVP/app.py"


def test_dashboard_filters_export_scope_and_reset():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.button(key="nav_dashboard").click().run()
    assert not app.exception
    assert app.metric[0].value == "118.969.906"
    app.selectbox(key="uf").set_value("SP").run()
    assert not app.exception
    assert len(app.selectbox(key="municipality").options) == 646
    app.selectbox(key="municipality").set_value("61310").run()
    assert app.metric[0].value == "136.589"
    app.selectbox(key="sexo").set_value("FEMININO").run()
    assert app.metric[2].value == "95.958" and app.metric[0].value == "136.589"
    app.selectbox(key="candidate").set_value("LULA").run()
    assert not app.exception and app.metric[0].value == "136.589"
    next(b for b in app.button if b.label == "Limpar filtros").click().run()
    assert not app.exception and app.metric[0].value == "118.969.906"
    assert app.selectbox(key="municipality").value == ""


def test_chat_history_and_return_preserves_filters():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.button(key="nav_dashboard").click().run()
    app.selectbox(key="uf").set_value("SP").run()
    app.selectbox(key="municipality").set_value("61310").run()
    app.button(key="header_chat").click().run()
    assert not app.exception
    next(b for b in app.button if b.label == "Compare os votos em Americana/SP").click().run()
    assert not app.exception
    assert len(app.chat_message) == 2
    first = app.session_state.active_conversation
    app.button(key="new_chat").click().run()
    assert len(app.chat_message) == 0 and len(app.session_state.conversations) == 2
    app.button(key=f"history_{first}").click().run()
    assert len(app.chat_message) == 2
    app.button(key="nav_dashboard").click().run()
    assert not app.exception and app.metric[0].value == "136.589"


def test_map_selection_updates_scope():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.button(key="nav_dashboard").click().run()
    app.session_state.pending_map = {"uf": "SP", "municipality": "61310", "ddd": None}
    app.run()
    assert not app.exception and app.metric[0].value == "136.589"


def test_chat_is_default_and_second_turn_updates_dashboard_and_chat(ref):
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    assert app.session_state.page == "Pergunte ao Lampiadim"
    assert len(app.chat_input) == 1 and len(app.metric) == 0
    assert app.button(key="round_1").label == "1º turno · Disponível"
    assert app.button(key="round_2").label == "2º turno · Disponível"
    app.button(key="round_2").click().run()
    assert not app.exception and len(app.chat_input) == 1
    conversation = app.session_state.conversations[app.session_state.active_conversation]
    assert conversation["state"].period == (2026, 2) and conversation["context"].turn == 2
    app.chat_input[0].set_value("Quantos votos Lula teve em Americana?").run()
    assert "2º turno" in app.session_state.conversations[app.session_state.active_conversation]["messages"][-1]["answer"].text
    app.button(key="nav_dashboard").click().run()
    national = ref.second_round("LULA") + ref.second_round("FLAVIO BOLSONARO")  # arquivos oficiais lidos diretamente
    assert not app.exception and app.metric[0].value == f"{national:,}".replace(",", ".")
    assert app.selectbox(key="turn").value == 2
    app.button(key="round_1").click().run()
    assert not app.exception and app.metric[0].value == "118.969.906"


def test_privacy_routes_session_deletion_and_about():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.chat_input[0].set_value("Compare os votos em Americana/SP").run()
    assert len(app.chat_message) == 2
    app.button(key="footer_privacy").click().run()
    assert not app.exception and app.query_params["pagina"] == "privacidade"
    assert any("Canal de privacidade: pendente" in m.value for m in app.markdown)
    app.button(key="clear_history").click().run()
    assert len(app.session_state.conversations) == 1
    assert all(not c["messages"] for c in app.session_state.conversations.values())
    app.button(key="nav_sobre").click().run()
    assert not app.exception and app.session_state.page == "Sobre o Lampiadim"
    app.button(key="header_chat").click().run()
    assert len(app.chat_message) == 0 and len(app.chat_input) == 1
    direct = AppTest.from_file(str(APP), default_timeout=60)
    direct.query_params["pagina"] = "privacidade"
    direct.run()
    assert not direct.exception and direct.session_state.page == "Política de Privacidade"


def test_delete_conversation_requires_confirmation_and_purges_state():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.chat_input[0].set_value("Compare os votos em Americana/SP").run()
    first = app.session_state.active_conversation
    assert len(app.chat_message) == 2
    app.button(key="delete_chat").click().run()
    assert any("Esta ação não poderá ser desfeita." in m.value for m in app.markdown)
    app.button(key="delete_cancel").click().run()
    assert not app.exception and len(app.chat_message) == 2 and first in app.session_state.conversations
    app.button(key="delete_chat").click().run()
    app.button(key="delete_confirm").click().run()
    assert not app.exception and first not in app.session_state.conversations
    assert len(app.chat_message) == 0
    assert all(not c["messages"] for c in app.session_state.conversations.values())
    assert not any("Americana" in b.label for b in app.button if (b.key or "").startswith("history_"))
    # Uma nova sessão (atualizar a página) começa sem histórico.
    fresh = AppTest.from_file(str(APP), default_timeout=60).run()
    assert len(fresh.chat_message) == 0 and all(not c["messages"] for c in fresh.session_state.conversations.values())


def test_logo_returns_home_without_deleting_conversation():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.chat_input[0].set_value("Compare os votos em Americana/SP").run()
    first = app.session_state.active_conversation
    app.button(key="brand_home").click().run()
    assert not app.exception and len(app.chat_message) == 0 and "pagina" not in app.query_params
    assert app.session_state.conversations[first]["messages"]
    app.button(key="nav_dashboard").click().run()
    labels = [m.label for m in app.metric]
    assert labels[:4] == ["Votos nominais válidos", "Eleitorado cadastrado", "Eleitores no perfil", "Diferença entre os 2 mais votados"]
    # Totalização oficial do 1º turno presente; horários do 1º turno só cobrem dois municípios, então nenhum total "Brasil".
    assert "Comparecimento" in labels and "Urnas com registro" not in labels
    app.button(key="brand_home_sidebar").click().run()
    assert not app.exception and len(app.metric) == 0 and len(app.chat_input) == 1
    assert app.session_state.page == "Pergunte ao Lampiadim"
    app.button(key="round_2").click().run()
    app.button(key="brand_home").click().run()
    assert len(app.chat_input) == 1 and len(app.session_state.conversations) == 2
