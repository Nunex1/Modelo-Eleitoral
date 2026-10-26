"""Interpretador semântico local: pergunta em português → Frame estruturado.

Combina normalização (acentos, caixa, abreviações informais, erros de digitação),
reconhecimento de entidades verificadas na base, sintaxe leve do português
(preposições, artigos, ordinais, pronomes) e regras de domínio eleitoral.
Não calcula números: apenas descreve o que foi pedido e o que está ambíguo.
"""
from __future__ import annotations

import re

from .context import Frame
from .data import normalize
from .entities import REGIONS, UF_COLLIDING, UF_WITH_ARTICLE, Territory
from .language import COMMON_WORDS, NUMBER_WORDS, ORDINALS, asserted_numbers, best_fuzzy, correct_typos, tokenize

# Palavras que podem seguir "em"/"de" sem serem nomes de lugar.
NOT_PLACE = COMMON_WORDS | set("""RELACAO COMPARACAO TERMOS GERAL MEDIA ORDEM BRANCO BRANCOS NULO NULOS SEPARADO CONJUNTO AMBOS AMBAS
NENHUM NENHUMA ALGUM ALGUMA OUTROS OUTRAS DESTAQUE DETALHES DETALHE TABELA LISTA RESUMO SEGUIDA ESPECIAL PARTICULAR NUMEROS ABSOLUTOS
ABSOLUTO VALOR VALORES MIM VOCE LUGAR LUGARES DIA MES TOTAL TODA GRAFICO MAPA FORMA FORMATO SI CANDIDATO CANDIDATA CANDIDATOS
CANDIDATURA CANDIDATURAS PARTIDO PARTIDOS VOTOS ELEITORES DDD UF PAIS NACIONAL EXTERIOR QUANTIDADE NUMERO PROPORCAO DETERMINADO
DETERMINADA ALGUEM NINGUEM CIMA BAIXO FRENTE TRAS META VIRTUDE FUNCAO MATERIA TEMPO VEZ PRATICA TESE CASO CIMA TEMPO REAL OPINIAO
DIFERENCA PORCENTAGEM DESEMPENHO PERFIL IDADE SEXO GENERO ESCOLARIDADE IDENTIDADE FAIXA HOMENS MULHERES JOVENS IDOSOS""".split())

VOTE_WORDS = {"VOTOS", "VOTACAO", "VOTADO", "VOTADA", "VOTADOS", "VOTADAS", "SUFRAGIOS"}
VOTE_VERBS = {"VOTARAM", "VOTOU", "VOTAM", "VOTA", "VOTARIAM", "VOTARIA", "ESCOLHERAM", "ESCOLHEU", "PREFERIRAM", "PREFERIU", "APOIARAM",
              "APOIOU", "ELEGERAM", "DERAM"}
ELIGIBLE = ["APTOS A VOTAR", "APTAS A VOTAR", "PODEM VOTAR", "PODIAM VOTAR", "PODERIAM VOTAR", "HABILITADOS A VOTAR", "OBRIGADOS A VOTAR",
            "APTOS PARA VOTAR", "CADASTRADOS PARA VOTAR", "ESTAVAM APTOS", "ESTAO APTOS"]
COUNT_WORDS = {"QUANTOS", "QUANTAS", "QUANTIDADE", "NUMERO", "TOTAL", "SOMA"}
PCT_WORDS = {"PERCENTUAL", "PROPORCAO", "FATIA", "PARCELA", "PROPORCIONAL", "PROPORCIONALMENTE"}
WIN_PHRASES = ["GANHOU", "VENCEU", "VENCEDOR", "VENCEDORA", "GANHADOR", "GANHADORA", "LIDEROU", "LIDER", "PRIMEIRO LUGAR", "MAIS VOTADO",
               "MAIS VOTADA", "NA FRENTE", "LEVOU", "LEVOU A MELHOR", "SE SAIU MELHOR", "SAIU MELHOR", "DOMINOU", "PREVALECEU",
               "TEVE MAIS VOTOS", "TEVE MAIS", "MAIS VOTOS", "RECEBEU MAIS", "OBTEVE MAIS", "FICOU EM PRIMEIRO", "GANHA EM", "VENCE EM"]
LOSE_PHRASES = ["MENOS VOTADO", "MENOS VOTADA", "ULTIMO LUGAR", "TEVE MENOS VOTOS", "MENOS VOTOS", "FICOU EM ULTIMO", "RECEBEU MENOS"]
COMPARE_WORDS = {"COMPARAR", "VERSUS", "COMPARADO", "COMPARADA", "CONFRONTO", "CONFRONTE", "CONFRONTAR"}
DIFF_PHRASES = ["DIFERENCA", "VANTAGEM", "MARGEM", "DISTANCIA", "A MAIS", "A MENOS", "FRENTE DE"]
RELATIVE_PHRASES = ["POR CENTO A MAIS", "PERCENTUAL A MAIS", "VEZES MAIS", "VARIACAO", "RELATIVA", "RELATIVO", "PROPORCIONALMENTE MAIS"]
PP_PHRASES = ["PONTOS PERCENTUAIS", "PONTO PERCENTUAL", "PP", "P P", "DIFERENCA PERCENTUAL", "DIFERENCA EM PERCENTUAL", "DIFERENCA DE PERCENTUAL"]
ELECTORATE_WORDS = {"ELEITORES", "ELEITORADO", "ELEITORAS", "ELEITORA", "CADASTRADOS", "CADASTRADAS", "APTOS", "APTAS", "INSCRITOS", "CADASTRO"}
DISTRIBUTION_PHRASES = ["DISTRIBUICAO", "PERFIL", "COMPOSICAO", "DIVISAO", "DIVIDIDO", "DIVIDIDA", "POR SEXO", "POR IDADE", "POR FAIXA",
                        "POR ESCOLARIDADE", "POR GENERO", "POR IDENTIDADE", "QUAL A ESCOLARIDADE", "QUAL A IDADE", "PIRAMIDE"]
PERFORMANCE_PHRASES = ["DESEMPENHO", "COMO FOI", "COMO SE SAIU", "SE SAIU", "FOI BEM", "FOI MAL", "PERFORMANCE", "ATUACAO", "RENDIMENTO ELEITORAL"]
RESULT_PHRASES = ["RESULTADO", "RESULTADOS", "PANORAMA", "RESUMO", "APURACAO", "PLACAR", "COMO FOI A ELEICAO", "COMO FOI A VOTACAO"]
CANDIDACY_WORDS = {"CANDIDATOS", "CANDIDATAS", "CANDIDATURAS", "CONCORRERAM", "CONCORREU", "DISPUTARAM", "CONCORRENTES", "PRESIDENCIAVEIS"}
GREETINGS = {"OI", "OLA", "OLAR", "EAI", "EAE", "SALVE", "HELLO", "HI", "BOM DIA", "BOA TARDE", "BOA NOITE", "TUDO BEM", "OI TUDO BEM"}
THANKS = {"OBRIGADO", "OBRIGADA", "VALEU", "BRIGADO", "GRATO", "GRATA", "OBG", "VLW", "TMJ", "MUITO OBRIGADO", "MUITO OBRIGADA"}
HELP_PHRASES = ["AJUDA", "O QUE VOCE FAZ", "O QUE VOCE SABE", "COMO FUNCIONA", "O QUE POSSO PERGUNTAR", "QUEM E VOCE", "QUEM VOCE E",
                "EXEMPLOS", "COMO USAR", "QUE PERGUNTAS"]
OPINION_PHRASES = ["EM QUEM VOTAR", "EM QUEM EU VOTO", "DEVO VOTAR", "VOCE VOTARIA", "VOCE APOIA", "MELHOR CANDIDATO", "PIOR CANDIDATO",
                   "QUEM E MELHOR", "QUEM E O MELHOR", "VOCE PREFERE", "SUA OPINIAO", "OPINIAO", "VOCE ACHA", "O QUE ACHA", "ACHA QUE",
                   "CONVENCER", "PERSUADIR", "PROPAGANDA", "COMUNISTA", "FASCISTA", "LADRAO", "CORRUPTO", "MERECE", "MERECIA"]
PREDICTION_PHRASES = ["VAI GANHAR", "VAI VENCER", "VAI PERDER", "QUEM GANHA O SEGUNDO", "QUEM VENCE O SEGUNDO", "QUEM VAI", "PREVER", "PREVISAO",
                      "PROJECAO", "PROJETAR", "ESTIMATIVA", "ESTIMAR", "PESQUISA ELEITORAL", "PESQUISAS", "CHANCE", "CHANCES",
                      "PROBABILIDADE", "FAVORITO", "VAI SER ELEITO", "SERA ELEITO", "VAI LEVAR", "VAI FICAR", "VAI TER"]
CAUSAL_PHRASES = ["POR QUE", "PORQUE", "POR QUAL MOTIVO", "MOTIVO", "RAZAO", "CAUSA", "CAUSOU", "EXPLICA O", "EXPLIQUE O", "QUAL A EXPLICACAO"]
OTHER_OFFICE = {"GOVERNADOR", "GOVERNADORA", "GOVERNADORES", "SENADOR", "SENADORA", "SENADORES", "DEPUTADO", "DEPUTADA", "DEPUTADOS",
                "PREFEITO", "PREFEITA", "PREFEITOS", "VEREADOR", "VEREADORA", "VEREADORES", "SENADO", "CAMARA", "ASSEMBLEIA"}
TURNOUT_PHRASES = ["COMPARECIMENTO", "COMPARECERAM", "COMPARECEU", "ABSTENCAO", "ABSTENCOES", "ABSTIVERAM", "VOTANTES", "FORAM VOTAR",
                   "DEIXARAM DE VOTAR", "NAO VOTARAM", "FALTARAM", "AUSENTES", "PARTICIPACAO", "TAXA DE PARTICIPACAO", "FOI VOTAR"]
BLANK_PHRASES = ["VOTOS BRANCOS", "VOTOS EM BRANCO", "VOTO EM BRANCO", "VOTOS NULOS", "NULOS", "ANULARAM", "ANULADOS", "BRANCOS E NULOS",
                 "VOTARAM EM BRANCO", "VOTARAM NULO", "VOTOS INVALIDOS", "INVALIDOS"]
HISTORY_PHRASES = ["HISTORICO", "HISTORICA", "EVOLUCAO", "AO LONGO", "ELEICOES ANTERIORES", "ELEICAO ANTERIOR", "ULTIMAS ELEICOES",
                   "SERIE HISTORICA", "COMPARADO A ELEICAO", "EM RELACAO A ELEICAO", "DESDE 20"]
REGION_PHRASES = ["INTERIOR", "REGIAO METROPOLITANA", "REGIAO DE", "GRANDE SAO PAULO", "LITORAL", "BAIXADA", "RMSP", "REGIAO DO", "REGIAO DA"]
INJECTION_PHRASES = ["IGNORE", "IGNORA", "ESQUECA", "ESQUECE", "INSTRUCOES", "SYSTEM PROMPT", "PROMPT", "FINJA", "INVENTE", "INVENTA",
                     "MODO DESENVOLVEDOR", "JAILBREAK", "DROP TABLE", "SELECT", "DELETE FROM"]
UNAVAILABLE_DIMENSIONS = {"RACA": "raça/cor", "COR DA PELE": "raça/cor", "ETNIA": "raça/cor", "NEGROS": "raça/cor", "PRETOS": "raça/cor",
                          "PARDOS": "raça/cor", "INDIGENAS": "raça/cor", "RENDA": "renda", "SALARIO": "renda", "CLASSE SOCIAL": "renda",
                          "POBRES": "renda", "RICOS": "renda", "CLASSE MEDIA": "renda", "RENDIMENTO": "renda", "RELIGIAO": "religião",
                          "EVANGELICOS": "religião", "CATOLICOS": "religião", "RELIGIOSOS": "religião", "ESTADO CIVIL": "estado civil",
                          "CASADOS": "estado civil", "SOLTEIROS": "estado civil", "PROFISSAO": "ocupação", "OCUPACAO": "ocupação",
                          "APOSENTADOS": "ocupação", "DESEMPREGADOS": "ocupação", "ESTUDANTES": "ocupação", "DEFICIENCIA": "deficiência",
                          "DEFICIENTES": "deficiência", "PCD": "deficiência", "BIOMETRIA": "biometria", "QUILOMBOLA": "quilombola",
                          "QUILOMBOLAS": "quilombola", "NOME SOCIAL": "nome social", "LIBRAS": "intérprete de libras",
                          "ORIENTACAO SEXUAL": "orientação sexual", "LGBT": "orientação sexual", "GAYS": "orientação sexual"}
FUZZY_EXCLUDED = {w for phrase in UNAVAILABLE_DIMENSIONS for w in phrase.split()} | {"RENDA", "LULO", "ZONA", "CAIXA", "SALA", "SAMBA", "CURA", "CURSO"}
DIMENSION_LABEL = {"sexo": "o sexo", "identidade": "a identidade de gênero", "idade": "a idade", "escolaridade": "a escolaridade"}
ARTICLED = {"raça/cor": "a raça/cor", "renda": "a renda", "religião": "a religião", "estado civil": "o estado civil", "ocupação": "a ocupação",
            "deficiência": "a deficiência", "biometria": "a biometria", "quilombola": "a condição quilombola", "nome social": "o nome social",
            "intérprete de libras": "a necessidade de intérprete de libras", "orientação sexual": "a orientação sexual"}
VAGUE_AGES = ["JOVENS", "JOVEM", "IDOSOS", "IDOSAS", "IDOSO", "IDOSA", "ADOLESCENTES", "ADULTOS", "TERCEIRA IDADE", "MAIS VELHOS", "MAIS NOVOS"]
GROUP_WORDS = {"MULHER", "MULHERES", "HOMEM", "HOMENS", "FEMININO", "FEMININA", "MASCULINO", "MASCULINA", "ELEITORAS", "TRANS", "CIS",
               "TRANSGENERO", "TRANSGENEROS", "CISGENERO", "CISGENEROS", "ANALFABETOS", "SEXO", "GENERO", "IDADE", "ETARIA", "ESCOLARIDADE"} | set(VAGUE_AGES)
CANDIDATE_REFS = {"ELE": "foco", "ELA": "foco", "NELE": "foco", "NELA": "foco", "DELE": "foco", "DELA": "foco", "O CANDIDATO": "foco",
                  "A CANDIDATA": "foco", "ESSE CANDIDATO": "foco", "ESSA CANDIDATA": "foco", "MESMO CANDIDATO": "foco",
                  "OS DOIS": "par", "AS DUAS": "par", "AMBOS": "par", "AMBAS": "par", "ELES": "par", "OS 2": "par", "ESSES DOIS": "par",
                  "ESSAS DUAS": "par", "OS DOIS CANDIDATOS": "par", "AS DUAS CANDIDATURAS": "par", "UM DO OUTRO": "par",
                  "O VENCEDOR": "top2", "A VENCEDORA": "top2", "O MAIS VOTADO": "vencedor", "O PRIMEIRO COLOCADO": "vencedor",
                  "OS DOIS PRIMEIROS": "top2", "O PRIMEIRO E O SEGUNDO": "top2", "PRIMEIRO E SEGUNDO": "top2", "1O E 2O": "top2",
                  "O GANHADOR": "top2", "QUEM GANHOU": "top2"}
PLACE_REFS = {"LA": "foco", "ALI": "foco", "NESSA CIDADE": "foco", "NESSE MUNICIPIO": "foco", "NESTA CIDADE": "foco", "NESTE MUNICIPIO": "foco",
              "MESMA CIDADE": "foco", "MESMO MUNICIPIO": "foco", "DESSA CIDADE": "foco", "DESSE MUNICIPIO": "foco", "ESSA CIDADE": "foco",
              "ESSE MUNICIPIO": "foco", "NESSE ESTADO": "foco", "NESTE ESTADO": "foco", "AS DUAS CIDADES": "par", "OS DOIS MUNICIPIOS": "par",
              "AMBAS AS CIDADES": "par", "AMBOS OS MUNICIPIOS": "par", "ESSAS CIDADES": "par", "ESSES MUNICIPIOS": "par", "AS 2 CIDADES": "par"}
CORRECTION_PHRASES = ["NA VERDADE", "QUIS DIZER", "EU QUIS DIZER", "CORRIGINDO", "CORRECAO", "DIGO", "ERREI", "OPS", "NAO ERA",
                      "MELHOR DIZENDO", "ME CONFUNDI", "ME ENGANEI", "EU ME ENGANEI", "QUERIA DIZER"]
FOLLOWUP_STARTS = ("E ", "TAMBEM ", "AGORA ", "MAS E ", "E QUANTO ", "E SOBRE ", "E PARA ", "E COM ", "ENTAO ", "E SE ")
METRIC_ONLY = {"PERCENTUAL": "percentual", "EM VOTOS": "votos", "NUMERO ABSOLUTO": "votos", "NUMEROS ABSOLUTOS": "votos",
               "EM NUMEROS": "votos", "VALOR ABSOLUTO": "votos", "QUANTIDADE DE VOTOS": "votos"}
PLACE_CUES = {"EM", "CIDADE", "MUNICIPIO", "CIDADES", "MUNICIPIOS"}
SIMULATION_WORDS = {"SIMULE", "SIMULAR", "SIMULA", "SIMULACAO", "SIMULACOES", "SIMULADO", "SIMULADA", "SIMULADOS", "SIMULADAS", "HIPOTETICO",
                    "HIPOTETICA", "HIPOTETICOS", "HIPOTETICAS", "HIPOTESE", "CENARIO", "CONTRAFACTUAL"}
REALITY_PHRASES = ["REALMENTE", "DE VERDADE", "NA REALIDADE", "DE FATO", "NA VERDADE QUANTOS", "VOTOS REAIS", "NUMERO REAL", "DADO REAL"]
DIMENSION_WORDS = [("sexo", {"SEXO", "SEXOS", "GENERO", "HOMENS", "MULHERES", "HOMEM", "MULHER", "FEMININO", "MASCULINO", "ELEITORAS"}),
                   ("identidade", {"IDENTIDADE", "TRANSGENERO", "TRANSGENEROS", "CISGENERO", "CISGENEROS"}),
                   ("idade", {"IDADE", "IDADES", "ETARIA", "ETARIAS", "ETARIO", "JOVENS", "IDOSOS"}),
                   ("escolaridade", {"ESCOLARIDADE", "INSTRUCAO", "EDUCACAO", "ESCOLAR"})]
TIME_WORDS = {"HORARIO", "HORARIOS", "HORA", "HORAS", "ENCERRAMENTO", "ENCERRAMENTOS", "ENCERRARAM", "ENCERROU", "ENCERRADAS", "ESTENDIDA",
              "ESTENDIDAS", "TARDIA", "TARDIAS", "FECHARAM", "FECHOU", "FECHAMENTO", "ABERTURA", "ABRIRAM", "PRORROGADA", "PRORROGADAS"}
TURNS_PHRASES = ["OS DOIS TURNOS", "AMBOS OS TURNOS", "ENTRE OS TURNOS", "NOS DOIS TURNOS", "PRIMEIRO E SEGUNDO TURNO", "PRIMEIRO E NO SEGUNDO TURNO",
                 "PRIMEIRO E O SEGUNDO TURNO", "1O E 2O TURNO", "1O E NO 2O TURNO", "DO PRIMEIRO PARA O SEGUNDO", "COMPARAR OS TURNOS", "DE UM TURNO PARA O OUTRO"]
FACTOR_PATTERNS = [re.compile(r"(?:peso|fator|multiplicador)\s*(?:de\s*)?(\d+(?:[.,]\d+)?)\s*(?:x\s*)?(?:para|nos|nas|aos|às|as|a|em|no|na)?\s*(?:as|os)?\s*(mulheres|homens|feminino|masculino|eleitoras)", re.I),
                   re.compile(r"(mulheres|homens|feminino|masculino|eleitoras)\s*(?:com\s*)?(?:peso|fator|multiplicador)\s*(?:de\s*)?(\d+(?:[.,]\d+)?)", re.I)]
SECOND_ROUND_QUESTION = re.compile(r"(QUEM|QUAIS|QUAL|QUANTOS|QUE CANDIDAT\w*) .*(FOI|FORAM|PASSOU|PASSARAM|CLASSIFIC\w*|VAI|VAO|DISPUT\w*|CHEGOU|CHEGARAM|AVANCOU|AVANCARAM) .*(PARA O|AO|NO|PRO) (SEGUNDO|2O|2) TURNO")


def split_clauses(text):
    """Separa perguntas múltiplas ('…? E …', '…; …', '… e qual …')."""
    parts = re.split(r"\?+|;|\n+|\s+e\s+(?=(?:qual|quais|quant[oa]s?|quem|onde|como)\b)", text, flags=re.I)
    clauses = [p.strip(" ,.!") for p in parts if p and p.strip(" ,.!")]
    return clauses[:4] or [text]


def has(q, *phrases):
    return any(f" {p} " in q for p in phrases)


class Interpreter:
    def __init__(self, engine):
        self.engine = engine
        self.kb = engine.kb
        categories = engine.data.categories
        self.category_lookup = {name: {normalize(v): v for v in values} for name, values in categories.items()}
        self.age_bands = {band: bounds for band, bounds in engine.age_bands.items() if bounds}
        self.single_aliases = [k for k in self.kb.single_aliases if len(k) >= 4]

    # ------------------------------------------------------------------ ponto de entrada
    def interpret(self, text, state):
        tokens = tokenize(text)
        if not tokens:
            return Frame("desconhecido")
        mentions = self.kb.scan(tokens)
        protected = {i for m in mentions for i in range(m.start, m.end)}
        tokens = correct_typos(tokens, protected)
        norms = [t.norm for t in tokens]
        q = " " + " ".join(norms) + " "
        frame = Frame("")
        frame.asserted = asserted_numbers(text)
        frame.factors = self._factors(text)
        issues = []

        # Entidades ---------------------------------------------------------
        abbreviations = self._uf_abbreviations(tokens, protected, mentions)
        territories, consumed_states = self._places(tokens, norms, mentions, abbreviations, state, issues)
        candidates = []
        for m in mentions:
            if m.kind == "candidato":
                if len(m.values) == 1:
                    candidates.append(m.values[0])
                else:
                    issues.append(("candidato_ambiguo", {"text": m.text, "options": list(m.values)}))
            elif m.kind == "nao_candidato" and not any(o.kind == "candidato" and o.start == m.start for o in mentions):
                issues.append(("candidato_inexistente", {"text": m.text}))
            elif m.kind == "partido":
                candidates.extend(c.key for c in self.kb.candidates.values() if c.party == m.values[0])
        protected |= {i for i, _ in abbreviations}
        candidates.extend(self._fuzzy_candidates(tokens, protected))
        candidates.extend(self._party_candidates(tokens, protected, candidates, issues))
        candidates = list(dict.fromkeys(candidates))
        unknown = self._unknown_names(tokens, norms, protected, mentions, territories)
        frame.candidates, frame.territories = candidates, territories

        # Período, DDD, regiões e abrangência --------------------------------
        years = [int(n) for n in norms if re.fullmatch(r"(19|20)\d{2}", n)]
        frame.year = years[0] if years else None
        if len(set(years)) > 1:
            issues.append(("anos_multiplos", {"years": sorted(set(years))}))
        second_round_question = bool(SECOND_ROUND_QUESTION.search(q)) and not (VOTE_WORDS & set(norms))
        if not second_round_question:
            frame.turn = self._turn(q)
        for i, n in enumerate(norms):
            glued = re.fullmatch(r"DDD(\d{2})", n)
            number = int(glued.group(1)) if glued else int(n) if re.fullmatch(r"\d{2}", n) and i and norms[i - 1] in {"DDD", "AREA"} else None
            if number is not None:
                if number in self.kb.ddds:
                    frame.territories.append(self.kb.ddd(number))
                else:
                    issues.append(("ddd_inexistente", {"ddd": number}))
        for key, (name, ufs) in REGIONS.items():
            if has(q, "REGIAO " + key, "NO " + key, "DO " + key, "REGIAO " + key.replace(" ", "")) or (key in {"NORDESTE", "SUDESTE", "CENTRO OESTE"} and has(q, key)):
                if not (key in {"SUL", "NORTE"} and has(q, "RIO GRANDE DO " + key, "MATO GROSSO DO " + key)):
                    frame.territories.append(Territory("regiao", key, name))
        if has(q, "INCLUINDO O EXTERIOR", "COM O EXTERIOR", "COM EXTERIOR", "TOTAL GERAL", "INCLUSIVE O EXTERIOR", "BRASIL E EXTERIOR", "BRASIL E NO EXTERIOR"):
            frame.territories.append(Territory("total"))
        elif has(q, "EXTERIOR", "FORA DO PAIS", "FORA DO BRASIL", "NO EXTERIOR"):
            frame.territories.append(Territory("exterior"))
        elif has(q, "NO BRASIL", "DO BRASIL", "NACIONAL", "TODO O BRASIL", "NO PAIS", "DO PAIS", "BRASIL INTEIRO", "TODO O PAIS", "NACIONALMENTE", "EM TODO O BRASIL"):
            if not frame.territories:
                frame.territories.append(Territory("brasil"))
        frame.territories = list(dict.fromkeys(frame.territories))

        # Referências ao contexto -------------------------------------------
        refs_q = q  # "os dois turnos" e "ambos os turnos" não se referem a candidaturas
        for phrase in TURNS_PHRASES:
            refs_q = refs_q.replace(f" {phrase} ", " ")
        for phrase, ref in sorted(CANDIDATE_REFS.items(), key=lambda kv: -len(kv[0])):
            if has(refs_q, phrase) and not (ref == "par" and has(q, *[p for p, r in PLACE_REFS.items() if r == "par"])):
                frame.candidate_ref = ref
                break
        for phrase, ref in sorted(PLACE_REFS.items(), key=lambda kv: -len(kv[0])):
            if has(q, phrase):
                frame.place_ref = ref
                break
        if frame.candidate_ref == "foco" and has(q, "NELA") and state.territories and not state.candidates:
            frame.candidate_ref, frame.place_ref = "", "foco"

        # Cadastro: dimensões e categorias ----------------------------------
        self._demographics(q, norms, frame, issues)

        # Intenção ----------------------------------------------------------
        frame.detail["person_mentioned"] = any(code == "candidato_inexistente" for code, _ in issues + ([unknown] if unknown else []))
        frame.followup = q.lstrip().startswith(FOLLOWUP_STARTS) or (len(norms) <= 4 and bool(candidates or territories or frame.turn or frame.year))
        frame.correction = has(q, *CORRECTION_PHRASES) or (norms[0] == "NAO" and bool(candidates or territories) and len(norms) <= 6)
        self._intent(q, norms, frame, state, second_round_question)
        if frame.intent in {"limitacao", "ajuda", "saudacao", "agradecimento", "fora_escopo"}:
            return frame
        # Problemas de entidade valem mais que qualquer intenção numérica.
        if unknown and not issues:
            issues.append(unknown)
        if issues:
            code, detail = issues[0]
            frame.detail = {"intent": frame.intent, **detail}
            frame.intent, frame.reason = "problema", code
        return frame

    # ------------------------------------------------------------------ entidades
    def _uf_abbreviations(self, tokens, protected, mentions):
        found = []
        for i, t in enumerate(tokens):
            if i in protected or t.norm not in self.kb.states or len(t.norm) != 2:
                continue
            explicit = t.orig.isupper() or t.sep.strip() in {"/", "-", "(", "/ ", ","} or (i and tokens[i - 1].norm in {"UF", "ESTADO", "SIGLA"})
            if t.norm in UF_COLLIDING and not explicit:
                continue
            if not explicit and t.norm in {"PR", "SC", "MS", "GO", "BA", "RN", "RS", "RJ", "MG", "SP", "DF", "PB", "RR"}:
                explicit = True
            if explicit:
                found.append((i, t.norm))
        return found

    def _places(self, tokens, norms, mentions, abbreviations, state, issues):
        territories, consumed = [], set()
        abbr_at = dict(abbreviations)
        places = [m for m in mentions if m.kind == "lugar"]
        explicit_states = {m.values[0].code for m in places if len(m.values) == 1 and m.values[0].kind == "uf"} | set(abbr_at.values())
        context_uf = state.territories[0].uf or (state.territories[0].code if state.territories[0].kind == "uf" else "") if state.territories else ""
        for m in places:
            prev = norms[max(0, m.start - 3):m.start]
            prev1 = prev[-1] if prev else ""
            nxt = norms[m.end] if m.end < len(norms) else ""
            qualifier = abbr_at.get(m.end, "")
            if qualifier:
                consumed.add(m.end)
            state_cue = (len(prev) >= 2 and prev[-2] in {"ESTADO", "UF"}) or prev1 in {"ESTADO", "UF"}
            capital_cue = "CAPITAL" in prev[-2:] or nxt == "CAPITAL"
            city_cue = capital_cue or (len(prev) >= 2 and prev[-2] in {"CIDADE", "MUNICIPIO"}) or prev1 in {"CIDADE", "MUNICIPIO"}
            if m.extra.get("gentilic"):
                # "município paulista" é adjetivo; "município de Paulista" é o nome da cidade.
                city_cue = capital_cue or (len(prev) >= 2 and prev[-2] in {"CIDADE", "MUNICIPIO"} and prev1 in {"DE", "DA"}) or prev1 == "EM"
            strong = city_cue or prev1 in PLACE_CUES or bool(qualifier)
            if m.weak and not strong:
                continue
            states = [t for t in m.values if t.kind == "uf"]
            cities = [t for t in m.values if t.kind == "municipio"]
            # "capital de São Paulo", "capital do Paraná": a capital do estado citado.
            if "CAPITAL" in prev[-2:] and states and states[0].code in self.kb.capitals:
                territories.append(self.kb.capitals[states[0].code])
                continue
            if nxt == "CAPITAL" and states and cities:
                cities = [c for c in cities if c.uf == states[0].code] or cities
                states = []
            if states and cities:
                if state_cue or (m.extra.get("gentilic") and not city_cue):
                    territories.append(states[0])
                    continue
                if city_cue or qualifier:
                    chosen = [c for c in cities if not qualifier or c.uf == qualifier]
                    if len(chosen) == 1:
                        territories.append(chosen[0])
                    elif not chosen:
                        issues.append(("municipio_fora_da_uf", {"text": m.text, "uf": qualifier, "found": sorted({c.uf for c in cities})}))
                    else:
                        issues.append(("municipio_homonimo", {"text": m.text, "options": chosen}))
                    continue
                if prev1 in {"NO", "DO", "PELO", "AO"} and states[0].code in UF_WITH_ARTICLE:
                    territories.append(states[0])
                    continue
                issues.append(("estado_ou_municipio", {"text": m.text, "options": [states[0]] + cities}))
                continue
            if states:
                territories.append(states[0])
                continue
            if qualifier:
                chosen = [c for c in cities if c.uf == qualifier]
                if not chosen:
                    issues.append(("municipio_fora_da_uf", {"text": m.text, "uf": qualifier, "found": sorted({c.uf for c in cities})}))
                    continue
                cities = chosen
            if len(cities) > 1:
                narrowed = [c for c in cities if c.uf in explicit_states]
                if len(narrowed) != 1 and context_uf:
                    narrowed = [c for c in cities if c.uf == context_uf]
                if len(narrowed) == 1:
                    cities = narrowed
                    consumed_state = narrowed[0].uf
                    territories[:] = [t for t in territories if not (t.kind == "uf" and t.code == consumed_state)]
                    explicit_states.discard(consumed_state)
                    consumed.add(consumed_state)
                else:
                    issues.append(("municipio_homonimo", {"text": m.text, "options": cities}))
                    continue
            territories.append(cities[0])
        city_ufs = {t.uf for t in territories if t.kind == "municipio"}
        for i, uf in abbreviations:
            if i in consumed or uf in city_ufs:
                continue
            territories.append(self.kb.state(uf))
        # UF explícita usada para desambiguar um município não é um segundo território.
        territories = [t for t in territories if not (t.kind == "uf" and t.code in city_ufs)]
        return list(dict.fromkeys(territories)), consumed

    def _fuzzy_candidates(self, tokens, protected):
        """Nomes de candidatura com erro de digitação ('Bolsonaru'); marca os índices usados."""
        found = []
        for i, t in enumerate(tokens):
            word = t.norm
            if i in protected or len(word) < 4 or word in NOT_PLACE or word in FUZZY_EXCLUDED or word.isdigit() or word in self.kb.city_names:
                continue
            match = best_fuzzy(word, [a for a in self.single_aliases if a[0] == word[0]], 0.83)
            if match:
                found.extend(self.kb.single_aliases[match])
                protected.add(i)
        return found

    def _party_candidates(self, tokens, protected, candidates, issues):
        found = []
        for i, t in enumerate(tokens):
            if i in protected or t.norm not in self.kb.parties:
                continue
            prev = tokens[i - 1].norm if i else ""
            explicit = prev in {"DO", "DA", "PELO", "PELA", "PARTIDO", "LEGENDA", "SIGLA"} and (t.orig.isupper() or t.norm in {"PT", "PL", "PSD", "PSTU", "PCB", "PCO", "AVANTE", "MISSAO"})
            if not explicit:
                continue
            party = self.kb.parties[t.norm]
            owners = [c.key for c in self.kb.candidates.values() if c.party == party]
            # "Lula do PL": partido incompatível com a candidatura citada.
            if candidates and not set(candidates) & set(owners) and prev in {"DO", "DA", "PELO", "PELA"}:
                issues.append(("partido_incompativel", {"candidate": candidates[-1], "party": party}))
                continue
            found.extend(owners)
        return found

    def _unknown_names(self, tokens, norms, protected, mentions, territories):
        """Nome após um gatilho de lugar/candidatura que não existe na base."""
        def name_after(start):
            words = []
            for j in range(start, min(start + 3, len(tokens))):
                t = tokens[j]
                if j in protected or t.norm in NOT_PLACE or t.norm.isdigit() or len(t.norm) < 3 or t.norm in self.kb.states:
                    break
                words.append(t)
            return words

        for i, n in enumerate(norms):
            if i in protected:
                continue
            place_trigger = n == "EM" or (n == "DE" and i and norms[i - 1] in {"CIDADE", "MUNICIPIO"})
            person_trigger = n in {"DO", "DA"} and i and norms[i - 1] in VOTE_WORDS | {"DESEMPENHO", "PERCENTUAL", "RESULTADO", "VITORIA", "CANDIDATURA"}
            if not (place_trigger or person_trigger):
                continue
            words = name_after(i + 1)
            if not words:
                continue
            raw = tuple(w.norm for w in words)
            if place_trigger:
                fuzzy = self.kb.fuzzy_city(raw) or (self.kb.fuzzy_city(raw[:1]) if len(raw) > 1 else [])
                if len(fuzzy) == 1 and not any(t.kind == "municipio" for t in territories):
                    territories.append(fuzzy[0])
                    continue
                if fuzzy:
                    return ("municipio_homonimo", {"text": " ".join(raw), "options": fuzzy})
            text = " ".join(w.orig for w in words)
            if person_trigger:
                return ("candidato_inexistente", {"text": text})
            return ("entidade_desconhecida", {"text": text})
        # "o Fulano teve/recebeu…" sem candidatura reconhecida
        for i in range(1, len(norms) - 1):
            if norms[i - 1] in {"O", "A"} and norms[i + 1] in {"TEVE", "RECEBEU", "OBTEVE", "CONSEGUIU", "FEZ"} and i not in protected:
                if norms[i] not in NOT_PLACE and not norms[i].isdigit() and len(norms[i]) >= 3:
                    return ("candidato_inexistente", {"text": tokens[i].orig})
        return None

    def _factors(self, text):
        """Fatores hipotéticos ditos na pergunta ('peso 1,2 para mulheres'); só para o cenário ponderado."""
        found = {}
        plain = text.replace("ã", "a")
        for pattern in FACTOR_PATTERNS:
            for match in pattern.finditer(plain):
                groups = match.groups()
                number, group = (groups[0], groups[1]) if groups[0][0].isdigit() else (groups[1], groups[0])
                category = "FEMININO" if group.lower() in {"mulheres", "feminino", "eleitoras"} else "MASCULINO"
                value = self._category("sexo", category)
                if value:
                    found.setdefault("sexo", {})[value] = float(number.replace(",", "."))
        return found

    # ------------------------------------------------------------------ período
    def _turn(self, q):
        if re.search(r" (SEGUNDO|2O|2A|2) TURNO ", q) or re.search(r" (NO|O|DO) SEGUNDO $", q) or has(q, "VE O SEGUNDO", "SEGUNDO TURNO"):
            return 2
        if re.search(r" (PRIMEIRO|1O|1A|1) TURNO ", q) or re.search(r" (NO|O|DO) PRIMEIRO $", q):
            return 1
        return None

    # ------------------------------------------------------------------ cadastro
    def _category(self, name, normalized):
        return self.category_lookup[name].get(normalized)

    def _demographics(self, q, norms, frame, issues):
        cats = {}
        words = set(norms)
        female = {"MULHER", "MULHERES", "FEMININO", "FEMININA", "FEMININOS", "FEMININAS", "ELEITORAS", "ELEITORA"}
        male = {"HOMEM", "HOMENS", "MASCULINO", "MASCULINA", "MASCULINOS", "MASCULINAS"}
        for n in norms:  # na ordem em que aparecem na pergunta
            if n in female or n in male:
                cats.setdefault("sexo", []).append(self._category("sexo", "FEMININO" if n in female else "MASCULINO"))
        if words & {"TRANSGENERO", "TRANSGENEROS", "TRANSGENERA", "TRANSGENERAS", "TRANS"}:
            cats.setdefault("identidade", []).append(self._category("identidade", "TRANSGENERO"))
        if words & {"CISGENERO", "CISGENEROS", "CISGENERA", "CISGENERAS", "CIS"}:
            cats.setdefault("identidade", []).append(self._category("identidade", "CISGENERO"))
        if re.search(r" PREFER\w* NAO (INFORMAR|DECLARAR|DIZER) ", q):
            cats.setdefault("identidade", []).append(self._category("identidade", "PREFERE NAO INFORMAR"))
        elif re.search(r" (NAO INFORMAD\w*|NAO DECLARAD\w*|SEM INFORMACAO) ", q):
            if "IDENTIDADE" in words:
                cats.setdefault("identidade", []).append(self._category("identidade", "NAO INFORMADO"))
            elif words & {"ESCOLARIDADE", "INSTRUCAO"}:
                cats.setdefault("escolaridade", []).append(self._category("escolaridade", "NAO INFORMADO"))
            elif words & {"SEXO", "GENERO"}:
                cats.setdefault("sexo", []).append(self._category("sexo", "NAO INFORMADO"))
            else:
                issues.append(("categoria_sem_dimensao", {}))
        education = [("ANALFABET", "ANALFABETO"), ("LE E ESCREVE", "LE E ESCREVE"), ("LEEM E ESCREVEM", "LE E ESCREVE"), ("LER E ESCREVER", "LE E ESCREVE"),
                     ("FUNDAMENTAL COMPLETO", "ENSINO FUNDAMENTAL COMPLETO"), ("FUNDAMENTAL INCOMPLETO", "ENSINO FUNDAMENTAL INCOMPLETO"),
                     ("MEDIO COMPLETO", "ENSINO MEDIO COMPLETO"), ("MEDIO INCOMPLETO", "ENSINO MEDIO INCOMPLETO"),
                     ("SUPERIOR COMPLETO", "SUPERIOR COMPLETO"), ("SUPERIOR INCOMPLETO", "SUPERIOR INCOMPLETO")]
        for phrase, category in education:
            if f" {phrase}" in q and self._category("escolaridade", category):
                cats.setdefault("escolaridade", []).append(self._category("escolaridade", category))
        if "escolaridade" not in cats:
            for level, options in [("SUPERIOR", ["SUPERIOR COMPLETO", "SUPERIOR INCOMPLETO"]), ("MEDIO", ["ENSINO MEDIO COMPLETO", "ENSINO MEDIO INCOMPLETO"]),
                                   ("FUNDAMENTAL", ["ENSINO FUNDAMENTAL COMPLETO", "ENSINO FUNDAMENTAL INCOMPLETO"])]:
                if re.search(rf" (ENSINO|NIVEL|FORMACAO|COM|CURSO) {level} ", q) or (level == "SUPERIOR" and has(q, "FACULDADE", "DIPLOMA", "GRADUADOS", "DIPLOMADOS")):
                    issues.append(("escolaridade_ambigua", {"options": [self._category("escolaridade", o) for o in options]}))
                    break
        ages = self._ages(q, issues)
        if ages:
            cats["idade"] = ages
        frame.categories = {k: tuple(dict.fromkeys(v for v in values if v)) for k, values in cats.items() if any(values)}
        if "IDENTIDADE" in words:
            frame.dimension = "identidade"
        elif words & {"IDADE", "IDADES", "ETARIA", "ETARIAS", "ETARIO", "ETARIOS"}:
            frame.dimension = "idade"
        elif words & {"ESCOLARIDADE", "INSTRUCAO", "EDUCACAO", "ESCOLAR", "ESTUDO"}:
            frame.dimension = "escolaridade"
        elif words & {"SEXO", "GENERO", "SEXOS", "GENEROS"}:
            frame.dimension = "sexo"
        elif len(frame.categories) == 1:
            frame.dimension = next(iter(frame.categories))
        frame.detail["unavailable_dimension"] = next((label for phrase, label in UNAVAILABLE_DIMENSIONS.items() if has(q, phrase)), "")
        if not frame.detail["unavailable_dimension"] and re.search(r" (ELEITORES|PESSOAS|EVANGELIC\w*) BRANCOS ", q):
            frame.detail["unavailable_dimension"] = "raça/cor"
        frame.detail["vague_age"] = has(q, *VAGUE_AGES)

    def _ages(self, q, issues):
        ranges = []
        for match in re.finditer(r" (\d{2,3}) (?:ANOS )?OU MAIS | A PARTIR D[EO]S? (\d{2,3}) ", q):
            ranges.append((int(match.group(1) or match.group(2)), 200))
        for match in re.finditer(r" (?:MAIS DE|ACIMA DE|ACIMA DOS|MAIORES DE) (\d{2,3}) ANOS ", q):
            ranges.append((int(match.group(1)) + 1, 200))
        for match in re.finditer(r" (?:MENOS DE|ABAIXO DE|ABAIXO DOS|MENORES DE) (\d{2,3}) ANOS ", q):
            ranges.append((16, int(match.group(1)) - 1))
        for match in re.finditer(r" ATE (\d{2,3}) ANOS ", q):
            ranges.append((16, int(match.group(1))))
        for match in re.finditer(r" (?:DE|DOS|ENTRE)? ?(\d{2,3}) (?:A|E|AOS) (\d{2,3}) ANOS ", q):
            a, b = int(match.group(1)), int(match.group(2))
            if " E " in match.group(0) and " ENTRE " not in match.group(0) and b - a > 0:
                ranges.extend([(a, a), (b, b)])
            else:
                ranges.append((min(a, b), max(a, b)))
        if not ranges:
            for match in re.finditer(r" (\d{2,3}) ANOS ", q):
                ranges.append((int(match.group(1)), int(match.group(1))))
        bands = []
        for lo, hi in dict.fromkeys(ranges):
            chosen = self.age_bands_for(lo, hi, issues)
            if not chosen:
                return []
            bands.extend(chosen)
        return bands

    def age_bands_for(self, lo, hi, issues):
        """Faixas oficiais que cobrem exatamente [lo, hi]; senão registra o desalinhamento."""
        lo = max(lo, 16)
        chosen = sorted((b for b, (l, h) in self.age_bands.items() if l >= lo and h <= hi), key=lambda b: self.age_bands[b][0])
        covered_lo = min((self.age_bands[b][0] for b in chosen), default=None)
        covered_hi = max((self.age_bands[b][1] for b in chosen), default=None)
        contiguous = all(self.age_bands[chosen[k + 1]][0] == self.age_bands[chosen[k]][1] + 1 for k in range(len(chosen) - 1))
        if not chosen or covered_lo != lo or covered_hi != min(hi, 200) or not contiguous:
            overlap = sorted((b for b, (l, h) in self.age_bands.items() if h >= lo and l <= hi), key=lambda b: self.age_bands[b][0])
            issues.append(("faixa_desalinhada", {"range": (lo, hi), "options": overlap[:6]}))
            return []
        return chosen

    # ------------------------------------------------------------------ intenção
    def _intent(self, q, norms, frame, state, second_round_question):
        words = set(norms)
        f = frame
        has_candidate = bool(f.candidates) or f.candidate_ref in {"foco", "par", "vencedor"} or bool(f.detail.get("person_mentioned"))
        vote = bool(words & VOTE_WORDS)
        eligible = has(q, *ELIGIBLE)
        vote_choice = (bool(words & VOTE_VERBS) and not eligible) or bool(re.search(r" (ELEITORES|ELEITORADO|ELEITORAS|PUBLICO|BASE) (DO|DA|DE) ", q) and has_candidate) \
            or has(q, "ELEITORES DE DETERMINADO", "ELEITORES DO CANDIDATO", "ELEITORES DE CADA", "QUEM VOTOU") \
            or bool(re.search(r" VOTOS (FEMININO|MASCULINO|JOVEM|EVANGELICO|FEMININOS|MASCULINOS|DAS MULHERES|DOS HOMENS|DOS JOVENS) ", q)) \
            or (has(q, "ENTRE AS", "ENTRE OS") and (has(q, *WIN_PHRASES) or vote))
        group = bool(f.categories) or bool(words & GROUP_WORDS) or bool(f.detail.get("unavailable_dimension")) or has(q, "DISTRIBUICAO", "PERFIL", "COMPOSICAO")
        candidate_choice = has_candidate or has(q, "EM QUEM", "QUAL CANDIDATO", "QUE CANDIDATO", "QUAL CANDIDATURA", "MAIS VOTADO",
                                                 "DETERMINADO CANDIDATO", "CADA CANDIDATO", "QUAL SEXO VOTOU", "CANDIDATO")

        def limitation(reason, **detail):
            f.intent, f.reason = "limitacao", reason
            f.detail.update(detail)

        stripped = " ".join(norms)
        if stripped in GREETINGS:
            f.intent = "saudacao"
            return
        if stripped in THANKS or (words <= THANKS | {"MUITO", "AJUDOU"} and words & THANKS):
            f.intent = "agradecimento"
            return
        if has(q, *HELP_PHRASES) and not (has_candidate or f.territories):
            f.intent = "ajuda"
            return
        if has(q, *OPINION_PHRASES) or has(q, *PREDICTION_PHRASES) or has(q, *CAUSAL_PHRASES):
            f.intent = "fora_escopo"
            return
        if words & OTHER_OFFICE:
            return limitation("outro_cargo")

        # Simulação hipotética: só com pedido explícito, e nunca quando se pergunta pelo voto real.
        if (words & SIMULATION_WORDS or has(q, "MESMA SIMULACAO", "DISTRIBUICAO HIPOTETICA")) and not has(q, *REALITY_PHRASES):
            f.intent = "simulacao"
            f.dimensions = [name for name, cues in sorted(DIMENSION_WORDS, key=lambda item: min((norms.index(w) for w in item[1] if w in norms), default=999))
                            if words & cues][:2]
            f.categories = {}  # a simulação usa a composição completa do eleitorado do território
            f.followup = f.followup or has(q, "MESMA SIMULACAO", "MESMO CENARIO", "A MESMA", "O MESMO")
            return

        # Horários das urnas: os logs não revelam candidaturas.
        hour = re.search(r" (\d{1,2}) ?H(\d{2})? | (?:DEPOIS|APOS|ANTES|ATE|A PARTIR) (?:DAS|AS|DA|A|DE)? ?(\d{1,2}) ", q)
        timing = bool(words & TIME_WORDS) or has(q, "ULTIMO VOTO", "FAIXA HORARIA", "FAIXAS HORARIAS", "POR HORA") or \
            bool(hour and (words & {"VOTOS", "URNAS", "VOTO", "VOTARAM", "VOTOU", "COMPUTADOS", "ELEITORES", "SECOES"}))
        if timing and not has(q, "HORARIO DE VERAO") and not (f.detail.get("unavailable_dimension")):
            if has_candidate or has(q, "EM QUEM", "QUAL CANDIDATO", "PARA QUEM"):
                return limitation("horario_por_candidatura")
            f.intent = "horarios"
            if hour:
                f.detail["hour"] = int(hour.group(1) or hour.group(3))
                f.detail["minute"] = int(hour.group(2) or 0)
            ranking_place = re.search(r" (QUAIS|QUAL|QUE|ONDE) .*(ESTADOS|ESTADO|UFS|MUNICIPIOS|MUNICIPIO|CIDADES|CIDADE) ", q) and (words & {"MAIS", "MAIOR", "MAIORES"})
            if ranking_place:
                f.metric = "ranking"
                f.level = "uf" if words & {"ESTADOS", "ESTADO", "UFS"} and not words & {"MUNICIPIOS", "MUNICIPIO", "CIDADES", "CIDADE"} else "municipio"
                f.order = "pct" if words & PCT_WORDS or has(q, "PROPORCAO") else "abs"
                f.limit = self._limit(norms) or (1 if words & {"ESTADO", "MUNICIPIO", "CIDADE", "QUAL"} and not words & {"QUAIS"} else 5)
            elif has(q, "ULTIMO VOTO"):
                f.metric = "ultimo_voto"
            elif has(q, "FAIXA HORARIA", "FAIXAS HORARIAS", "POR HORA", "HORA A HORA", "CADA HORA") or (words & {"DISTRIBUICAO"} and words & {"HORA", "HORAS", "HORARIO", "HORARIOS"}) \
                    or re.search(r" ENTRE (AS )?\d{1,2} ?H? E (AS )?\d{1,2} ?H? ", q):
                f.metric = "faixas"
            elif re.search(r" (QUAIS|QUAL) (SAO |FORAM )?(AS )?(URNAS|SECOES|SECAO|URNA) ", q):
                f.metric, f.limit = "urnas_tardias", self._limit(norms) or 10
            elif words & {"ESTENDIDA", "ESTENDIDAS", "TARDIA", "TARDIAS", "PRORROGADA", "PRORROGADAS"} or has(q, "ENCERRAMENTO TARDIO", "FECHARAM DEPOIS", "ENCERRARAM DEPOIS", "QUANTAS URNAS"):
                f.metric = "estendidas"
            elif hour and words & {"VOTOS", "VOTO", "VOTARAM", "COMPUTADOS"}:
                f.metric = "votos_apos_17h" if f.detail["hour"] == 17 and not f.detail["minute"] else "votos_apos_hora"
            else:
                f.metric = "resumo"
            return

        # Comparação entre turnos do mesmo território.
        if has(q, *TURNS_PHRASES):
            f.intent, f.turn = "comparar_turnos", None
            return
        if group and vote_choice and candidate_choice:
            unavailable = f.detail.get("unavailable_dimension")
            label = ARTICLED.get(unavailable, unavailable) or DIMENSION_LABEL.get(f.dimension or next(iter(f.categories), ""), "")
            if not label:
                label = "a idade" if f.detail.get("vague_age") else ("o sexo" if words & {"MULHER", "MULHERES", "HOMEM", "HOMENS"} else "o perfil")
            return limitation("inferencia_demografica", attribute=label)
        if f.detail.get("unavailable_dimension"):
            return limitation("dimensao_indisponivel", attribute=f.detail["unavailable_dimension"])
        if has(q, *BLANK_PHRASES):
            return limitation("brancos_nulos")
        people_voted = has(q, "PESSOAS VOTARAM", "QUANTOS VOTARAM", "QUANTAS VOTARAM", "GENTE VOTOU", "ELEITORES VOTARAM", "MULHERES VOTARAM", "HOMENS VOTARAM")
        if has(q, *TURNOUT_PHRASES) or (people_voted and not has_candidate) or (group and vote_choice):
            return limitation("comparecimento")
        if has(q, *HISTORY_PHRASES):
            return limitation("serie_historica")
        if has(q, *REGION_PHRASES) and not any(t.kind == "regiao" for t in f.territories):
            return limitation("regiao_nao_definida")
        if (words & PCT_WORDS) and (words & ELECTORATE_WORDS) and vote_choice and has_candidate:
            f.intent, f.metric, f.note = "votos", "percentual", "bases_incompativeis"
            return
        if has(q, *INJECTION_PHRASES) and not (has_candidate or f.territories or vote):
            return limitation("injecao")

        # Candidaturas (informação cadastral do pleito)
        if second_round_question:
            f.intent, f.metric, f.turn = "candidaturas", "segundo_turno", None
            return
        if re.search(r" (QUAL|QUE) (E |FOI )?(O )?(PARTIDO|NUMERO|LEGENDA|SIGLA|NOME COMPLETO|NOME) ", q) or has(q, "NOME COMPLETO"):
            f.intent = "candidaturas"
            f.metric = "partido" if has(q, "PARTIDO", "LEGENDA", "SIGLA") else "numero" if "NUMERO" in words else "nome"
            return
        if words & CANDIDACY_WORDS and not vote and not has(q, *WIN_PHRASES) and not f.territories and not f.candidates:
            f.intent, f.metric = "candidaturas", ("contagem" if words & COUNT_WORDS else "lista")
            return

        ranked_noun = next((n for n in norms if n in {"CIDADE", "CIDADES", "MUNICIPIO", "MUNICIPIOS", "ESTADO", "ESTADOS", "UF", "UFS", "LUGARES", "LOCAIS"}), "")
        superlative = bool(words & {"MAIS", "MAIOR", "MAIORES", "MENOS", "MENOR", "MENORES", "MELHOR", "PIOR", "MELHORES", "PIORES"})
        ordinal_noun = re.search(r" (PRIMEIR|SEGUND|TERCEIR|QUART|QUINT|SEXT|SETIM|OITAV|NON|DECIM|ULTIM|PENULTIM)[OA] (CIDADE|MUNICIPIO|ESTADO|UF) | (\d{1,2})[OA] (CIDADE|MUNICIPIO|ESTADO) ", q)
        ranking = has(q, "RANKING", "TOP") or bool(ordinal_noun) or (bool(re.search(r" (QUAL|QUAIS|ONDE|EM QUE|EM QUAL|EM QUAIS|QUE) ", q)) and ranked_noun and superlative) \
            or bool(re.search(r" (CIDADES|MUNICIPIOS|ESTADOS) (QUE|COM|ONDE|DE) (MAIS|MAIOR|MENOS|MENOR)", q)) or bool(re.search(r" (MAIORES|MENORES) (CIDADES|MUNICIPIOS|ESTADOS|ELEITORADOS)", q))
        wins = bool(re.search(r" (EM )?QUANT[OA]S (CIDADES|MUNICIPIOS|ESTADOS|UFS) ", q)) and has(q, "GANHOU", "VENCEU", "VENCEDOR", "MAIS VOTADO", "MAIS VOTADA", "LIDEROU", "GANHOU EM", "FICOU EM PRIMEIRO")
        if wins:
            f.intent, f.level = "vitorias", ("uf" if has(q, "ESTADOS", "UFS") else "municipio")
            return
        if ranking and ranked_noun:
            f.intent = "ranking"
            f.level = "uf" if ranked_noun in {"ESTADO", "ESTADOS", "UF", "UFS"} and not any(n in norms for n in ["CIDADE", "CIDADES", "MUNICIPIO", "MUNICIPIOS"]) else "municipio"
            f.order = "asc" if words & {"MENOS", "MENOR", "MENORES", "PIOR", "PIORES"} else "desc"
            number = self._limit(norms)
            if ordinal_noun:
                word = (ordinal_noun.group(1) or "") + "O"
                f.position = int(ordinal_noun.group(3)) if ordinal_noun.group(3) else ORDINALS.get(word, ORDINALS.get(word[:-1] + "A", 1))
            elif number:
                f.limit = number
            elif ranked_noun.endswith("S") or ranked_noun == "UFS":
                f.limit = 5
            else:
                f.limit = 1
            if words & PCT_WORDS:
                f.metric = "percentual_eleitores" if (words & ELECTORATE_WORDS and not has_candidate) else "percentual_candidato"
            elif (words & ELECTORATE_WORDS or f.categories) and not has_candidate and not vote:
                f.metric = "eleitores"
            elif has_candidate:
                f.metric = "votos_candidato"
                if has(q, "MAIS FORTE", "MELHOR DESEMPENHO", "PIOR DESEMPENHO", "MAIS FRACO", "FOI MELHOR", "FOI PIOR", "MAIS FORTES"):
                    f.metric = ""
                    f.reason = "metrica_ranking"
            else:
                f.metric = "votos_validos"
            return

        countable = f.categories or f.detail.get("vague_age")
        profile_request = has(q, *DISTRIBUTION_PHRASES) or bool(f.dimension)
        if (words & ELECTORATE_WORDS or profile_request or (countable and not has_candidate and (words & COUNT_WORDS or has(q, "HA", "EXISTEM", "TEM", "TEEM")))) and not vote and not has_candidate:
            if has(q, "QUANTOS MUNICIPIOS", "QUANTAS CIDADES") and not words & ELECTORATE_WORDS:
                f.intent = "contar_municipios"
                return
            several = any(len(v) > 1 for k, v in f.categories.items() if k != "idade")  # "homens e mulheres"
            if has(q, *DISTRIBUTION_PHRASES) or (f.dimension and not f.categories) or several:
                f.intent = "distribuicao"
                if not f.dimension:
                    f.reason = "dimensao_perfil"
            else:
                f.intent = "eleitorado"
            if f.detail.get("vague_age") and "idade" not in f.categories:
                f.intent, f.reason = "problema", "faixa_indefinida"
            if words & PCT_WORDS:
                f.metric = "percentual"
            return
        if has(q, "QUANTOS MUNICIPIOS", "QUANTAS CIDADES", "NUMERO DE MUNICIPIOS", "NUMERO DE CIDADES") and not vote and not has_candidate:
            f.intent = "contar_municipios"
            return

        pair = len(f.candidates) >= 2 or f.candidate_ref == "par"
        compare = bool(words & COMPARE_WORDS) or (" OU " in q and len(f.candidates) >= 2)
        diff = has(q, *DIFF_PHRASES)
        win = has(q, *WIN_PHRASES)
        cue = vote or win or compare or diff or ranking or bool(words & (PCT_WORDS | ELECTORATE_WORDS | COUNT_WORDS)) or has(q, *PERFORMANCE_PHRASES, *RESULT_PHRASES, *LOSE_PHRASES)
        if (f.followup or f.correction) and not cue and state.intent:
            # "E Bolsonaro?", "E em Americana?", "Na verdade, Campinas": mesma consulta, outra dimensão.
            f.intent = "continuar"
            return
        if win and not f.candidates and not f.candidate_ref and state.intent == "comparar_candidatos" and len(state.candidates) >= 2 and len(norms) <= 6:
            f.intent, f.metric, f.candidate_ref = "comparar_candidatos", "mais_votos", "par"
            return
        if diff:
            f.intent = "comparar_candidatos"
            f.metric = "variacao" if has(q, *RELATIVE_PHRASES) else "diferenca_pp" if (has(q, *PP_PHRASES) or (words & PCT_WORDS)) else \
                "diferenca_votos" if has(q, "VOTOS A MAIS", "VOTOS A MENOS", "DIFERENCA DE VOTOS", "EM VOTOS", "QUANTOS VOTOS") else "diferenca"
            if f.candidate_ref in {"top2", "vencedor"} or (not pair and has(q, "ENTRE O PRIMEIRO", "DOIS PRIMEIROS", "1O E 2O", "PRIMEIRO E O SEGUNDO")):
                f.candidate_ref = "top2"
            return
        if len(f.territories) >= 2 or (compare and f.place_ref == "par") or (compare and len(f.territories) == 1 and not f.candidates and state.territories):
            f.intent = "comparar_territorios"
            if words & PCT_WORDS:
                f.metric = "percentual"
            elif words & ELECTORATE_WORDS:
                f.metric = "eleitores"
            elif has(q, *RESULT_PHRASES):
                f.metric = "geral"
            return
        if pair and (compare or win or has(q, "QUEM TEVE MAIS", "QUEM RECEBEU MAIS", "QUEM FOI MELHOR")):
            f.intent, f.metric = "comparar_candidatos", "mais_votos"
            return
        if compare and not f.candidates and not f.territories:
            f.intent, f.metric = "comparar", ""
            return
        position = re.search(r" (?:FICOU EM|EM|O|A) (SEGUND|TERCEIR|QUART|QUINT|ULTIM|PENULTIM)[OA] (?:LUGAR|COLOCAD[OA]|MAIS VOTAD[OA])? ?", q)
        if position and not re.search(r" (SEGUND|TERCEIR|QUART|QUINT)[OA] TURNO ", q) and (has(q, "LUGAR", "COLOCADO", "COLOCADA", "MAIS VOTADO", "MAIS VOTADA", "FICOU")):
            f.intent = "vencedor"
            f.position = ORDINALS.get(position.group(1) + "O", 1)
            return
        if has(q, *LOSE_PHRASES) and not has_candidate:
            f.intent, f.position = "vencedor", -1
            return
        if win and (not has_candidate or len(f.candidates) == 1 and has(q, "GANHOU", "VENCEU", "VENCE", "GANHA", "LIDEROU")):
            f.intent, f.position = "vencedor", 1
            f.metric = "votos" if vote else ""
            return
        if has_candidate or f.candidate_ref == "top2":
            f.intent = "votos"
            asserted_pct = any(kind == "pct" for _, kind, _ in f.asserted)
            f.metric = "percentual" if words & PCT_WORDS or asserted_pct else "desempenho" if has(q, *PERFORMANCE_PHRASES) else "votos"
            if len(f.candidates) >= 2 and not f.metric == "votos":
                f.intent = "comparar_candidatos"
            return
        if f.place_ref == "par" and compare:
            f.intent = "comparar_territorios"
            return
        if has(q, *RESULT_PHRASES) or ((vote or has(q, "VALIDOS")) and (f.territories or f.place_ref)):
            f.intent = "resultado"
            f.metric = "total_validos" if (has(q, "VOTOS VALIDOS", "TOTAL DE VOTOS", "QUANTOS VOTOS", "SOMA DOS VOTOS", "VOTOS TOTAIS") and not has(q, *RESULT_PHRASES)) else ""
            return
        metric_only = next((m for p, m in METRIC_ONLY.items() if has(q, p)), "")
        if metric_only and (f.followup or len(norms) <= 6 or has(q, "SO O", "SO A", "APENAS O", "MOSTRA", "MOSTRE", "PASSA", "ME DA", "ME DE")):
            f.intent, f.metric = "continuar", metric_only
            return
        if words & PCT_WORDS or has(q, "QUAL FOI O PERCENTUAL", "QUAL O PERCENTUAL"):
            f.intent, f.metric = "continuar", "percentual"
            return
        if (f.followup or f.correction or f.turn or f.year) and state.intent:
            f.intent = "continuar"
            return
        if f.territories:
            f.intent = "resultado"
            return
        if vote:
            f.intent = "resultado"
            return
        f.intent = "desconhecido"

    def _limit(self, norms):
        for i, n in enumerate(norms):
            value = int(n) if n.isdigit() and len(n) <= 2 else NUMBER_WORDS.get(n)
            if not value or value < 2 and n not in {"UM", "UMA"}:
                continue
            nxt = norms[i + 1] if i + 1 < len(norms) else ""
            prev = norms[i - 1] if i else ""
            if nxt in {"CIDADES", "MUNICIPIOS", "ESTADOS", "UFS", "PRIMEIRAS", "PRIMEIROS", "MAIORES", "MENORES", "MAIS", "LUGARES"} or prev in {"TOP", "OS", "AS"}:
                return min(value, 50)
        return None
