"""Otimiza o recorte aprovado e enquadra o rosto em SVG sem redesenhar pixels.

O fundo foi removido com image_gen. Este script apenas reduz resolução para a
web e cria janelas SVG sobre a mesma imagem, mantendo o mestre PNG intacto.
"""
from pathlib import Path
import base64
import hashlib
import io
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "Lampiadim_MVP/assets"


def main():
    source = ASSETS / "lampiadim_mascote.png"
    with Image.open(source) as image:
        if image.mode != "RGBA" or image.getchannel("A").getextrema() != (0, 255):
            raise ValueError("O mestre deve conter transparência real.")
        original_size = image.size
        image.thumbnail((480, 600), Image.Resampling.LANCZOS)
        image.save(ASSETS / "lampiadim_mascote.webp", lossless=True, method=6)
        width, height = image.size
    for name, size in [("lampiadim_avatar.svg", 128), ("lampiadim_favicon.svg", 64)]:
        with Image.open(source) as small:
            small.thumbnail((400, 500) if size == 128 else (224, 280), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            small.save(buffer, format="WEBP", lossless=True, method=6)
            embedded_width, embedded_height = small.size
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        # Janela normalizada: rosto, óculos e parte do chapéu oficial.
        x, y, edge = embedded_width * .39, embedded_height * .075, embedded_width * .265
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 100 100" role="img" aria-label="Rosto do Lampiadim">
<defs><clipPath id="circle"><circle cx="50" cy="50" r="50"/></clipPath></defs>
<g clip-path="url(#circle)"><circle cx="50" cy="50" r="50" fill="#F7F4EC"/>
<svg viewBox="{x} {y} {edge} {edge}" width="100" height="100"><image href="data:image/webp;base64,{encoded}" width="{embedded_width}" height="{embedded_height}"/></svg></g></svg>'''
        (ASSETS / name).write_text(svg, encoding="utf-8")
    manifest = {"original": "image.png", "original_format": "JPEG RGB (apesar da extensão .png)", "original_sha256": hashlib.sha256((ROOT / "image.png").read_bytes()).hexdigest(), "master": source.name, "master_size": original_size, "master_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "web_size": [width, height], "method": "Fundo removido por image_gen; redução WebP sem perdas; avatar e favicon são janelas SVG sobre a mesma imagem, sem redesenho ou filtro de cor."}
    (ASSETS / "identidade.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
