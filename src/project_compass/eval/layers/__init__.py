"""The evaluation layers.

The layers are ordered from cheapest and most structural to most expensive and
most behavioural, so a run can stop early without losing the measurements
that guard the product's hard rules.

* ``L1`` structure — ingestion, ownership and the two layers of truth.
* ``L2`` extraction — fact precision, recall and the extraction contract.
* ``L3`` handoff — retrieval reachability and answer quality.
* ``L4`` contract — call-chain tracing and index freshness.
* ``L5`` adversarial — whether the extraction gate resists attacks.
"""

from .base import HIGHER, LOWER, LayerResult, Metric, ratio
from .l1_structure import run_structure
from .l2_extraction import extract_and_validate, run_extraction
from .l3_handoff import AgentAnswerer, ProductAnswerer, run_handoff
from .l4_contract import ContractCase, load_contract_cases, run_contract
from .l5_adversarial import (
    AdversarialCase,
    load_adversarial_cases,
    run_adversarial,
)

__all__ = [
    "HIGHER",
    "LOWER",
    "AdversarialCase",
    "AgentAnswerer",
    "ContractCase",
    "LayerResult",
    "Metric",
    "ProductAnswerer",
    "extract_and_validate",
    "load_adversarial_cases",
    "load_contract_cases",
    "ratio",
    "run_adversarial",
    "run_contract",
    "run_extraction",
    "run_handoff",
    "run_structure",
]
