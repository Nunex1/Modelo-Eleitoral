"""Exportações locais sem navegador, CDN ou serviço externo.

Pillow já é dependência do Streamlit. PNG e PDF compartilham a mesma prancha;
CSV contém valores sem arredondamento e metadados completos.
"""
from io import BytesIO
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

from .data import integer, percent
from .evolution import COMPOSITION, LABELS, WARNING, FORMULAS, summary
from .evolution_charts import COLORS


def font(size, bold=False):
    candidates = [Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def report_image(comparison):
    image = Image.new("RGB", (1600, 2300), "#f8f5ed")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48, 48, 1552, 2252), radius=28, fill="#fffdf8")
    y = 85

    def line(text, size=25, bold=False, color="#253e57", width=95):
        nonlocal y
        for part in textwrap.wrap(str(text), width=width, break_long_words=True):
            draw.text((90, y), part, font=font(size, bold), fill=color)
            y += size + 12
        y += 8

    a, b = comparison["first"], comparison["second"]
    line("LAMPIADIM | INTELIGÊNCIA ELEITORAL", 22, True)
    line("Como Lula evoluiu entre os turnos?", 45, True, width=55)
    line(f"{a['year']} · 1º e 2º turnos · {a['scope']}", 27)
    line("DADO OFICIAL: contagens | CÁLCULO ESTATÍSTICO: taxas e diferenças", 21, True)
    line(summary(comparison), 27, width=88)
    y += 12
    headers = ["Indicador", "1º turno", "2º turno", "Variação"]
    positions = [90, 640, 940, 1240]
    for x, label in zip(positions, headers):
        draw.text((x, y), label, font=font(24, True), fill="#285b92")
    y += 50
    for row in comparison["table"].to_dict("records"):
        draw.line((90, y - 8, 1500, y - 8), fill="#e1ded6")
        for x, value in zip(positions, [row["Métrica"], integer(row["1º turno"]), integer(row["2º turno"]), integer(row["Variação absoluta"]) ]):
            draw.text((x, y), value, font=font(25), fill="#253e57")
        y += 48
    y += 18
    d = comparison["decomposition"]
    if d:
        line("Decomposição matemática exata do crescimento de Lula", 28, True)
        number = lambda value: f"{float(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
        line(f"Efeito participação: {number(d['participacao'])} votos; efeito base: {number(d['base'])} votos.", 24)
        line("(p2 − p1) × (V1 + V2) / 2 + (V2 − V1) × (p1 + p2) / 2 = L2 − L1", 22)
        initial, final = a["totals"]["LULA"], b["totals"]["LULA"]
        intermediate = initial + float(d["participacao"])
        extent = max(initial, final, intermediate, 1)
        for label, start, end in [("1º turno", 0, initial), ("Participação", initial, intermediate), ("Base válida", intermediate, final), ("2º turno", 0, final)]:
            draw.text((90, y), label, font=font(21), fill="#253e57")
            left, right = 310 + 1180 * min(start, end) / extent, 310 + 1180 * max(start, end) / extent
            draw.rectangle((left, y + 2, max(left + 1, right), y + 23), fill="#285b92" if label.endswith("turno") else "#708fa4")
            y += 34
        y += 12
    if a["closed"] and b["closed"]:
        line("Para onde mudou a distribuição do eleitorado?", 28, True)
        for snapshot in [a, b]:
            line(f"{snapshot['turn']}º turno · aptos: {integer(snapshot['totals']['ELEITORADO_APTO'])}", 21)
            x = 90
            for key in COMPOSITION:
                width = 1400 * snapshot["totals"][key] / snapshot["totals"]["ELEITORADO_APTO"]
                draw.rectangle((x, y, x + width, y + 42), fill=COLORS[key])
                x += width
            y += 60
        line(" | ".join(LABELS[k] for k in COMPOSITION), 22)
    line(WARNING, 24, True, width=94)
    line(FORMULAS, 21, width=110)
    line("Fontes e atualização", 25, True)
    for snapshot in [a, b]:
        line(f"{snapshot['turn']}º turno · {snapshot['source']} · {snapshot['updated']}", 20, width=115)
    line("Versão (SHA256): " + a["version"], 17, width=120)
    line(" ".join(a["notes"]), 18, width=125)
    if y > 2240:
        raise ValueError("Conteúdo excedeu a prancha de exportação")
    return image


def export_png(comparison):
    out = BytesIO()
    report_image(comparison).save(out, format="PNG")
    return out.getvalue()


def export_pdf(comparison, ranking=None, ranking_title="", scenario=None):
    pages = [report_image(comparison)]
    supplements = []
    if ranking is not None:
        supplements.append((ranking_title, ranking))
    if scenario is not None:
        from .transfers import FLOW_WARNING
        supplements.append((FLOW_WARNING + "\nPremissas: " + str(scenario["assumptions"]), scenario["matrix"].reset_index().rename(columns={"index": "Origem"})))
    for title, table in supplements:
        page = Image.new("RGB", (1600, 2300), "#fffdf8")
        draw = ImageDraw.Draw(page)
        y = 80
        for part in textwrap.wrap(title, 85):
            draw.text((70, y), part, font=font(28, True), fill="#253e57"); y += 40
        for record in table.head(20).to_dict("records"):
            text = " · ".join(f"{k}: {v:.2f}" if isinstance(v, float) else f"{k}: {v}" for k, v in record.items())
            parts = textwrap.wrap(text, 115)
            if y + len(parts) * 30 + 14 > 2110:
                pages.append(page)
                page = Image.new("RGB", (1600, 2300), "#fffdf8")
                draw = ImageDraw.Draw(page)
                draw.text((70, 60), "Lampiadim · continuação da tabela da página anterior", font=font(26, True), fill="#253e57")
                y = 120
            for part in parts:
                draw.text((70, y), part, font=font(21), fill="#253e57"); y += 30
            y += 14
        if y > 2150:
            raise ValueError("Tabela excedeu a página de exportação")
        draw.text((70, 2180), "Mesmas fontes, ano e recorte da primeira página. Tabela limitada às linhas indicadas.", font=font(21), fill="#253e57")
        pages.append(page)
    out = BytesIO()
    pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:], resolution=150.0, title="Lampiadim · Evolução eleitoral",
                  subject=f"{comparison['first']['scope']} · {comparison['first']['year']} · Dados oficiais e cálculos; fluxos apenas hipotéticos")
    return out.getvalue()
