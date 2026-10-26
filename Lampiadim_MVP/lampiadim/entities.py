"""Resolução de entidades verificadas na base: candidaturas, municípios, UFs, DDD e partidos.

Nenhuma associação vale sem registro correspondente nos dados preparados. Apelidos
de cidades e capitais só são usados quando o município existe na UF indicada.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


from .data import normalize
from .language import COMMON_WORDS, PARTICLES, best_fuzzy, title_name

UF_PREPOSITION = {"AC": "do", "AL": "de", "AP": "do", "AM": "do", "BA": "da", "CE": "do", "DF": "do", "ES": "do", "GO": "de",
                  "MA": "do", "MT": "de", "MS": "de", "MG": "de", "PA": "do", "PB": "da", "PR": "do", "PE": "de", "PI": "do",
                  "RJ": "do", "RN": "do", "RS": "do", "RO": "de", "RR": "de", "SC": "de", "SP": "de", "SE": "de", "TO": "do"}
# Estados cujo nome é usado com artigo ("no Paraná"): o artigo indica o estado, não o município homônimo.
UF_WITH_ARTICLE = {uf for uf, prep in UF_PREPOSITION.items() if prep != "de"} - {"RJ"}
# Siglas que também são palavras comuns ("se", "pé", "tô"): exigem caixa alta, barra ou a palavra estado/UF.
UF_COLLIDING = {"SE", "ES", "PA", "TO", "MA", "PE", "CE", "AL", "AM", "AP", "AC", "MT", "RO", "PI"}
GENTILICS = {"PAULISTA": "SP", "PAULISTAS": "SP", "FLUMINENSE": "RJ", "FLUMINENSES": "RJ", "MINEIRO": "MG", "MINEIROS": "MG",
             "MINEIRA": "MG", "MINEIRAS": "MG", "GAUCHO": "RS", "GAUCHOS": "RS", "GAUCHA": "RS", "GAUCHAS": "RS", "BAIANO": "BA",
             "BAIANOS": "BA", "BAIANA": "BA", "BAIANAS": "BA", "PARANAENSE": "PR", "PARANAENSES": "PR", "CATARINENSE": "SC",
             "CATARINENSES": "SC", "CAPIXABAS": "ES", "GOIANO": "GO", "GOIANOS": "GO", "GOIANA": "GO", "GOIANAS": "GO",
             "PERNAMBUCANO": "PE", "PERNAMBUCANOS": "PE", "PERNAMBUCANAS": "PE", "CEARENSE": "CE", "CEARENSES": "CE",
             "PARAENSE": "PA", "PARAENSES": "PA", "AMAZONENSE": "AM", "AMAZONENSES": "AM", "MARANHENSE": "MA", "MARANHENSES": "MA",
             "PIAUIENSE": "PI", "PIAUIENSES": "PI", "POTIGUAR": "RN", "POTIGUARES": "RN", "PARAIBANO": "PB", "PARAIBANOS": "PB",
             "PARAIBANAS": "PB", "ALAGOANO": "AL", "ALAGOANOS": "AL", "ALAGOANAS": "AL", "SERGIPANO": "SE", "SERGIPANOS": "SE",
             "TOCANTINENSE": "TO", "TOCANTINENSES": "TO", "RONDONIENSE": "RO", "RONDONIENSES": "RO", "RORAIMENSE": "RR",
             "RORAIMENSES": "RR", "AMAPAENSE": "AP", "AMAPAENSES": "AP", "ACREANO": "AC", "ACREANOS": "AC", "ACRIANO": "AC",
             "ACRIANOS": "AC", "MATO GROSSENSE": "MT", "MATO GROSSENSES": "MT", "SUL MATO GROSSENSE": "MS", "SUL MATO GROSSENSES": "MS",
             "BRASILIENSE": "DF", "BRASILIENSES": "DF"}
STATE_ALIASES = {"MINAS": "MG", "RIO GRANDE": "", "DISTRITO FEDERAL": "DF"}
# Grandes regiões oficiais do IBGE (divisão por UF).
REGIONS = {"NORTE": ("Norte", ("AC", "AM", "AP", "PA", "RO", "RR", "TO")), "NORDESTE": ("Nordeste", ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE")),
           "CENTRO OESTE": ("Centro-Oeste", ("DF", "GO", "MS", "MT")), "SUDESTE": ("Sudeste", ("ES", "MG", "RJ", "SP")), "SUL": ("Sul", ("PR", "RS", "SC"))}
CAPITALS = {"AC": "RIO BRANCO", "AL": "MACEIO", "AP": "MACAPA", "AM": "MANAUS", "BA": "SALVADOR", "CE": "FORTALEZA", "DF": "BRASILIA",
            "ES": "VITORIA", "GO": "GOIANIA", "MA": "SAO LUIS", "MT": "CUIABA", "MS": "CAMPO GRANDE", "MG": "BELO HORIZONTE",
            "PA": "BELEM", "PB": "JOAO PESSOA", "PR": "CURITIBA", "PE": "RECIFE", "PI": "TERESINA", "RJ": "RIO DE JANEIRO",
            "RN": "NATAL", "RS": "PORTO ALEGRE", "RO": "PORTO VELHO", "RR": "BOA VISTA", "SC": "FLORIANOPOLIS", "SP": "SAO PAULO",
            "SE": "ARACAJU", "TO": "PALMAS"}
CITY_NICKNAMES = {"SAMPA": ("SAO PAULO", "SP"), "BH": ("BELO HORIZONTE", "MG"), "BEAGA": ("BELO HORIZONTE", "MG"),
                  "POA": ("PORTO ALEGRE", "RS"), "FLORIPA": ("FLORIANOPOLIS", "SC"), "BSB": ("BRASILIA", "DF"),
                  "SSA": ("SALVADOR", "BA"), "SJC": ("SAO JOSE DOS CAMPOS", "SP"), "SAMPAZINHA": ("SAO PAULO", "SP"),
                  "PAULISTANO": ("SAO PAULO", "SP"), "PAULISTANOS": ("SAO PAULO", "SP"), "PAULISTANA": ("SAO PAULO", "SP"),
                  "PAULISTANAS": ("SAO PAULO", "SP"), "CARIOCA": ("RIO DE JANEIRO", "RJ"), "CARIOCAS": ("RIO DE JANEIRO", "RJ"),
                  "CAPITAL PAULISTA": ("SAO PAULO", "SP"), "CAPITAL FLUMINENSE": ("RIO DE JANEIRO", "RJ"),
                  "CAPITAL CARIOCA": ("RIO DE JANEIRO", "RJ"), "CAPITAL MINEIRA": ("BELO HORIZONTE", "MG"),
                  "CAPITAL GAUCHA": ("PORTO ALEGRE", "RS"), "CAPITAL BAIANA": ("SALVADOR", "BA"),
                  "CAPITAL PARANAENSE": ("CURITIBA", "PR"), "CAPITAL CATARINENSE": ("FLORIANOPOLIS", "SC"),
                  "CAPITAL PERNAMBUCANA": ("RECIFE", "PE"), "CAPITAL CEARENSE": ("FORTALEZA", "CE"),
                  "CAPITAL FEDERAL": ("BRASILIA", "DF"), "CAPITAL DO PAIS": ("BRASILIA", "DF")}
# Pessoas públicas citadas com frequência. A lista só melhora a mensagem quando
# não há candidatura correspondente no pleito; nunca fornece dados.
NON_CANDIDATES = ["JAIR BOLSONARO", "JAIR MESSIAS BOLSONARO", "JAIR", "MICHELLE BOLSONARO", "EDUARDO BOLSONARO", "CARLOS BOLSONARO",
                  "TARCISIO", "TARCISIO DE FREITAS", "CIRO GOMES", "CIRO", "SIMONE TEBET", "TEBET", "MARINA SILVA", "FERNANDO HADDAD",
                  "HADDAD", "GERALDO ALCKMIN", "ALCKMIN", "SERGIO MORO", "JOAO DORIA", "DORIA", "GUILHERME BOULOS", "BOULOS", "DILMA",
                  "DILMA ROUSSEFF", "AECIO NEVES", "AECIO", "MICHEL TEMER", "FERNANDO HENRIQUE", "FHC", "PABLO MARCAL", "RATINHO JUNIOR",
                  "EDUARDO LEITE", "HELDER BARBALHO", "RUI COSTA", "SORAYA THRONICKE", "PADRE KELMON", "KELMON", "CABO DACIOLO",
                  "DACIOLO", "EYMAEL", "ANDRE JANONES", "JANONES", "VERA LUCIA", "LEONARDO PERICLES", "SOFIA MANZANO", "DATENA",
                  "JOSE LUIZ DATENA", "GUSTAVO LIMA", "TABATA AMARAL", "MARCAL"]
TITLES = {"ESCRITOR", "VETERINARIO", "DOUTOR", "DOUTORA", "DR", "PASTOR", "PASTORA", "PADRE", "CABO", "SARGENTO", "CORONEL",
          "PROFESSOR", "PROFESSORA", "DELEGADO", "DELEGADA", "GENERAL", "CAPITAO", "IRMAO", "IRMA"}
COMMON_SURNAMES = {"SILVA", "SANTOS", "OLIVEIRA", "SOUZA", "SOUSA", "RODRIGUES", "FERREIRA", "ALVES", "PEREIRA", "LIMA", "GOMES",
                   "COSTA", "RIBEIRO", "MARTINS", "CARVALHO", "ALMEIDA", "LOPES", "SOARES", "FERNANDES", "VIEIRA", "BARBOSA", "ROCHA",
                   "DIAS", "NASCIMENTO", "ANDRADE", "MOREIRA", "NUNES", "MARQUES", "MACHADO", "MENDES", "FREITAS", "CARDOSO", "RAMOS",
                   "GONCALVES", "SANTANA", "TEIXEIRA", "ARAUJO", "PINTO", "MELO", "JUNIOR", "NETO", "FILHO", "SOBRINHO", "CONCEICAO",
                   "JESUS", "ANTONIO", "JOSE", "JOAO", "MARIA", "ANA", "LUIZ", "LUIS", "CARLOS", "PAULO", "PEDRO", "FRANCISCO", "MARCOS"}


@dataclass(frozen=True)
class Candidate:
    key: str            # NM_URNA_CANDIDATO exatamente como na base
    number: int
    party: str
    party_name: str
    full_name: str
    display: str
    status: str
    periods: tuple


@dataclass(frozen=True)
class Territory:
    kind: str           # brasil | exterior | total | regiao | uf | municipio | ddd
    code: str = ""
    name: str = ""
    uf: str = ""

    @property
    def label(self):
        return {"brasil": "Brasil (sem exterior)", "exterior": "Exterior", "total": "Brasil e exterior", "ddd": f"DDD {self.code}",
                "regiao": f"Região {self.name}",
                "uf": f"Estado {UF_PREPOSITION.get(self.code, 'de')} {self.name}" if self.code != "DF" else "Distrito Federal",
                "municipio": f"{self.name}/{self.uf}"}[self.kind]

    @property
    def phrase(self):
        """Complemento de lugar: 'em Americana/SP', 'no estado de São Paulo'."""
        if self.kind == "uf":
            return "no Distrito Federal" if self.code == "DF" else f"no estado {UF_PREPOSITION.get(self.code, 'de')} {self.name}"
        return {"brasil": "no Brasil (sem os votos do exterior)", "exterior": "no exterior", "total": "no Brasil e no exterior",
                "ddd": f"nos municípios do DDD {self.code}", "regiao": f"na região {self.name}", "municipio": f"em {self.name}/{self.uf}"}[self.kind]

    @property
    def subject(self):
        """Sujeito de frase e se é plural: ('Americana/SP', False)."""
        if self.kind == "uf":
            return ("O Distrito Federal" if self.code == "DF" else f"O estado {UF_PREPOSITION.get(self.code, 'de')} {self.name}"), False
        return {"brasil": ("O Brasil (sem o exterior)", False), "exterior": ("O exterior", False), "total": ("Brasil e exterior", True),
                "ddd": (f"Os municípios do DDD {self.code}", True), "regiao": (f"A região {self.name}", False),
                "municipio": (f"{self.name}/{self.uf}", False)}[self.kind]


BRASIL = Territory("brasil")


@dataclass
class Mention:
    start: int
    end: int
    kind: str                       # candidato | nao_candidato | lugar | uf | partido
    values: tuple = ()              # chaves de candidatura, territórios possíveis ou siglas
    text: str = ""
    weak: bool = False              # nome de município que também é palavra comum
    fuzzy: bool = False
    qualifier: str = ""             # UF escrita logo após o município ("Americana/SP")
    extra: dict = field(default_factory=dict)


class KnowledgeBase:
    """Dicionários de entidades construídos uma vez a partir dos dados preparados."""

    def __init__(self, data):
        self.data = data
        info = data.candidate_info
        self.periods = sorted({(int(y), int(t)) for y, t in data.votes[["ANO_ELEICAO", "NR_TURNO"]].drop_duplicates().itertuples(index=False)})
        self.candidates = {}
        for key, rows in info.groupby("NM_URNA_CANDIDATO", sort=True):
            row = rows.iloc[-1]
            full = row.get("NM_CANDIDATO") if isinstance(row.get("NM_CANDIDATO"), str) else ""
            accented = {normalize(w): w for w in full.split()} if full else {}
            display = title_name(" ".join(accented.get(normalize(w), w) for w in key.split()))
            status = row.get("DS_SIT_TOT_TURNO") if isinstance(row.get("DS_SIT_TOT_TURNO"), str) else ""
            party_name = row.get("NM_PARTIDO") if isinstance(row.get("NM_PARTIDO"), str) else ""
            periods = tuple(sorted({(int(y), int(t)) for y, t in rows[["ANO_ELEICAO", "NR_TURNO"]].itertuples(index=False)}))
            self.candidates[key] = Candidate(key, int(row.NR_CANDIDATO), row.SG_PARTIDO, party_name, full, display, status, periods)
        towns = data.towns
        self.states = dict(data.states)
        self.cities = defaultdict(list)
        for row in towns.itertuples():
            self.cities[normalize(row.NM_MUNICIPIO)].append(Territory("municipio", row.CD_MUNICIPIO, title_name(row.NM_MUNICIPIO), row.SG_UF))
        self.city_names = set(self.cities)
        self.city_by_code = {t.code: t for options in self.cities.values() for t in options}
        self.state_names = {normalize(name): uf for uf, name in self.states.items()}
        self.state_names.update({k: v for k, v in STATE_ALIASES.items() if v})
        self.gentilics = {k: v for k, v in GENTILICS.items() if v in self.states}
        self.nicknames = {}
        for alias, (name, uf) in CITY_NICKNAMES.items():
            found = [t for t in self.cities.get(name, []) if t.uf == uf]
            if len(found) == 1:
                self.nicknames[alias] = found[0]
        self.capitals = {uf: next(t for t in self.cities[name] if t.uf == uf) for uf, name in CAPITALS.items() if any(t.uf == uf for t in self.cities.get(name, []))}
        self.ddds = sorted(int(x) for x in towns.DDD.dropna().unique())
        self.parties = {normalize(c.party): c.party for c in self.candidates.values()}
        self.party_names = {normalize(c.party_name): c.party for c in self.candidates.values() if c.party_name}
        self._build_aliases()
        self.max_span = max(len(k) for k in list(self.aliases) + [tuple(n.split()) for n in self.city_names] + [tuple(n.split()) for n in self.non_candidates])

    def _build_aliases(self):
        aliases = defaultdict(set)
        for c in self.candidates.values():
            sequences = [normalize(c.key).split()] + ([normalize(c.full_name).split()] if c.full_name else [])
            for seq in sequences:
                for i in range(len(seq)):
                    for j in range(i + 2, len(seq) + 1):
                        span = seq[i:j]
                        if span[0] in PARTICLES or span[-1] in PARTICLES:
                            continue
                        # Ao menos uma palavra distintiva: "da Silva" não identifica ninguém.
                        if any(w not in PARTICLES and w not in COMMON_SURNAMES and w not in TITLES for w in span):
                            aliases[tuple(span)].add(c.key)
            for word in sequences[0]:
                single_city = word in self.city_names
                if len(word) >= 3 and word not in PARTICLES | TITLES | COMMON_SURNAMES | COMMON_WORDS and not single_city and word not in self.state_names:
                    aliases[(word,)].add(c.key)
            aliases[tuple(normalize(c.key).split())].add(c.key)
        self.aliases = dict(aliases)
        self.single_aliases = {k[0]: v for k, v in aliases.items() if len(k) == 1}
        names_of = {key: set(normalize(c.key).split()) | set(normalize(c.full_name).split()) for key, c in self.candidates.items()}
        self.non_candidates = {}
        for name in NON_CANDIDATES:
            words = set(name.split())
            # Só é "não candidato" se não coincidir integralmente com uma candidatura da base.
            if not any(words <= names for names in names_of.values()):
                self.non_candidates[name] = name

    # ------------------------------------------------------------------
    def candidates_in(self, period):
        return [c for c in self.candidates.values() if period in c.periods]

    def find_candidate_text(self, text):
        """Resolve um nome livre (vindo do modelo de linguagem) para candidaturas da base."""
        words = tuple(w for w in normalize(text).split() if w not in TITLES)
        if not words:
            return set(), ""
        full = tuple(normalize(text).split())
        for key in (full, words):
            if key in self.aliases:
                return set(self.aliases[key]), ""
        if " ".join(words) in self.non_candidates:
            return set(), " ".join(words)
        hits = [set(self.aliases[(w,)]) for w in words if (w,) in self.aliases]
        if hits and all(h == hits[0] for h in hits):
            names = set(normalize(self.candidates[next(iter(hits[0]))].key).split()) | set(normalize(self.candidates[next(iter(hits[0]))].full_name).split())
            if all(w in names or w in PARTICLES for w in words):
                return hits[0], ""
            return set(), " ".join(words)
        if len(words) == 1:
            fuzzy = best_fuzzy(words[0], [k for k in self.single_aliases if len(k) >= 4], 0.8)
            if fuzzy:
                return set(self.single_aliases[fuzzy]), ""
        return set(), " ".join(words)

    def find_city(self, name, uf=""):
        options = self.cities.get(normalize(name), [])
        if name and normalize(name) in self.nicknames:
            options = [self.nicknames[normalize(name)]]
        return [t for t in options if not uf or t.uf == uf]

    def fuzzy_city(self, words):
        """Município com grafia aproximada (erro de digitação), somente se a correspondência for única."""
        text = " ".join(words)
        if len(text) < 5:
            return []
        pool = [n for n in self.city_names if n[0] == text[0] and abs(len(n) - len(text)) <= 2]
        match = best_fuzzy(text, pool, 0.86)
        return list(self.cities[match]) if match else []

    def state(self, uf):
        return Territory("uf", uf, self.states[uf], uf)

    def ddd(self, number):
        return Territory("ddd", str(number))

    # ------------------------------------------------------------------
    def scan(self, tokens):
        """Encontra menções com o maior trecho possível, sem sobreposição."""
        norms = [t.norm for t in tokens]
        mentions, i = [], 0
        while i < len(norms):
            found = None
            for length in range(min(self.max_span, len(norms) - i), 0, -1):
                span = tuple(norms[i:i + length])
                text = " ".join(span)
                kinds = []
                if span in self.aliases:
                    kinds.append(Mention(i, i + length, "candidato", tuple(sorted(self.aliases[span])), text))
                if text in self.non_candidates:
                    kinds.append(Mention(i, i + length, "nao_candidato", (), text))
                places = []
                previous = norms[i - 1] if i else ""
                # "Pará" e a preposição "para" só se distinguem por acento ou artigo; "as minas" é gíria.
                state_ok = not (text == "PARA" and not tokens[i].accent and previous not in {"NO", "DO", "PELO", "AO"}) and not (text == "MINAS" and previous == "AS")
                if text in self.state_names and self.state_names[text] and state_ok:
                    places.append(self.state(self.state_names[text]))
                if text in self.gentilics:
                    places.append(self.state(self.gentilics[text]))
                if text in self.nicknames:
                    places.append(self.nicknames[text])
                elif text in self.cities:
                    places.extend(self.cities[text])
                if places:
                    weak = length == 1 and text in COMMON_WORDS and text not in self.state_names and text not in self.gentilics and text not in self.nicknames
                    kinds.append(Mention(i, i + length, "lugar", tuple(places), text, weak=weak, extra={"gentilic": text in self.gentilics}))
                if text in self.party_names and length > 1:
                    kinds.append(Mention(i, i + length, "partido", (self.party_names[text],), text))
                if kinds:
                    found = kinds
                    break
            if not found:
                i += 1
                continue
            mentions.extend(found)
            i = found[0].end
        return mentions
