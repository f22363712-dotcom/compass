"""Evaluation benchmark for ProjectCompass.

The benchmark measures whether the product changes an outcome, not whether the
implementation matches its own specification. Every layer scores against
ground truth that was authored outside ProjectCompass.
"""

from .adapters import AdapterError, ConversationEntry, conversation_events, parse_sync_conversation
from .corpus import Corpus, CorpusError, Deidentifier, load_corpus, write_corpus
from .gold import GoldError, GoldFact, GoldQuestion, GoldSet

__all__ = [
    "AdapterError",
    "ConversationEntry",
    "Corpus",
    "CorpusError",
    "Deidentifier",
    "GoldError",
    "GoldFact",
    "GoldQuestion",
    "GoldSet",
    "conversation_events",
    "load_corpus",
    "parse_sync_conversation",
    "write_corpus",
]
