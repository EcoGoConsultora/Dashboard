from __future__ import annotations


DOLLAR_LINKED_SYMBOLS = ["D30A6", "TZV26", "D30S6", "TZV27", "TZV28"]
DOLLAR_LINKED_MARKET = "BCBA"
DOLLAR_LINKED_HISTORY_WINDOW = 30

DOLLAR_LINKED_SNAPSHOT_COLUMNS = [
    "date",
    "symbol",
    "price",
    "volume",
    "amount",
    "market",
    "source",
    "fetched_at",
]

DOLLAR_LINKED_HISTORY_COLUMNS = ["date", "symbol", "price", "volume"]
DOLLAR_LINKED_LATEST_COLUMNS = ["date", "symbol", "price", "volume", "amount"]

