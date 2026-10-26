"""Coleta logs oficiais das urnas (TSE) e extrai a linha do tempo de cada seção.

Fonte primária: https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna/<pleito>/
(pleito 3220 = 1º turno, 3221 = 2º turno). Para cada seção: arquivo auxiliar (-aux.json),
último pacote recebido e o log (.jez, um zip com logd.dat em Latin-1, separado por tabulação).

Metodologia (a mesma documentada por apolinario/urnas-tardias, reimplementada aqui):
- usa apenas eventos da data do turno;
- "Urna pronta para receber votos" = abertura; "Procedimento de encerramento confirmado" =
  encerramento; "O voto do eleitor foi computado" = um voto computado (sem candidatura);
- horários do log são locais; o fuso de cada município é a moda de (abertura − 8h),
  pois a votação começou às 8h de Brasília em todo o país.

Os horários dos votos são guardados apenas como contagens por minuto da seção, sem
qualquer vínculo com candidaturas (o log não registra em quem o eleitor votou).

    .\\.venv\\Scripts\\python.exe scripts\\coletar_logs_urna.py 3221 --municipios sp:61310 sp:62910
    .\\.venv\\Scripts\\python.exe scripts\\coletar_logs_urna.py 3221 --amostra 150
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import random
import threading
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dados/brutos/logs_urna_2026"
BASE = "https://resultados.tse.jus.br/oficial/ele2026/arquivo-urna"
DATES = {"3220": "04/10/2026", "3221": "25/10/2026"}
AGENT = "Lampiadim/1.0 (pesquisa academica; https://github.com/Nunex1/Modelo-Eleitoral)"
RPS = float(os.environ.get("RPS", "5"))
WORKERS = int(os.environ.get("WORKERS", "8"))
EVENTS = {"Urna pronta para receber votos": "abertura", "Procedimento de encerramento confirmado": "encerramento",
          "O voto do eleitor foi computado": "voto"}


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
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            time.sleep(min(60, 2 ** attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"falhou após novas tentativas: {url}")


def config(pleito, uf):
    path = OUT / pleito / "config" / f"{uf}-p00{pleito}-cs.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        content = fetch(f"{BASE}/{pleito}/config/{uf}/{uf}-p00{pleito}-cs.json")
        json.loads(content)
        path.write_bytes(content)
    return json.loads(path.read_text(encoding="utf-8"))


def sections(pleito, uf, municipalities=None):
    data = config(pleito, uf)
    out = []
    for m in data["abr"][0]["mu"]:
        if municipalities and m["cd"] not in municipalities:
            continue
        for z in m["zon"]:
            out += [(uf, m["cd"], m["nm"], z["cd"], s["ns"]) for s in z["sec"]]
    return out


def parse_log(raw, date):
    """Eventos do dia do turno, em horário local, a partir do log compactado."""
    events = collections.defaultdict(list)
    model = None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            for line in z.read(name).decode("latin1").splitlines():
                parts = line.split("\t")
                if len(parts) < 5 or not parts[0].startswith(date):
                    continue
                kind = EVENTS.get(parts[4])
                if kind:
                    events[kind].append(parts[0][11:19])
                elif parts[4].startswith("Identificação do Modelo de Urna"):
                    model = parts[4].split(":")[-1].strip()
    votes_per_minute = collections.Counter(t[:5] for t in events["voto"])
    return {"abertura_local": sorted(events["abertura"]), "encerramento_local": sorted(events["encerramento"]),
            "votos": len(events["voto"]), "votos_por_minuto_local": dict(sorted(votes_per_minute.items())),
            "ultimo_voto_local": max(events["voto"]) if events["voto"] else None, "modelo": model}


def collect_section(pleito, uf, mun, name, zone, section):
    base = f"{BASE}/{pleito}/dados/{uf}/{mun}/{zone}/{section}"
    row = {"pleito": pleito, "uf": uf.upper(), "cd_mun": mun, "municipio": name, "zona": zone, "secao": section}
    try:
        aux = json.loads(fetch(f"{base}/p00{pleito}-{uf}-m{mun}-z{zone}-s{section}-aux.json"))
    except urllib.error.HTTPError as exc:
        return {**row, "erro": f"aux {exc.code}"}
    hashes = aux.get("hashes", [])
    if not hashes:
        return {**row, "erro": "sem pacote"}
    last = hashes[-1]
    logs = [a["nm"] for a in last.get("arq", []) if a.get("tp") == "log"]
    if not logs:
        return {**row, "erro": "sem log"}
    try:
        raw = fetch(f"{base}/{last['hash']}/{logs[0]}")
    except urllib.error.HTTPError as exc:
        return {**row, "erro": f"log {exc.code}"}
    try:
        parsed = parse_log(raw, DATES[pleito])
    except zipfile.BadZipFile:
        return {**row, "erro": "log invalido"}
    return {**row, **parsed, "pacote": last["hash"], "recebido": last.get("hr"), "log_sha256": hashlib.sha256(raw).hexdigest()}


def run(pleito, targets, label):
    path = OUT / pleito / f"{label}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not str(r.get("erro", "")).startswith("excecao"):
                done.add((r["cd_mun"], r["zona"], r["secao"]))
    missing = [t for t in targets if (t[1], t[3], t[4]) not in done]
    print(f"{pleito}/{label}: {len(targets)} seções, {len(missing)} a coletar", flush=True)
    if path.exists() and path.stat().st_size and not path.read_bytes().endswith(b"\n"):
        with path.open("a", encoding="utf-8") as out:
            out.write("\n")  # linha interrompida fica isolada e é ignorada na consolidação
    lock = threading.Lock()
    with path.open("a", encoding="utf-8") as out, cf.ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(collect_section, pleito, *t): t for t in missing}
        for i, future in enumerate(cf.as_completed(futures), 1):
            try:
                row = future.result()
            except Exception as exc:
                uf, mun, name, zone, section = futures[future]
                row = {"pleito": pleito, "uf": uf.upper(), "cd_mun": mun, "municipio": name, "zona": zone, "secao": section, "erro": f"excecao {exc!r}"[:200]}
            with lock:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            if i % 250 == 0:
                out.flush()
                print(f"{pleito}/{label}: {i}/{len(missing)}", flush=True)
    print(f"{pleito}/{label}: concluído", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pleito", choices=sorted(DATES))
    parser.add_argument("--municipios", nargs="*", default=[], help="uf:codigo_tse, ex.: sp:61310")
    parser.add_argument("--amostra", type=int, default=0, help="seções sorteadas do secoes.csv do urnas-tardias, para validação")
    parser.add_argument("--semente", type=int, default=2026)
    args = parser.parse_args()
    if args.municipios:
        by_uf = collections.defaultdict(set)
        for item in args.municipios:
            uf, code = item.lower().split(":")
            by_uf[uf].add(code)
        targets = [t for uf, codes in sorted(by_uf.items()) for t in sections(args.pleito, uf, codes)]
        run(args.pleito, targets, "municipios")
    if args.amostra:
        source = next((ROOT / "dados/brutos/urnas_tardias").glob("*/secoes.csv"))
        with source.open(encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r["uf"] != "ZZ"]
        sample = random.Random(args.semente).sample(rows, args.amostra)
        run(args.pleito, [(r["uf"].lower(), r["cd_mun"], r["municipio"], r["zona"], r["secao"]) for r in sample], f"amostra_{args.semente}")


if __name__ == "__main__":
    main()
