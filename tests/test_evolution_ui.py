from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "Lampiadim_MVP/app.py"


def test_infographic_filters_and_exports():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.button(key="nav_dashboard").click().run()
    app.button(key="round_2").click().run()
    assert not app.exception
    assert any("COMO LULA EVOLUIU" in x.value for x in app.header)
    app.selectbox(key="region").set_value("SUDESTE").run()
    assert set(app.selectbox(key="uf").options) == {"Todos os estados do recorte", "ES · Espírito Santo", "MG · Minas Gerais", "RJ · Rio de Janeiro", "SP · São Paulo"}
    app.selectbox(key="uf").set_value("SP").run()
    app.selectbox(key="municipality").set_value("61310").run()
    assert not app.exception
    assert any(x.value == "48.130" for x in app.metric)
    assert any("eleitorado apto difere" in x.value for x in app.info)
    app.button(key="header_chat").click().run()
    app.chat_input[0].set_value("Qual a abstenção?").run()
    conversation = app.session_state.conversations[app.session_state.active_conversation]
    assert "34.080" in conversation["messages"][-1]["answer"].text
    old_count = len(conversation["messages"])
    app.button(key="nav_dashboard").click().run()
    app.selectbox(key="municipality").set_value("62910").run()
    app.button(key="header_chat").click().run()
    app.chat_input[0].set_value("Qual a abstenção?").run()
    conversation = app.session_state.conversations[app.session_state.active_conversation]
    assert len(conversation["messages"]) == old_count + 2
    assert "Campinas/SP" in conversation["messages"][-1]["answer"].text
    app.button(key="nav_dashboard").click().run()
    app.selectbox(key="municipality").set_value("61310").run()
    app.selectbox(key="evolution_metric").set_value("VOTOS_NULOS").run()
    app.button(key="evolution_export_prepare").click().run()
    assert not app.exception
    signature, png, pdf = app.session_state.evolution_exports
    assert signature[0].municipality == "61310" and png.startswith(b"\x89PNG") and pdf.startswith(b"%PDF")
    app.button(key="round_1").click().run()
    app.checkbox(key="evolution_compare").uncheck().run()
    assert not app.exception
    assert any("COMPARECIMENTO E ABSTENÇÃO" in x.value for x in app.subheader)


def test_lab_only_after_explicit_hypothesis_and_conserves_real_margins():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.button(key="nav_dashboard").click().run()
    app.selectbox(key="uf").set_value("SP").run()
    app.selectbox(key="municipality").set_value("61026").run()
    app.button(key="round_2").click().run()
    assert not app.exception
    assert not app.checkbox(key="flow_constant").value
    app.checkbox(key="flow_constant").check().run()
    assert not app.exception
    assert any("OS FLUXOS NÃO REPRESENTAM" in x.value for x in app.warning)
    assert any("não intervalos de confiança" in x.value for x in app.caption)
    app.slider(key="flow_lula").set_value(100).run()
    assert not app.exception
    app.button(key="flow_pdf_prepare").click().run()
    assert not app.exception
