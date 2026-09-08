"""Match the 935 jurisdictions to a publisher + source URL.

Primary catalog: Municode ``/Clients/stateAbbr`` (covers most of this corpus).
eCode360 and American Legal have no comparable public catalog; unmatched
jurisdictions are left as publisher=null for a later pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any

from .common import looks_like_county, name_variants, normalize_name, polite_get_json, slugify_client_name


def library_url(state_abbr: str, client_name: str, product_name: str | None = None) -> str:
    st = (state_abbr or "").lower()
    slug = slugify_client_name(client_name)
    pub = slugify_client_name(product_name) if product_name else "code_of_ordinances"
    return f"https://library.municode.com/{st}/{slug}/codes/{pub}"


def clients_by_state(state_abbr: str, *, sleep: float = 0.4):
    url = f"https://api.municode.com/Clients/stateAbbr?stateAbbr={state_abbr.upper()}"
    data = polite_get_json(url, sleep=sleep)
    return data if isinstance(data, list) else []


def load_cached_clients(cache_dir: str, state: str):
    path = os.path.join(cache_dir, f"municode_clients_{state.upper()}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_cached_clients(cache_dir: str, state: str, clients) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"municode_clients_{state.upper()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clients, f)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JURIS = os.path.join(ROOT, "jurisdictions.json")
DEFAULT_OUT = os.path.join(ROOT, "publisher_map.json")
DEFAULT_CACHE = os.path.join(ROOT, "cache")


def _client_state(c: dict[str, Any]) -> str:
    st = c.get("State") or {}
    return (st.get("StateAbbreviation") or "").upper()


def _index_clients(clients: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    idx: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in clients:
        for v in name_variants(c.get("ClientName") or ""):
            idx[v].append(c)
    return idx


def _unique(cs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {}
    for c in cs:
        seen[c.get("ClientID")] = c
    return list(seen.values())


def _is_county_client(c: dict[str, Any]) -> bool:
    name = normalize_name(c.get("ClientName") or "")
    if "county" in name or "parish" in name:
        return True
    # ClassificationId 4 observed for Buncombe County; 6 for small cities.
    return str(c.get("ClassificationId")) == "4"


def score_match(place_name: str, client: dict[str, Any]) -> tuple[float, str]:
    pv = name_variants(place_name)
    cv = name_variants(client.get("ClientName") or "")
    inter = pv & cv
    county_place = looks_like_county(place_name)
    county_client = _is_county_client(client)
    pn = normalize_name(place_name)
    cn = normalize_name(client.get("ClientName") or "")

    if pn == cn:
        return 0.99, "exact"
    if county_place != county_client and ("city of" in pn or "town of" in pn or "village of" in pn):
        # City/town/village should not match a county of the same name.
        if not inter:
            return 0.0, "type-mismatch"
    if pn in cv or cn in pv:
        if county_place == county_client:
            return 0.95, "variant-exact"
        return 0.8, "variant-type-diff"
    if inter:
        core = max(inter, key=len)
        if len(core) >= 4:
            if county_place == county_client:
                return 0.9, "core-overlap"
            return 0.7, "core-overlap-type-diff"
    # unique containment — extra tokens may only be government words
    gov = {
        "county", "parish", "government", "unified", "consolidated",
        "city", "town", "village", "borough", "of", "the", "co",
    }
    for p in pv:
        for c in cv:
            if len(p) < 5:
                continue
            if p == c:
                return 0.9, "core-equal"
            if p.startswith(c + " ") or c.startswith(p + " "):
                longer, shorter = (c, p) if len(c) > len(p) else (p, c)
                extra = set(longer.split()) - set(shorter.split())
                if extra and extra <= gov:
                    return 0.85, "prefix-gov"
    # County/parish contained in a combined name:
    # "East Baton Rouge" ⊂ "Baton Rouge, East Baton Rouge Parish"
    if looks_like_county(place_name) and not _is_township(client):
        for p in pv:
            if (p.endswith(" parish") or p.endswith(" county")) and len(p) >= 10:
                if cn.endswith(p) or cn.endswith(" " + p):
                    return 0.88, "phrase-in-client"
    return 0.0, "none"


def _phrase_in(phrase: str, hay: str) -> bool:
    import re
    if not phrase or len(phrase) < 6:
        return False
    return re.search(r"(?:^| )" + re.escape(phrase) + r"(?:$| )", hay) is not None


def _is_township(c: dict[str, Any]) -> bool:
    n = normalize_name(c.get("ClientName") or "")
    return "township" in n.split() or "charter township" in n


def match_one(
    place_name: str,
    state_code: str,
    idx: dict[str, list[dict[str, Any]]],
    all_clients: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float, str]:
    candidates: list[dict[str, Any]] = []
    for v in name_variants(place_name):
        candidates.extend(idx.get(v) or [])
    # Phrase containment: "East Baton Rouge" in "Baton Rouge, East Baton Rouge Parish"
    pv = name_variants(place_name)
    for c in all_clients:
        cn = normalize_name(c.get("ClientName") or "")
        if any(_phrase_in(v, cn) for v in pv):
            candidates.append(c)
    if looks_like_county(place_name):
        candidates = [c for c in candidates if not _is_township(c)]
    candidates = _unique(candidates)

    if not candidates:
        # Fall back to scoring every client in-state (rare; small states).
        scored_all = []
        for c in all_clients:
            if looks_like_county(place_name) and _is_township(c):
                continue
            sc, why = score_match(place_name, c)
            if sc >= 0.65:
                scored_all.append((sc, why, c))
        scored_all.sort(key=lambda x: -x[0])
        if not scored_all:
            return None, 0.0, "unmatched"
        # If the top score is unique enough, take it.
        top = scored_all[0]
        if len(scored_all) == 1 or top[0] >= scored_all[1][0] + 0.1:
            return top[2], top[0], top[1]
        return None, 0.0, "ambiguous:" + ",".join(
            x[2].get("ClientName") or "" for x in scored_all[:4]
        )

    scored = []
    for c in candidates:
        sc, why = score_match(place_name, c)
        scored.append((sc, why, c))
    scored.sort(key=lambda x: -x[0])
    best_sc, best_why, best = scored[0]
    if best_sc <= 0:
        return None, 0.0, "unmatched"
    ties = [x for x in scored if abs(x[0] - best_sc) < 0.02]
    if len(ties) > 1:
        county_place = looks_like_county(place_name)
        typed = [x for x in ties if _is_county_client(x[2]) == county_place]
        if len(typed) == 1:
            best_sc, best_why, best = typed[0]
            return best, min(best_sc, 0.85), best_why + "+type-break"
        names = ",".join(x[2].get("ClientName") or "" for x in ties[:4])
        return None, 0.0, "ambiguous:" + names
    return best, best_sc, best_why


def load_jurisdictions(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for row in data:
        gnis = str(row.get("gnis") or "")
        if not gnis:
            continue
        out.append(
            {
                "gnis": gnis,
                "place_name": row.get("place_name") or "",
                "state_code": (row.get("state_code") or "").upper(),
                "total_sections": row.get("total_sections"),
                "last_updated": row.get("last_updated"),
            }
        )
    return out


def build_map(
    jurisdictions: list[dict[str, Any]],
    *,
    cache_dir: str,
    sleep: float = 0.35,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    by_state: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for j in jurisdictions:
        by_state[j["state_code"]].append(j)

    result: list[dict[str, Any]] = []
    for state, rows in sorted(by_state.items()):
        if not state or len(state) != 2:
            for j in rows:
                result.append(_unmatched_row(j, "bad-state"))
            continue
        clients = None if refresh else load_cached_clients(cache_dir, state)
        if clients is None:
            print(f"fetching Municode clients for {state}...", file=sys.stderr)
            clients = clients_by_state(state, sleep=sleep)
            save_cached_clients(cache_dir, state, clients)
        print(f"{state}: {len(clients)} municode clients, {len(rows)} jurisdictions", file=sys.stderr)
        idx = _index_clients(clients)
        for j in rows:
            client, conf, why = match_one(j["place_name"], state, idx, clients)
            if client:
                result.append(
                    {
                        "gnis": j["gnis"],
                        "place_name": j["place_name"],
                        "state_code": state,
                        "publisher": "municode",
                        "source_url": library_url(state, client.get("ClientName") or ""),
                        "match_confidence": round(float(conf), 3),
                        "match_reason": why,
                        "client_id": client.get("ClientID"),
                        "client_name": client.get("ClientName"),
                        "total_sections": j.get("total_sections"),
                    }
                )
            else:
                result.append(_unmatched_row(j, why))
    result.sort(key=lambda r: (r["state_code"], r["place_name"], r["gnis"]))
    return result


def _unmatched_row(j: dict[str, Any], why: str) -> dict[str, Any]:
    return {
        "gnis": j["gnis"],
        "place_name": j["place_name"],
        "state_code": j["state_code"],
        "publisher": None,
        "source_url": None,
        "match_confidence": 0.0,
        "match_reason": why,
        "client_id": None,
        "client_name": None,
        "total_sections": j.get("total_sections"),
    }


def summarize(rows: list[dict[str, Any]]) -> str:
    c = Counter(r.get("publisher") or "unmatched" for r in rows)
    lines = [f"total={len(rows)}"]
    for k, n in c.most_common():
        lines.append(f"  {k}: {n}")
    unmatched = [r for r in rows if not r.get("publisher")]
    lines.append("unmatched examples:")
    for r in unmatched[:25]:
        lines.append(
            f"  {r['gnis']} {r['place_name']}, {r['state_code']} "
            f"(sections={r.get('total_sections')}) reason={r.get('match_reason')}"
        )
    if len(unmatched) > 25:
        lines.append(f"  ... {len(unmatched) - 25} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Match jurisdictions to publishers")
    p.add_argument("--jurisdictions", default=DEFAULT_JURIS)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE)
    p.add_argument("--sleep", type=float, default=0.35)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args(argv)
    juris = load_jurisdictions(args.jurisdictions)
    rows = build_map(juris, cache_dir=args.cache_dir, sleep=args.sleep, refresh=args.refresh)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")
    print(summarize(rows))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
