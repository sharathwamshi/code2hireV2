"""Shared helpers: the server side of the table standard (search, filter, sort, paginate) and request parsing."""
from datetime import datetime

from flask import jsonify, request
from sqlalchemy import or_


def body():
    return request.get_json(silent=True) or {}


def ok(data=None, **extra):
    out = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(extra)
    return jsonify(out)


def err(msg, code=400):
    return jsonify({"error": msg}), code


def table(query, search_cols=(), sort_map=None, default_sort=None, serialize=None, filters=None):
    """Applies ?q=&sort=&dir=&page=&size= and returns the standard paged payload.

    filters: {param_name: callable(query, value) -> query}
    """
    args = request.args
    q = (args.get("q") or "").strip()
    if q and search_cols:
        like = f"%{q}%"
        query = query.filter(or_(*[c.ilike(like) for c in search_cols]))
    for name, fn in (filters or {}).items():
        v = args.get(name)
        if v not in (None, ""):
            query = fn(query, v)
    sort_map = sort_map or {}
    sort = args.get("sort") or default_sort
    direction = args.get("dir", "desc")
    if sort in sort_map:
        col = sort_map[sort]
        query = query.order_by(col.desc() if direction == "desc" else col.asc())
    try:
        page = max(1, int(args.get("page", 1)))
        size = min(100, max(5, int(args.get("size", 25))))
    except ValueError:
        page, size = 1, 25
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return jsonify({"items": [serialize(i) if serialize else i.to_dict() for i in items],
                    "total": total, "page": page, "size": size, "pages": max(1, (total + size - 1) // size)})


def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", ""))
    except ValueError:
        return None
