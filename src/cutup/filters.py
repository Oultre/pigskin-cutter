"""Filter builder over the EAV tag store.

Down, distance, formation, personnel, result — every filterable field is a tag
(PLAN §4 stores them EAV so any Hudl column works). A predicate therefore
compiles to an ``EXISTS`` against ``tags``. Play-level gates (``source``,
``confidence``) compile against ``plays`` directly.

Phase 1 syntax is repeated ``--where "key OP value"`` predicates, ANDed together.
A real expression language (OR, parentheses) is later work; this covers the
Phase 1 export path without a parser to maintain.

Supported operators:
    key = value            text equality
    key != value           text inequality
    key >= n   >   <   <=   numeric comparison (value cast to REAL)
    key in (a, b, c)        membership
    key exists              the tag is present at all
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import FilterError

_NUMERIC_OPS = {">=", "<=", ">", "<"}
# Longer operators first so ">=" is not read as ">".
_OP_PATTERN = re.compile(r"^(?P<key>[^<>=!]+?)\s*(?P<op>>=|<=|!=|=|>|<)\s*(?P<val>.+)$")
_IN_PATTERN = re.compile(r"^(?P<key>.+?)\s+in\s+\((?P<vals>.*)\)\s*$", re.IGNORECASE)
_EXISTS_PATTERN = re.compile(r"^(?P<key>.+?)\s+exists\s*$", re.IGNORECASE)


@dataclass
class Predicate:
    key: str
    op: str            # one of: = != >= <= > < in exists
    values: list[str]  # 1 value for most ops, N for "in", 0 for "exists"


def parse_where(expr: str) -> Predicate:
    text = expr.strip()
    if not text:
        raise FilterError("Empty --where expression.")

    m = _EXISTS_PATTERN.match(text)
    if m:
        return Predicate(key=m.group("key").strip(), op="exists", values=[])

    m = _IN_PATTERN.match(text)
    if m:
        raw = m.group("vals")
        values = [v.strip().strip("'\"") for v in raw.split(",") if v.strip()]
        if not values:
            raise FilterError(f"`in` needs at least one value: {expr!r}")
        return Predicate(key=m.group("key").strip(), op="in", values=values)

    m = _OP_PATTERN.match(text)
    if m:
        key = m.group("key").strip()
        op = m.group("op")
        val = m.group("val").strip().strip("'\"")
        if not key:
            raise FilterError(f"Missing key in --where {expr!r}")
        if op in _NUMERIC_OPS:
            try:
                float(val)
            except ValueError as exc:
                raise FilterError(
                    f"Operator {op!r} needs a number, got {val!r} in {expr!r}"
                ) from exc
        return Predicate(key=key, op=op, values=[val])

    raise FilterError(
        f"Could not parse --where {expr!r}. "
        "Use `key=value`, `key>=6`, `key in (a,b)`, or `key exists`."
    )


def _predicate_sql(pred: Predicate, min_confidence: float | None) -> tuple[str, list]:
    """Compile one predicate to an EXISTS clause and its bound params."""
    conf = ""
    conf_params: list = []
    if min_confidence is not None:
        conf = " AND t.confidence >= ?"
        conf_params = [min_confidence]

    base = "EXISTS (SELECT 1 FROM tags t WHERE t.play_id = plays.id AND t.key = ?{extra}{conf})"

    if pred.op == "exists":
        sql = base.format(extra="", conf=conf)
        return sql, [pred.key, *conf_params]

    if pred.op == "in":
        placeholders = ", ".join("?" for _ in pred.values)
        sql = base.format(extra=f" AND t.value IN ({placeholders})", conf=conf)
        return sql, [pred.key, *pred.values, *conf_params]

    if pred.op in _NUMERIC_OPS:
        sql = base.format(extra=f" AND CAST(t.value AS REAL) {pred.op} ?", conf=conf)
        return sql, [pred.key, float(pred.values[0]), *conf_params]

    # text = / !=
    sql = base.format(extra=f" AND t.value {pred.op} ?", conf=conf)
    return sql, [pred.key, pred.values[0], *conf_params]


def build_query(
    predicates: list[Predicate],
    *,
    source: str | None = None,
    min_confidence: float | None = None,
    confirmed_only: bool = False,
) -> tuple[str, list]:
    """Build the SELECT that returns matching plays joined to their film.

    ``min_confidence`` gates both the play's own confidence and, for tag
    predicates, the confidence of the matched tag — an unconfirmed OCR tag should
    not satisfy a filter that asked for confirmed data (PLAN §2C.5).
    """
    from .models import CONFIRMED_SOURCES

    clauses: list[str] = []
    params: list = []

    if source is not None:
        clauses.append("plays.source = ?")
        params.append(source)

    if min_confidence is not None:
        clauses.append("plays.confidence >= ?")
        params.append(min_confidence)

    if confirmed_only:
        placeholders = ", ".join("?" for _ in CONFIRMED_SOURCES)
        clauses.append(f"plays.source IN ({placeholders})")
        params.extend(CONFIRMED_SOURCES)

    for pred in predicates:
        sql, p = _predicate_sql(pred, min_confidence)
        clauses.append(sql)
        params.extend(p)

    where = " AND ".join(clauses) if clauses else "1 = 1"
    query = (
        "SELECT plays.*, films.path AS film_path, films.label AS film_label, "
        "films.source_type AS film_source_type "
        "FROM plays JOIN films ON films.id = plays.film_id "
        f"WHERE {where} "
        "ORDER BY plays.film_id, plays.play_no, plays.t_start"
    )
    return query, params
