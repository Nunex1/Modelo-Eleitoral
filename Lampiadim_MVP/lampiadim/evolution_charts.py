"""Figuras sobre a mesma tabela validada usada pelo assistente e exportações."""
import plotly.graph_objects as go

from .charts import base, geometry, project
from .data import STATE_CODES, integer, percent
from .evolution import COMPOSITION, LABELS, ratio
from .transfers import FLOW_WARNING

COLORS = {"LULA": "#285b92", "FLAVIO": "#a96534", "OUTROS": "#6b6592", "ABSTENCAO": "#989b9f",
          "VOTOS_BRANCOS": "#d5d1c6", "VOTOS_NULOS": "#626871", "COMPARECIMENTO": "#285b92", "VOTOS_VALIDOS": "#285b92"}


def waterfall(comparison):
    d = comparison["decomposition"]
    if d is None:
        return None
    values = [comparison["first"]["totals"]["LULA"], float(d["participacao"]), float(d["base"]), comparison["second"]["totals"]["LULA"]]
    fig = go.Figure(go.Waterfall(orientation="h", measure=["absolute", "relative", "relative", "total"],
                               y=["1º turno", "Efeito participação", "Efeito base válida", "2º turno"],
                               x=[*values[:3], 0], text=[integer(values[0]), "", "", integer(values[3])],
                               textposition="inside", connector={"line": {"color": "#c4c1b9"}},
                               increasing={"marker": {"color": "#527fa3"}}, decreasing={"marker": {"color": "#8b8173"}},
                               totals={"marker": {"color": COLORS["LULA"]}},
                               customdata=values, hovertemplate="%{y}<br>%{customdata:,.2f} votos<br>Componente matemático, sem interpretação causal<extra></extra>"))
    base(fig, 330)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="Votos")
    return fig


def composition(comparison, mode="electorate"):
    snapshots = [comparison["first"], comparison["second"]]
    keys, denominator = (COMPOSITION, "ELEITORADO_APTO") if mode == "electorate" else \
                        (["COMPARECIMENTO", "ABSTENCAO"], "ELEITORADO_APTO") if mode == "turnout" else \
                        (["VOTOS_VALIDOS", "VOTOS_BRANCOS", "VOTOS_NULOS"], "COMPARECIMENTO")
    fig = go.Figure()
    for key in keys:
        values = [s["totals"][key] for s in snapshots]
        rates = [ratio(v, s["totals"][denominator]) for s, v in zip(snapshots, values)]
        fig.add_trace(go.Bar(name=LABELS[key], orientation="h", y=["1º turno", "2º turno"], x=rates,
                             marker={"color": COLORS[key], "line": {"color": "#faf8f2", "width": 1}},
                             customdata=[[integer(v), percent(p), key] for v, p in zip(values, rates)],
                             text=[percent(p) if p is not None and p > 7 else "" for p in rates], textposition="inside",
                             hovertemplate=LABELS[key] + " · %{y}<br>%{customdata[0]} eleitores/votos<br>%{customdata[1]}<extra></extra>"))
    base(fig, 290)
    fig.update_layout(barmode="stack", legend={"orientation": "h", "y": -.25, "x": 0}, margin={"b": 100})
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 100], title="% do eleitorado apto" if denominator == "ELEITORADO_APTO" else "% do comparecimento")
    return fig


def candidate_bars(snapshot):
    keys = ["LULA", "FLAVIO", "OUTROS"] if snapshot["turn"] == 1 else ["LULA", "FLAVIO"]
    fig = go.Figure(go.Bar(x=[snapshot["rates"][k] for k in keys], y=[LABELS[k] for k in keys], orientation="h",
                           marker_color=[COLORS[k] for k in keys], text=[percent(snapshot["rates"][k]) for k in keys],
                           customdata=[integer(snapshot["totals"][k]) for k in keys], textposition="auto",
                           hovertemplate="%{y}<br>%{customdata} votos<br>%{x:.2f}% dos válidos<extra></extra>"))
    base(fig, 230)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 100], title="% dos votos válidos")
    return fig


def territorial_map(data, table, field, level, unit):
    """Malhas locais já utilizadas no projeto. Sem mapa-base remoto."""
    values = dict(zip(table.SG_UF if level == "uf" else table.CD_MUNICIPIO, table[field]))
    names = dict(zip(table.SG_UF if level == "uf" else table.CD_MUNICIPIO, table.Localidade))
    reverse = {v: k for k, v in STATE_CODES.items()}
    ibge = dict(zip(data.towns.codigo_ibge, data.towns.CD_MUNICIPIO))
    fig, xs, ys, texts, colors = go.Figure(), [], [], [], []
    from plotly.colors import sample_colorscale
    finite = [v for v in values.values() if v == v]
    minimum, maximum = min(finite, default=0), max(finite, default=1)
    for feature in geometry("uf" if level == "uf" else "municipality"):
        code = str(feature["properties"]["codarea"])
        key = reverse.get(code) if level == "uf" else ibge.get(code)
        if key not in values:
            continue
        value = values[key]
        valid = value == value
        color = sample_colorscale([[0, "#e4e8ed"], [1, "#285b92"]], [(value - minimum) / (maximum - minimum) if valid and maximum > minimum else .5])[0] if valid else "#ddd"
        label = names[key] + "<br>" + (f"{value:,.2f} {unit}" if valid else "Indisponível")
        polygons = feature["geometry"]["coordinates"] if feature["geometry"]["type"] == "MultiPolygon" else [feature["geometry"]["coordinates"]]
        for polygon in polygons:
            x, y = project(polygon[0])
            fig.add_trace(go.Scatter(x=x, y=y, fill="toself", mode="lines", fillcolor=color, line={"color": "white", "width": .4},
                                     text=label, hoveron="fills", hovertemplate="%{text}<extra></extra>", showlegend=False))
        x, y = project(max(polygons, key=lambda p: len(p[0]))[0])
        xs.append(sum(x) / len(x)); ys.append(sum(y) / len(y)); texts.append(label); colors.append(value)
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", text=texts, hovertemplate="%{text}<extra></extra>", showlegend=False,
                             marker={"size": 4, "color": colors, "colorscale": [[0, "#e4e8ed"], [1, "#285b92"]], "showscale": True, "colorbar": {"title": unit}}))
    base(fig, 430)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    return fig


def sankey(result):
    matrix = result["matrix"]
    m, n = matrix.shape
    fig = go.Figure(go.Sankey(node={"label": [f"{x} · 1º" for x in matrix.index] + [f"{x} · 2º" for x in matrix.columns],
                                   "color": [COLORS[k] for k in COMPOSITION] + [COLORS[k] for k in COMPOSITION if k != "OUTROS"], "pad": 22},
                             link={"source": [i for i in range(m) for j in range(n)],
                                   "target": [m + j for i in range(m) for j in range(n)], "value": matrix.to_numpy().ravel(),
                                   "hovertemplate": "Fluxo hipotético: %{value:,.2f}<extra></extra>"}))
    base(fig, 580)
    fig.update_layout(title={"text": "SIMULAÇÃO HIPOTÉTICA", "font": {"size": 15}}, margin={"t": 65, "b": 75},
                      annotations=[{"text": "Fluxos hipotéticos; não representam migração individual real.", "xref": "paper", "yref": "paper", "x": .5, "y": -.12, "showarrow": False}])
    return fig
