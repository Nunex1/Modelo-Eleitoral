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
