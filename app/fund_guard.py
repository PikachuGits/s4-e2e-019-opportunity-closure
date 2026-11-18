"""Rejects any payment / collection field in statistics-only deal records.

Acceptance criterion 2 says the deal-record endpoint must not accept any
收付款（payment/collection）field, and ``amount_paid`` / ``payment_account``
must produce 422. The check walks the whole JSON tree (objects, arrays,
nested objects) so a field hidden one level deeper cannot slip through.
"""

from __future__ import annotations

from typing import Any

# Normalised (lowercase, non-alphanumeric stripped) key names that are
# considered payment / collection fields.
FUND_FIELD_TOKENS: frozenset[str] = frozenset(
    {
        "amountpaid",
        "paidamount",
        "paymentamount",
        "paymentaccount",
        "payaccount",
        "paymentmethodaccount",
        "receivedamount",
        "receiveamount",
        "receivableamount",
        "receivingaccount",
        "receiveaccount",
        "receivingamount",
        "bankaccount",
        "bankaccountno",
        "bankcardno",
        "accountname",
        "accountnumber",
        "payee",
        "payeename",
        "payer",
        "payername",
        "transferamount",
        "settlementamount",
        "fundamount",
        "currency",
        "amount",
        "unitprice",
        "price",
        "invoiceamount",
        "taxamount",
        "paidat",
        "paymentdate",
    }
)

DEAL_FORBIDDEN_FIELDS = sorted(FUND_FIELD_TOKENS)


def normalise_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def find_fund_fields(payload: Any, path: str = "$") -> list[str]:
    """Return dotted paths of every forbidden key found in ``payload``."""

    hits: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if normalise_key(str(key)) in FUND_FIELD_TOKENS:
                hits.append(child)
                # keep walking: a forbidden key may itself hold nested objects
            hits.extend(find_fund_fields(value, child))
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            hits.extend(find_fund_fields(value, f"{path}[{index}]"))
    return hits
