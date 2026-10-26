"""Linguagem: tokens normalizados, vocabulário informal, correspondência aproximada e formato pt-BR.

A normalização remove acentos e caixa apenas para comparar; os nomes originais
das bases continuam sendo usados na exibição.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import math
import re
import unicodedata


@dataclass(frozen=True)
class Token:
    norm: str      # maiúsculas sem acento, usado nas comparações
    orig: str      # grafia digitada (sem acento), para distinguir "SP" de "se"
    sep: str       # caracteres entre o token anterior e este ("/", "-", ", ")
    accent: bool = False  # a palavra digitada tinha acento ("Pará" e não a preposição "para")


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c))


# Expressões informais e abreviações frequentes → forma canônica.
INFORMAL = {
    "QTS": "QUANTOS", "QTOS": "QUANTOS", "QNTS": "QUANTOS", "QNTOS": "QUANTOS", "QTD": "QUANTIDADE", "QTDE": "QUANTIDADE",
    "QUANTO": "QUANTOS", "QTAS": "QUANTAS", "QNTAS": "QUANTAS", "VC": "VOCE", "VCS": "VOCES", "TB": "TAMBEM", "TBM": "TAMBEM",
    "Q": "QUE", "OQ": "O QUE", "PRA": "PARA", "PRO": "PARA O", "PROS": "PARA OS", "PRAS": "PARA AS", "PRAH": "PARA",
    "VOTO": "VOTOS", "VOTINHOS": "VOTOS", "PORCENTAGEM": "PERCENTUAL", "PORCENTAGENS": "PERCENTUAL", "PERCENTUAIS": "PERCENTUAL",
    "PORCENTO": "PERCENTUAL", "PERCENT": "PERCENTUAL", "PCT": "PERCENTUAL", "PORCENTUAL": "PERCENTUAL", "NUM": "NUMERO", "NRO": "NUMERO",
    "VS": "VERSUS", "X": "VERSUS", "CONTRA": "VERSUS", "COMPARA": "COMPARAR", "COMPARE": "COMPARAR", "COMPARANDO": "COMPARAR",
    "COMPARACAO": "COMPARAR", "COMPARATIVO": "COMPARAR", "COMPARAI": "COMPARAR", "COMPARO": "COMPARAR", "CIDADEZINHA": "CIDADE",
    "MUNICIPAL": "MUNICIPIO", "ELEITOR": "ELEITORES", "ELEITORADOS": "ELEITORADO", "TA": "ESTA", "TAH": "ESTA",
}
FILLERS = {"MANO", "MANA", "CARA", "VEI", "VEIO", "VELHO", "AE", "OPA", "PFV", "PF", "PFVR", "BLZ", "LAMPIADIM", "LAMPIADIN",
           "LAMPI", "AMIGO", "AMIGA", "PARCEIRO", "BROTHER", "BRO", "TIPO", "AI", "NE", "HEIN", "UAI", "OXE", "OXI", "EITA"}

NUMBER_WORDS = {"UM": 1, "UMA": 1, "DOIS": 2, "DUAS": 2, "TRES": 3, "QUATRO": 4, "CINCO": 5, "SEIS": 6, "SETE": 7, "OITO": 8,
                "NOVE": 9, "DEZ": 10, "ONZE": 11, "DOZE": 12, "TREZE": 13, "QUINZE": 15, "VINTE": 20, "TRINTA": 30, "CINQUENTA": 50, "CEM": 100}
ORDINALS = {"PRIMEIRO": 1, "PRIMEIRA": 1, "SEGUNDO": 2, "SEGUNDA": 2, "TERCEIRO": 3, "TERCEIRA": 3, "QUARTO": 4, "QUARTA": 4,
            "QUINTO": 5, "QUINTA": 5, "SEXTO": 6, "SEXTA": 6, "SETIMO": 7, "SETIMA": 7, "OITAVO": 8, "OITAVA": 8, "NONO": 9,
            "NONA": 9, "DECIMO": 10, "DECIMA": 10, "ULTIMO": -1, "ULTIMA": -1, "PENULTIMO": -2, "PENULTIMA": -2}

# Vocabulário de domínio para corrigir erros de digitação (não inclui nomes próprios).
VOCABULARY = """VOTOS VOTACAO VOTADO VOTADA VOTARAM ELEITORES ELEITORADO ELEITORAS PERCENTUAL DIFERENCA COMPARAR MUNICIPIO MUNICIPIOS
CIDADE CIDADES TURNO PRIMEIRO SEGUNDO CANDIDATO CANDIDATOS CANDIDATA CANDIDATURA CANDIDATURAS GANHOU VENCEU VENCEDOR RECEBEU
QUANTOS QUANTAS ESTADO ESTADOS DISTRIBUICAO ESCOLARIDADE IDADE SEXO GENERO MULHERES HOMENS FEMININO MASCULINO RESULTADO
RANKING MAIORES MENORES DESEMPENHO ABSTENCAO COMPARECIMENTO BRANCOS NULOS VALIDOS PARTIDO TRANSGENERO IDENTIDADE FAIXA
ETARIA ANALFABETOS SUPERIOR PRESIDENTE ELEICAO QUANTIDADE CADASTRADOS BRASIL EXTERIOR MAIS VOTADO LUGAR COLOCADO PERFIL""".split()
VOCABULARY_SET = set(VOCABULARY)

# Palavras comuns da língua e do domínio. Um município cujo nome seja só isso
# (Vitória, União, Natal…) exige pista explícita de lugar para ser reconhecido.
COMMON_WORDS = set("""A O AS OS E OU DE DO DA DOS DAS EM NO NA NOS NAS NUM NUMA UM UMA UNS UMAS PARA POR PELO PELA PELOS PELAS COM
SEM QUE QUAL QUAIS QUEM COMO ONDE QUANDO QUANTOS QUANTAS MAIS MENOS MUITO MUITA POUCO TODO TODA TODOS TODAS ESSE ESSA ESTE ESTA
ISSO ISTO AQUILO ELE ELA ELES ELAS NELE NELA DELE DELA LA LA ALI AQUI AGORA ENTAO TAMBEM SO SOMENTE APENAS JA AINDA BEM MAL
SIM NAO SER FOI FORAM ERA TEVE TEM TINHA TER SAO ESTAVA ESTAVAM HA HAVIA FICOU FICARAM VEZ VEZES CADA OUTRO OUTRA MESMO MESMA
ENTRE SOBRE ATE APOS ANTES DEPOIS ACIMA ABAIXO MAIOR MENOR MAIORES MENORES MELHOR PIOR NOVO NOVA NOVOS VELHO BOM BOA BONS BOAS
ALTO ALTA BAIXO BAIXA GRANDE PEQUENO CENTRO CENTRAL SUL NORTE LESTE OESTE ALEGRE AREIA BARRA BONITO BREJO CALDAS COLORADO CORRENTE
CRISTAL ESPERANCA ESTRELA FATIMA FLORES GLORIA GUARANI IPE LAGOA LIBERDADE MATA OURO PALMAS PIMENTA PLANALTO PORTO PRATA SALTO
SANTOS SERIO SERRA TIROS UNIAO VARGEM VAZANTE VITORIA NATAL PAZ MONTE CAMPO CAMPOS ILHA PRAIA RIO LAGO PONTE PEDRA PEDRAS
FLORESTA PARAISO HORIZONTE PRESIDENTE GOVERNADOR SENADOR PREFEITO DEPUTADO VEREADOR DOUTOR CORONEL PADRE
CAPITAL INTERIOR REGIAO METROPOLITANA LITORAL CIDADE CIDADES MUNICIPIO MUNICIPIOS ESTADO ESTADOS PAIS BRASIL VOTOS VOTACAO
TURNO PRIMEIRO SEGUNDO TERCEIRO ANO ELEICAO ELEICOES RESULTADO RESULTADOS PERCENTUAL DIFERENCA ELEITORES ELEITORADO ELEITORAS
GANHOU VENCEU PERDEU LEVOU MANDOU DEU SAIU SE ME TE NOS LHE SEU SUA MEU MINHA DELES DELAS IGREJA JESUS BARRO CRUZ FORTE
CONTAGEM DATAS MODELO PAINEL PANORAMA REGISTRO TRIUNFO PROPRIA SAUDE ALEGRIA ALIANCA ALMAS ALTOS AMPARO ANGULO ARCOS AURORA
BANDEIRA BARRAS BATALHA CANDEIAS CAPELA CARIDADE CASCA CASTELO CEDRO CHAVES CHORO COLINA COLINAS COLUNA CONDE CORTES CRUZEIRO
DELTA DESCANSO DIAMANTE DIVINO DOURADO ENCANTO ESCADA ESTACAO ESTANCIA ESTREITO EXTREMA FAMA FAROL FARTURA FELIZ FIGUEIRA
FORMIGA FORMOSA FORTUNA FRANCA GENTIL GRACA GRAMADO GRANJA HARMONIA JARDIM JOIA LUZ MANGA MARCO MILAGRES MOEDA MONTANHA MORENO
PASSAGEM PASSOS PATOS PEIXE PEROLA PIEDADE PILAR PORTAO POSSE PRADO PRINCESA PUREZA QUADRA RAPOSA RECREIO REDENCAO REMANSO
RESERVA RIQUEZA ROTEIRO SALGADO SAUDADES SEGREDO SOCORRO SOLEDADE SOLIDAO SONORA SORRISO SOSSEGO TESOURO TORRES TRINDADE
TURVO VALENTE VARZEA VERA VEREDA VIGIA MASCOTE ORIENTE PAULISTA
ELEITORAL ELEITORAIS ELEICOES ELEITO ELEITA ELEITOS ELEITAS VOTANTE MUNICIPAL ESTADUAL FEDERAL PRESIDENCIAL PRESIDENCIAIS REGIONAL
PERGUNTA SABER QUERO QUERIA DESCOBRIR CONSEGUE CONSEGUIU RECEBIDOS RECEBIDAS RECEBIDO MOSTRA MOSTRE MOSTRAR FALA FALE DIGA DIZER
PASSA PASSAR INFORMA INFORMAR INFORME VOTANDO VOTARAM VOTOU VOTAR VOTA VOTAM VOTEI VOTE ESCOLHERAM ESCOLHEU DADOS DADO BASE
CANDIDATA CANDIDATAS COLOCADO COLOCADA COLOCACAO MUNICIPAIS ESTADUAIS PORCENTAGEM QUANTIDADE PESSOAS GENTE CIDADAOS
ESTAO ESTAVA ESTAVAM SERAO FICAM MORAM VIVEM EXISTEM EXISTE POSSUEM POSSUI TEEM HAVIA TINHAM CONTA CONTAS MOSTRAM DIGO
""".split()) | VOCABULARY_SET | set(NUMBER_WORDS) | set(ORDINALS) | FILLERS

PARTICLES = {"DA", "DE", "DO", "DAS", "DOS", "E", "D"}


def tokenize(text):
    """Tokens com grafia original (sem acento) e separadores, com o vocabulário informal expandido."""
    tokens, last = [], 0
    for match in re.finditer(r"[^\W_]+", str(text)):
        sep, last = text[last:match.start()], match.end()
        stripped = strip_accents(match.group())
        for k, orig in enumerate(re.findall(r"[A-Za-z0-9]+", stripped)):
            norm = orig.upper()
            if norm in FILLERS:
                continue
            expanded = INFORMAL.get(norm, norm)
            if norm == "X" and not tokens:
                expanded = norm
            for i, part in enumerate(expanded.split()):
                tokens.append(Token(part, orig if i == 0 else part.lower(), sep if i == k == 0 else " ", stripped != match.group()))
    return tokens


def correct_typos(tokens, protected):
    """Corrige palavras do vocabulário de domínio digitadas com erro (ex.: 'eleitroes').

    Índices em ``protected`` pertencem a entidades e nunca são alterados.
    """
    fixed = []
    for i, token in enumerate(tokens):
        word = token.norm
        if i in protected or len(word) < 5 or word.isdigit() or word in COMMON_WORDS:
            fixed.append(token)
            continue
        match = difflib.get_close_matches(word, VOCABULARY, n=1, cutoff=0.86)
        fixed.append(Token(match[0], token.orig, token.sep) if match else token)
    return fixed


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_fuzzy(word, choices, cutoff):
    """Melhor correspondência aproximada, somente se for única acima do limite."""
    scored = sorted(((similar(word, c), c) for c in choices if abs(len(c) - len(word)) <= 3), reverse=True)
    if not scored or scored[0][0] < cutoff:
        return None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.02 and scored[1][1] != scored[0][1]:
        return None
    return scored[0][1]


# ---------------------------------------------------------------------------
# Formatação brasileira. Cálculos preservam a precisão; só a exibição arredonda.

def fmt_int(value):
    return f"{int(value):,}".replace(",", ".")


def fmt_dec(value, places=1):
    return f"{value:.{places}f}".replace(".", ",")


def places_for(values, minimum=1, maximum=4):
    """Casas decimais mínimas para que valores distintos não pareçam iguais nem um positivo pareça zero."""
    clean = [v for v in values if v is not None and not math.isnan(v)]
    for places in range(minimum, maximum + 1):
        rounded = [round(v, places) for v in clean]
        collide = any(rounded[i] == rounded[j] and clean[i] != clean[j] for i in range(len(clean)) for j in range(i + 1, len(clean)))
        vanishes = any(v > 0 and round(v, places) == 0 for v in clean)
        if not collide and not vanishes:
            return places
    return maximum


def fmt_pct(value, places=1):
    return "indisponível" if value is None or (isinstance(value, float) and math.isnan(value)) else fmt_dec(value, places) + "%"


def fmt_pp(value, places=1):
    unit = "ponto percentual" if round(abs(value), places) == 1 else "pontos percentuais"
    return f"{fmt_dec(value, places)} {unit}"


def title_name(text):
    """Caixa de título preservando acentos originais e partículas em minúsculas."""
    words = []
    for i, word in enumerate(str(text).lower().split()):
        if i and word in {"da", "de", "do", "das", "dos", "e"}:
            words.append(word)
        elif "'" in word:
            head, _, tail = word.partition("'")
            words.append((head if len(head) == 1 else head.capitalize()) + "'" + tail.capitalize())
        elif "-" in word:
            words.append("-".join(part.capitalize() for part in word.split("-")))
        else:
            words.append(word.capitalize())
    return " ".join(words)


_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?)(?![\w])\s*(mil\b|milh[aã]o\b|milh[oõ]es\b|%|por ?cento\b)?", re.I)


def asserted_numbers(text):
    """Números afirmados pelo usuário (ex.: '100 mil votos', '90%'), excluindo anos, DDD, turnos, idades e limites."""
    found = []
    for match in _NUMBER.finditer(text):
        raw, unit = match.group(1), (match.group(2) or "").lower()
        before = text[max(0, match.start() - 12):match.start()].lower()
        after = text[match.end():match.end() + 16].lower()
        if re.search(r"ddd\s*$|top\s*$|turno\s*$", before) or re.match(r"\s*(º|°|o\b|a\b|ª|turno|anos|cidades|munic|estados|primeir|maiores|menores|candidat|colocad|lugar)", after):
            continue
        value = float(raw.replace(".", "").replace(",", "."))
        if not unit and re.fullmatch(r"(19|20)\d{2}", raw):
            continue
        if not unit and value < 100 and not re.match(r"\s*votos", after):
            continue
        kind = "pct" if unit in {"%", "por cento", "porcento"} else "abs"
        approximate = bool(unit in {"mil"} or unit.startswith("milh") or "," in raw)
        value *= 1_000 if unit == "mil" else 1_000_000 if unit.startswith("milh") else 1
        found.append((value, kind, approximate))
    return found


def numbers_in(text):
    """Números exibidos num texto pt-BR, para conferir a origem de cada um."""
    return re.findall(r"\d[\d.]*(?:,\d+)?", text)
