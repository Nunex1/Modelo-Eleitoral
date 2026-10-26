"""Representação estruturada da pergunta (Frame) e contexto temporário da conversa.

O contexto vive apenas no estado da sessão: entidades em foco, período e um
eventual esclarecimento pendente. Não guarda o texto das mensagens.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .data import Filters
from .entities import Territory


@dataclass
class Frame:
    """Interpretação de uma oração, antes de combinar com o contexto (camadas 1 e 2)."""
    intent: str                                   # ver INTENTS em interpreter.py
    candidates: list = field(default_factory=list)        # chaves de candidatura já resolvidas
    candidate_ref: str = ""                       # "" | foco | par | vencedor | top2
    territories: list = field(default_factory=list)       # territórios já resolvidos
    place_ref: str = ""                           # "" | foco | par
    year: int | None = None
    turn: int | None = None
    metric: str = ""
    dimension: str = ""
    categories: dict = field(default_factory=dict)
    limit: int | None = None
    position: int | None = None
    order: str = ""
    level: str = ""
    reason: str = ""                              # código de limitação ou de esclarecimento
    detail: dict = field(default_factory=dict)
    followup: bool = False
    correction: bool = False
    asserted: list = field(default_factory=list)  # números afirmados pelo usuário
    note: str = ""                                # observação obrigatória na resposta

    def summary(self):
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [], {}, False)}


@dataclass
class ConversationState:
    base: Filters = field(default_factory=Filters)    # filtros do painel na abertura da conversa
    period: tuple | None = None
    period_explicit: bool = False
    candidates: tuple = ()                            # candidaturas em foco
    recent: tuple = ()                                # mencionadas recentemente (mais recente por último)
    territories: tuple = ()                           # territórios em foco
    recent_places: tuple = ()
    scope: Territory | None = None                    # escopo do último ranking/contagem
    intent: str = ""
    metric: str = ""
    dimension: str = ""
    categories: dict = field(default_factory=dict)
    limit: int | None = None
    position: int | None = None
    order: str = ""
    level: str = ""
    leaders: tuple = ()                               # 1º e 2º do último resultado consultado
    pending: dict | None = None                       # esclarecimento aguardando resposta
    exchanges: int = 0

    @classmethod
    def from_filters(cls, filters):
        return cls(base=filters or Filters())

    def remember_candidates(self, keys):
        recent = tuple(k for k in self.recent if k not in keys) + tuple(keys)
        return replace(self, candidates=tuple(keys), recent=recent[-4:])

    def remember_places(self, places):
        recent = tuple(p for p in self.recent_places if p not in places) + tuple(places)
        return replace(self, territories=tuple(places), recent_places=recent[-4:])

    def summary(self):
        """Contexto estruturado (sem texto de mensagens) para o intérprete externo e auditoria."""
        return {"periodo": list(self.period) if self.period else None, "periodo_explicito": self.period_explicit,
                "candidaturas_em_foco": list(self.candidates), "candidaturas_recentes": list(self.recent),
                "territorios_em_foco": [t.label for t in self.territories], "territorios_recentes": [t.label for t in self.recent_places],
                "escopo_ranking": self.scope.label if self.scope else None, "ultima_intencao": self.intent, "ultima_metrica": self.metric,
                "dimensao": self.dimension, "categorias": {k: list(v) for k, v in self.categories.items()},
                "esclarecimento_pendente": (self.pending or {}).get("field"),
                "filtros_do_painel": {k: v for k, v in self.base.__dict__.items() if v not in ("", None)}}
