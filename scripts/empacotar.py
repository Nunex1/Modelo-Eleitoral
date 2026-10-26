"""Pacote local portátil, sem ambiente virtual, credenciais ou ZIPs brutos."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "dados/tratados/lampiadim/manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["outputs"].items():
        with (ROOT / "dados/tratados/lampiadim" / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != expected:
                raise ValueError("Derivado alterado: " + name)
    files = {ROOT / p for p in ["README.md", "Dockerfile", ".dockerignore", "requirements-dev.txt", "iniciar_lampiadim.ps1", ".streamlit/config.toml", "analise_eleitoral.ipynb", "image.png"]}
    for folder, patterns in {"Lampiadim_MVP": ["*.py", "*.md", "*.txt", "*.csv", "*.xlsx"], "Lampiadim_MVP/lampiadim": ["*.py"], "Lampiadim_MVP/assets": ["*.svg", "*.css", "*.geojson", "*.png", "*.webp", "*.md", "*.json"], "dados/tratados/lampiadim": ["*.parquet", "*.csv", "*.json"], "scripts": ["*.py"], "tests": ["*.py"], "tests/avaliacao": ["*.json"], "docs": ["*.md"], "resultados": ["*.md", "*.xml", "*.png"]}.items():
        for pattern in patterns:
            files.update((ROOT / folder).glob(pattern))
    output = ROOT / "resultados/Lampiadim-local.zip"
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(files):
            if path.is_file():
                z.write(path, path.relative_to(ROOT))
    with ZipFile(output) as z:
        assert z.testzip() is None
        assert "dados/tratados/lampiadim/perfil.parquet" in z.namelist()
        for name in ["lampiadim_mascote.png", "lampiadim_mascote.webp", "lampiadim_avatar.svg", "lampiadim_favicon.svg", "politica_privacidade.md", "identidade.json"]:
            assert f"Lampiadim_MVP/assets/{name}" in z.namelist(), f"Identidade incompleta no pacote: {name}"
        assert not any(".env" in n or "secrets.toml" in n or ".venv" in n for n in z.namelist())
    print(f"Pacote verificado: {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
