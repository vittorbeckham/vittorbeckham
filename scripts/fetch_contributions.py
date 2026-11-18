"""Atualiza data/contributions.json e data/repos.json.

Roda na Action agendada (diariamente). Com GH_TOKEN usa a API GraphQL
(se o token for um PAT seu, conta também contribuições privadas); sem token
ou se a API falhar, lê o calendário público github.com/users/<login>/contributions.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
LOGIN = os.environ.get("GH_LOGIN") or PROFILE["login"]
TOKEN = os.environ.get("GH_TOKEN", "").strip()
UA = {"User-Agent": "profile-cards-script", "Accept": "application/vnd.github+json"}


def _get(url: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def days_graphql() -> list[dict]:
    query = """query($login:String!){user(login:$login){contributionsCollection{
      contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}"""
    body = json.dumps({"query": query, "variables": {"login": LOGIN}}).encode()
    res = json.loads(_get("https://api.github.com/graphql", body,
                          {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}))
    if "errors" in res:
        raise RuntimeError(res["errors"])
    weeks = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [{"date": d["date"], "count": d["contributionCount"]}
            for w in weeks for d in w["contributionDays"]]


def days_html() -> list[dict]:
    html = _get(f"https://github.com/users/{LOGIN}/contributions",
                headers={"Accept": "text/html"}).decode("utf-8")
    ids: dict[str, str] = {}  # id da célula -> data
    for tag in re.findall(r"<td[^>]*data-date=[^>]*>", html):
        d, i = re.search(r'data-date="([\d-]+)"', tag), re.search(r'\bid="([^"]+)"', tag)
        if d and i:
            ids[i.group(1)] = d.group(1)
    counts = {d: 0 for d in ids.values()}
    for for_id, text in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html):
        m = re.match(r"\s*([\d,]+) contribution", text)
        if for_id in ids and m:
            counts[ids[for_id]] = int(m.group(1).replace(",", ""))
    if not counts:
        raise RuntimeError("calendário público não reconhecido")
    return [{"date": d, "count": counts[d]} for d in sorted(counts)]


def repo_stats() -> dict:
    out = {}
    headers = {"Authorization": f"bearer {TOKEN}"} if TOKEN else {}
    for r in PROFILE["featured"]:
        try:
            d = json.loads(_get(f"https://api.github.com/repos/{LOGIN}/{r['repo']}", headers=headers))
        except Exception as e:  # privado/renomeado: o card usa só o texto de profile.json
            print(f"aviso: {r['repo']}: {e}", file=sys.stderr)
            continue
        out[r["repo"]] = {k: d.get(k) for k in ("description", "language", "stargazers_count",
                                                "forks_count", "pushed_at", "html_url")}
    return out


def main() -> None:
    try:
        days, source = (days_graphql(), "graphql") if TOKEN else (days_html(), "html")
    except Exception as e:
        print(f"aviso: GraphQL falhou ({e}); usando o calendário público", file=sys.stderr)
        days, source = days_html(), "html"
    data = {
        "login": LOGIN,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "total": sum(d["count"] for d in days),
        "days": days,
    }
    (ROOT / "data" / "contributions.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (ROOT / "data" / "repos.json").write_text(
        json.dumps(repo_stats(), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(days)} dias, {data['total']} contribuições ({source})")


if __name__ == "__main__":
    main()
