"""Gráficos locais, sem tiles, CDN ou associação entre cor e partido."""
from functools import lru_cache
import json
import math

import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from .data import ASSETS, STATE_CODES, integer, percent

BLUE = "#002776"
TEAL = "#247A73"


def base(fig, height):
    fig.update_layout(height=height, margin=dict(l=8, r=25, t=15, b=25), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Arial, sans-serif", size=12, color="#334155"), separators=",.", hoverlabel=dict(bgcolor="#171717", font_color="white"))
    fig.update_xaxes(showgrid=True, gridcolor="#ebe8e0", zeroline=False)
    fig.update_yaxes(showgrid=False, zeroline=False, automargin=True)
    return fig


def candidates(table, mode="Percentual"):
    frame = table.iloc[::-1]
    field = "PERCENTUAL" if mode == "Percentual" else "VOTOS"
    labels = [percent(x) if mode == "Percentual" else integer(x) for x in frame[field]]
    fig = go.Figure(go.Bar(x=frame[field].tolist(), y=frame.NM_URNA_CANDIDATO.tolist(), orientation="h", marker_color=BLUE, text=labels, textposition="outside", cliponaxis=False, customdata=[[integer(r.VOTOS), percent(r.PERCENTUAL), r.SG_PARTIDO] for r in frame.itertuples()], hovertemplate="<b>%{y}</b> · %{customdata[2]}<br>%{customdata[0]} votos<br>%{customdata[1]} dos válidos<extra></extra>"))
    maximum = float(frame[field].max()) if len(frame) else 1
    base(fig, max(300, len(frame) * 31 + 55))
    fig.update_xaxes(range=[0, max(1, maximum) * 1.22], ticksuffix="%" if mode == "Percentual" else "", title=None)
    fig.update_layout(bargap=.36)
    return fig


def demographic(table, dimension):
    frame = table if dimension == "idade" else table.iloc[::-1]
    if dimension == "idade":
        fig = go.Figure(go.Bar(x=frame.CATEGORIA.tolist(), y=frame.QT_ELEITORES.tolist(), marker_color=TEAL, customdata=[percent(x) for x in frame.PERCENTUAL], hovertemplate="%{x}<br>%{y:,.0f} eleitores · %{customdata}<extra></extra>"))
        base(fig, 340)
        fig.update_yaxes(rangemode="tozero", showgrid=True, gridcolor="#ebe8e0", tickformat=",.0f")
        fig.update_xaxes(tickangle=-45, showgrid=False)
    else:
        fig = go.Figure(go.Bar(x=frame.PERCENTUAL.tolist(), y=[str(x).capitalize() for x in frame.CATEGORIA], orientation="h", marker_color=TEAL, text=[percent(x) for x in frame.PERCENTUAL], textposition="outside", cliponaxis=False, customdata=[integer(x) for x in frame.QT_ELEITORES], hovertemplate="%{y}<br>%{customdata} eleitores<br>%{x:.2f}% do perfil selecionado<extra></extra>"))
        base(fig, max(230, len(frame) * 37 + 50))
        fig.update_xaxes(range=[0, 115], ticksuffix="%")
    return fig


LIGHT_BLUE = "#7C9CCF"
# Simulações usam tom de alerta e hachura: nunca a cor dos dados oficiais.
SIM_FILL, SIM_LINE = "#F5B544", "#9A3412"
SIMULATION_WARNING = "SIMULAÇÃO HIPOTÉTICA. NÃO REPRESENTA VOTOS REAIS POR PERFIL DEMOGRÁFICO."


def turns(frame):
    """Percentual dos válidos por candidatura em cada turno (denominadores próprios de cada turno)."""
    fig = go.Figure()
    order = frame.groupby("NM_URNA_CANDIDATO").PERCENTUAL.max().sort_values().index.tolist()
    for turn, color in [(1, LIGHT_BLUE), (2, BLUE)]:
        rows = frame[frame.NR_TURNO.eq(turn)].set_index("NM_URNA_CANDIDATO").reindex(order)
        fig.add_trace(go.Bar(name=f"{turn}º turno", x=rows.PERCENTUAL.tolist(), y=order, orientation="h", marker_color=color,
                             text=[percent(x) if x == x else "" for x in rows.PERCENTUAL], textposition="outside", cliponaxis=False,
                             customdata=[[integer(v) if v == v else "—"] for v in rows.VOTOS], hovertemplate="<b>%{y}</b> · " + f"{turn}º turno" + "<br>%{customdata[0]} votos<br>%{x:.2f}% dos válidos<extra></extra>"))
    base(fig, max(260, len(order) * 46 + 70))
    fig.update_layout(barmode="group", bargap=.25, legend=dict(orientation="h", y=1.08, x=0))
    fig.update_xaxes(range=[0, 115], ticksuffix="%")
    return fig


def hours(table):
    """Votos computados por faixa horária (horário de Brasília). Nenhuma informação de candidatura."""
    labels = [f"{int(h):02d}h–{int(h) + 1:02d}h" for h in table.HORA]
    fig = go.Figure(go.Bar(x=labels, y=table.VOTOS.tolist(), marker_color=TEAL, hovertemplate="%{x}<br>%{y:,.0f} votos computados<extra></extra>"))
    base(fig, 320)
    fig.update_yaxes(rangemode="tozero", showgrid=True, gridcolor="#ebe8e0", tickformat=",.0f")
    fig.update_xaxes(showgrid=False, tickangle=-35)
    return fig


def closings(sections):
    """Encerramento das urnas em blocos de 15 minutos, com a linha do critério de urna estendida (17h45)."""
    minutes = sections.ENCERRAMENTO.map(lambda t: int(t[:2]) * 60 + int(t[3:5]))
    buckets = (minutes // 15 * 15).clip(lower=16 * 60 + 30, upper=20 * 60)
    counts = buckets.value_counts().sort_index()
    labels = [f"{m // 60:02d}h{m % 60:02d}" for m in counts.index]
    colors = [BLUE if m < 17 * 60 + 45 else "#B45309" for m in counts.index]
    fig = go.Figure(go.Bar(x=labels, y=counts.tolist(), marker_color=colors, hovertemplate="Encerramento a partir de %{x}<br>%{y:,.0f} urnas<extra></extra>"))
    base(fig, 300)
    if counts.max() > 50 * max(1, counts.min()):
        # Escala logarítmica com marcas só em potências de 10: poucas urnas tardias continuam visíveis.
        ticks = [10 ** k for k in range(0, int(math.log10(counts.max())) + 2)]
        fig.update_yaxes(type="log", tickvals=ticks, ticktext=[integer(t) for t in ticks], title="Urnas (escala log)", showgrid=True, gridcolor="#ebe8e0")
    else:
        fig.update_yaxes(showgrid=True, gridcolor="#ebe8e0", title="Urnas")
    fig.update_xaxes(showgrid=False, tickangle=-35)
    if "17h45" in labels:
        fig.add_vline(x=labels.index("17h45") - .5, line_dash="dash", line_color="#9A3412", annotation_text="17h45 · urna estendida", annotation_position="top right")
    return fig


def simulation(runs, dimensions):
    """Votos SIMULADOS por categoria: aviso permanente no topo, marca d'água e hachura de alerta."""
    fig = go.Figure()
    patterns = ["/", "x"]
    for i, run in enumerate(runs):
        rows = run["rows"]
        labels = rows[list(dimensions)].astype(str).agg(" · ".join, axis=1).map(lambda s: s if any(c.isdigit() for c in s) else s.capitalize())
        fig.add_trace(go.Bar(name=f"{run['display']} · votos simulados", x=labels.tolist(), y=rows.VOTOS_SIMULADOS.tolist(),
                             marker=dict(color=SIM_FILL, line=dict(color=SIM_LINE, width=1.2), pattern=dict(shape=patterns[i % 2], fgcolor=SIM_LINE, solidity=.18)),
                             customdata=[[integer(v), percent(100 * p)] for v, p in zip(rows.VOTOS_SIMULADOS, rows.PARTICIPACAO)],
                             hovertemplate="<b>%{x}</b><br>SIMULAÇÃO HIPOTÉTICA<br>%{customdata[0]} votos simulados<br>%{customdata[1]} do eleitorado<extra></extra>"))
    base(fig, 450)
    # Três linhas curtas: o aviso cabe inteiro também em telas de celular (anotações não quebram linha sozinhas).
    warning = SIMULATION_WARNING.replace(". ", ".<br>", 1).replace(" POR PERFIL", "<br>POR PERFIL")
    fig.update_layout(barmode="group", margin=dict(l=8, r=25, t=130, b=25), legend=dict(orientation="h", y=-0.22, x=0),
                      annotations=[dict(text="<b>" + warning + "</b>", xref="paper", yref="paper", x=0.5, y=1.04, yanchor="bottom", showarrow=False, align="center",
                                        font=dict(size=13, color="#7C2D12"), bgcolor="#FEF3C7", bordercolor="#B45309", borderwidth=2, borderpad=8),
                                   dict(text="HIPOTÉTICO", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, textangle=-18,
                                        font=dict(size=72, color="rgba(180,83,9,0.13)"))])
    fig.update_yaxes(rangemode="tozero", showgrid=True, gridcolor="#ebe8e0", tickformat=",.0f", title="Votos simulados")
    fig.update_xaxes(showgrid=False, tickangle=-30)
    return fig


@lru_cache(maxsize=2)
def geometry(level):
    filename = "brasil_uf.geojson" if level == "uf" else "brasil_municipios.geojson"
    return json.loads((ASSETS / filename).read_text(encoding="utf-8"))["features"]


def project(ring):
    return [p[0] for p in ring], [math.degrees(math.log(math.tan(math.pi / 4 + math.radians(p[1]) / 2))) for p in ring]


def territorial(data, filters, level="uf", state="SP"):
    """Polígonos IBGE em Mercator; pontos centrais permitem seleção por teclado/lista alternativa."""
    values = data.map_values(filters, level)
    towns = data.towns.set_index("codigo_ibge")
    reverse = {v: k for k, v in STATE_CODES.items()}
    features = geometry(level)
    if level != "uf":
        features = [f for f in features if str(f["properties"]["codarea"]).startswith(STATE_CODES[state])]
    maximum = 100 if filters.candidate else (max((v for v in values.values() if v == v), default=1) or 1)
    fig = go.Figure()
    centers = []
    for feature in features:
        code = str(feature["properties"]["codarea"])
        if level == "uf":
            key = reverse.get(code)
            name = data.states.get(key, code)
        elif code in towns.index:
            town = towns.loc[code]
            key, name = town.CD_MUNICIPIO, town.NM_MUNICIPIO.title()
        else:
            key, name = "", f"IBGE {code} · sem correspondência TSE"
        value = values.get(key)
        valid = value is not None and value == value
        scale = value / maximum if valid else 0
        color = sample_colorscale([[0, "#dcece8"], [.5, "#5b9b92"], [1, "#165b56"]], [scale])[0] if valid else "#e9e7e0"
        label = percent(value) if filters.candidate and valid else (integer(value) + " votos" if valid else "Fora do recorte / sem dados")
        polygons = feature["geometry"]["coordinates"] if feature["geometry"]["type"] == "MultiPolygon" else [feature["geometry"]["coordinates"]]
        largest = max(polygons, key=lambda p: len(p[0]))[0]
        for polygon in polygons:
            x, y = project(polygon[0])
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", fill="toself", fillcolor=color, line=dict(width=.7, color="#ffffff"), hoveron="fills", text=f"{name}<br>{label}", hovertemplate="%{text}<extra></extra>", showlegend=False, customdata=[[key]] * len(x)))
        x, y = project(largest)
        if key:
            centers.append((sum(x)/len(x), sum(y)/len(y), key, name, label))
    fig.add_trace(go.Scatter(x=[p[0] for p in centers], y=[p[1] for p in centers], mode="markers+text" if level == "uf" else "markers", text=[p[2] for p in centers], textfont=dict(size=11, color="#142d38"), textposition="middle center", marker=dict(size=24 if level == "uf" else 9, color="rgba(0,0,0,0.01)"), customdata=[[p[2], p[3], p[4]] for p in centers], hovertemplate="<b>%{customdata[1]}</b><br>%{customdata[2]}<extra></extra>", showlegend=False))
    base(fig, 440)
    fig.update_layout(clickmode="event+select", dragmode="pan", margin=dict(l=0, r=0, t=0, b=0), hovermode="closest")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    return fig
