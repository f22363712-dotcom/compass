"""Shared size, count, and timeout bounds across Project Compass modules."""

from __future__ import annotations

#: Code graph identifier length limit (an edge ID combines two node IDs within MAX_NODE_ID=256).
MAX_ID = 110
MAX_NODES = 10000
MAX_EDGES = 20000

#: Derived context schema bounds.
MAX_SOURCE_REF = 2048
MAX_FINGERPRINT = 256
MAX_NODE_ID = 256
MAX_LABEL = 4096
MAX_SUMMARY = 16000

#: Dashboard topology rendering slice bounds.
MAX_DASHBOARD_VISIBLE_NODES = 200
MAX_DASHBOARD_VISIBLE_EDGES = 400

#: Extractive candidate and batch bounds.
MAX_CANDIDATES_PER_PAYLOAD = 24
MAX_FACT_QUOTE_CHARS = 1600
MAX_SUBJECT_KEY_CHARS = 160
MAX_EXTRACTION_BATCH_CHARS = 18000
MAX_SOURCE_CHARS = 12000

#: Eval benchmark builder & harness bounds.
MAX_ANCHORS_PER_ITEM = 8
DEFAULT_HARNESS_TIMEOUT_S = 300
