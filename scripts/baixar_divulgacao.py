"""Baixa os resultados oficiais de divulgação do TSE (arquivos -u.json) por município, UF e Brasil.

Fonte: https://resultados.tse.jus.br/oficial/ele2026/<eleicao>/ — portal oficial de
divulgação. Usado enquanto o TSE não publica o arquivo consolidado
votacao_candidato_munzona com o turno correspondente.

    .\\.venv\\Scripts\\python.exe scripts\\baixar_divulgacao.py 6258 6257

Retoma downloads interrompidos e respeita um limite de requisições por segundo.
Os arquivos brutos ficam em dados/brutos/divulgacao_2026/<eleicao>/ (fora do Git).
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dados/brutos/divulgacao_2026"
BASE = "https://resultados.tse.jus.br/oficial/ele2026"
RPS = float(os.environ.get("RPS", "5"))
WORKERS = int(os.environ.get("WORKERS", "8"))
AGENT = "Lampiadim/1.0 (pesquisa academica; https://github.com/Nunex1/Modelo-Eleitoral)"


class Limiter:
    def __init__(self, rps):
        self.interval, self.lock, self.next = 1 / rps, threading.Lock(), time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            self.next = max(self.next + self.interval, now)
            delay = self.next - now
        if delay > 0:
            time.sleep(delay)


LIMIT = Limiter(RPS)


def fetch(url):
    for attempt in range(6):
        LIMIT.wait()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            time.sleep(min(60, 2 ** attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"falhou após novas tentativas: {url}")


def save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    json.loads(content)  # só grava JSON válido
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def download(election):
    folder = OUT / election
    config_path = folder / f"mun-e00{election}-cm.json"
    save(config_path, fetch(f"{BASE}/{election}/config/mun-e00{election}-cm.json"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    targets = [("br", f"br/br-c0001-e00{election}-u.json")]
    for state in config["abr"]:
        uf = state["cd"].lower()
        targets.append((uf, f"{uf}/{uf}-c0001-e00{election}-u.json"))
        targets += [(uf, f"{uf}/{uf}{m['cd']}-c0001-e00{election}-u.json") for m in state["mu"]]
    missing = [(uf, rel) for uf, rel in targets if not (folder / rel).exists()]
    print(f"eleição {election}: {len(targets)} arquivos, {len(missing)} a baixar", flush=True)
    failures = []

    def task(item):
        uf, rel = item
        try:
            save(folder / rel, fetch(f"{BASE}/{election}/dados/{rel}"))
        except Exception as exc:  # registra e segue; a próxima execução retoma
            failures.append({"arquivo": rel, "erro": repr(exc)[:200]})

    with cf.ThreadPoolExecutor(WORKERS) as pool:
        for i, _ in enumerate(pool.map(task, missing), 1):
            if i % 500 == 0:
                print(f"eleição {election}: {i}/{len(missing)}", flush=True)
    files = sorted(p for p in folder.rglob("*.json"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(path.read_bytes())
    summary = {"eleicao": election, "fonte": f"{BASE}/{election}/", "arquivos": len(files), "esperados": len(targets) + 1,
               "falhas": failures, "sha256_conjunto": digest.hexdigest(), "baixado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "config_dg": config.get("dg"), "config_hg": config.get("hg")}
    (folder / "_coleta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "falhas"} | {"falhas": len(failures)}, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    for code in sys.argv[1:] or ["6258", "6257"]:
        download(code)
