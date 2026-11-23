"""Pure, deterministic CSV analysis. No network, DB, dynamic execution or UID output."""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from datetime import datetime
from typing import Any

from i18n import field_title, t

MAX_BYTES = 1024 * 1024
MAX_ROWS = 2000
MAX_QUESTION = 400

FIELDS = (
    "Tag", "Aliança conhecida", "Servidor", "Jogador", "Cargo", "Total Power",
    "HQ", "Rank Kills", "Kills", "Hero Total Power", "Rank Herói forte",
    "Herói forte", "Rank Fase", "Fase Soberano", "Rank Arena", "Score Arena",
    "Poder tropa", "Status", "Última obs.",
)
NUMERIC_FIELDS = {
    "Total Power": "total_power", "HQ": "hq", "Rank Kills": "rank_kills",
    "Kills": "kills", "Hero Total Power": "hero_power", "Rank Herói forte": "rank_hero",
    "Herói forte": "strongest_hero", "Rank Fase": "rank_phase",
    "Fase Soberano": "sovereign_phase", "Rank Arena": "rank_arena",
    "Score Arena": "arena_score", "Poder tropa": "troop_power",
}
METRICS = {v: k for k, v in NUMERIC_FIELDS.items()}
NUMBERS = set(METRICS)
GROUPS = {"cargo": "Cargo", "tag": "Tag", "servidor": "Servidor", "hq": "HQ", "status": "Status"}
PRIVATE_IDENTIFIERS = {"uid", "playeruid", "playerid", "userid", "identificadordojogador", "idjogador"}
UID_PATTERN = re.compile(r"(?<!\d)\d{13,20}(?!\d)")


def norm(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in value if char.isalnum() and not unicodedata.combining(char))


ALIASES = {norm(field): field for field in FIELDS}
ALIASES.update({"rankpoder": "Total Power", "poder": "Total Power",
                "cidade": "HQ", "herois": "Hero Total Power", "alianca": "Aliança conhecida",
                "ultimaobs": "Última obs.", "playername": "Jogador", "nickname": "Jogador"})


def safe_text(raw: Any, maximum: int = 110) -> str:
    """A displayable value, not HTML/Markdown/code; never expose UID-shaped numbers."""
    value = str(raw or "")
    value = "".join(" " if (ord(c) < 32 or c in "\u2028\u2029") else c for c in value)
    value = UID_PATTERN.sub("[identificador oculto]", value)
    return " ".join(value.split())[:maximum]


def row_completeness(row: dict) -> int:
    return sum(1 for v in row.values() if v.strip() and v.strip() not in ("—", "-", "N/A"))


def timestamp(text: str) -> float:
    text = str(text or "")[:24]
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m %H:%M"):
        try:
            result = datetime.strptime(text, fmt)
            return result.replace(year=(result.year if fmt.startswith("%d/%m/%Y") else 2026)).timestamp()
        except ValueError:
            pass
    return 0.0


def sanitize_csv(blob: bytes, language: str = "pt") -> tuple[list[dict[str, str]], dict[str, int]]:
    if not isinstance(blob, bytes) or not blob or len(blob) > MAX_BYTES:
        raise ValueError(t(language, "err_empty"))
    if b"\x00" in blob:
        raise ValueError(t(language, "err_binary"))
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(t(language, "err_utf8")) from exc
    head = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(head, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if head.partition("\n")[0].count(";") >= head.partition("\n")[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
    headers = reader.fieldnames or []
    if not headers or len(headers) > 60:
        raise ValueError(t(language, "err_header"))
    mapped = [(h, ALIASES.get(norm(h))) for h in headers]
    uid_keys = [h for h in headers if norm(h) in PRIVATE_IDENTIFIERS]
    if "Jogador" not in {dest for _, dest in mapped}:
        raise ValueError(t(language, "err_player"))
    unique: dict[tuple[str, ...], tuple[dict[str, str], float, int]] = {}
    total, dupes, skipped = 0, 0, 0
    for raw in reader:
        total += 1
        if total > MAX_ROWS:
            raise ValueError(t(language, "err_rows"))
        if None in raw or any(value is None for value in raw.values()):
            raise ValueError(t(language, "err_alignment"))
        out = {field: "" for field in FIELDS}
        for source, destination in mapped:
            if destination:
                out[destination] = safe_text(raw.get(source), 96 if destination == "Jogador" else 120)
        if not out["Jogador"] or out["Jogador"] == "—":
            skipped += 1
            continue
        uid = next((str(raw.get(h, "")).strip() for h in uid_keys if str(raw.get(h, "")).strip()), "")
        if uid:
            # UID is used in memory for duplicate detection only, never retained.
            key = ("uid", uid)
        else:
            key = ("name", norm(out["Servidor"]), norm(out["Tag"]), norm(out["Jogador"]))
        candidate = (out, timestamp(out["Última obs."]), row_completeness(out))
        if key in unique:
            dupes += 1
            previous = unique[key]
            if candidate[1:] >= previous[1:]:
                unique[key] = candidate
        else:
            unique[key] = candidate
    if not unique:
        raise ValueError(t(language, "err_no_valid"))
    records = [item[0] for item in unique.values()]
    records.sort(key=lambda r: (r.get("Tag", ""), -float(number(r.get("Total Power")) or 0), r["Jogador"].casefold()))
    return records, {"linhas": total, "jogadores": len(records), "duplicados": dupes,
                     "ignorados": skipped, "colunas_privadas_removidas": len(uid_keys)}


def number(value: Any) -> float | None:
    s = str(value if value is not None else "").strip().upper().replace(" ", "")
    if not s or s in ("—", "-", "N/A", "NULL"):
        return None
    multiplier = 1.0
    if s[-1:] in ("K", "M", "B"):
        multiplier = {"K": 1000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}[s[-1]]
        s = s[:-1]
    # Both BR and US decimals, without ever eval()-ing values.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        x = float(s) * multiplier
        return x if math.isfinite(x) else None
    except (ValueError, OverflowError):
        return None


def format_value(value: float | int | None, metric: str, language: str = "pt") -> str:
    if value is None:
        return t(language, "not_available")
    sep = "," if language in ("en", "zh") else "."
    if metric in {"hq", "rank_kills", "rank_hero", "rank_phase", "rank_arena", "sovereign_phase", "arena_score"}:
        return f"{value:,.0f}".replace(",", sep)
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}".replace(",", sep)


def allowed_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Plano de consulta inválido.")
    op = str(raw.get("operation", "unsupported"))
    if op not in {"summary", "top", "bottom", "count", "list", "average", "sum", "group", "teams", "unsupported"}:
        op = "unsupported"
    metric = str(raw.get("metric", "total_power"))
    if metric not in NUMBERS:
        op = "unsupported"
        metric = "total_power"
    group = str(raw.get("group_by", "cargo"))
    if group not in GROUPS:
        group = "cargo"
    try:
        limit = max(2 if op == "teams" else 1, min(12 if op == "teams" else 15, int(raw.get("limit", 5))))
    except (ValueError, TypeError):
        limit = 5
    f = raw.get("filters") if isinstance(raw.get("filters"), dict) else {}
    filters = {}
    for k in ("cargo", "tag", "server", "name_contains", "status"):
        if isinstance(f.get(k), str) and f[k].strip():
            filters[k] = safe_text(f[k], 50)
    if f.get("hq") is not None:
        try:
            filters["hq"] = int(f["hq"])
        except (ValueError, TypeError):
            pass
    return {"operation": op, "metric": metric, "group_by": group, "limit": limit, "filters": filters}


def apply_filters(rows: list[dict], filters: dict) -> list[dict]:
    lookup = {"cargo": "Cargo", "tag": "Tag", "server": "Servidor", "status": "Status"}
    result = []
    for r in rows:
        if any(norm(r.get(col)) != norm(filters[key]) for key, col in lookup.items() if key in filters):
            continue
        if "name_contains" in filters and norm(filters["name_contains"]) not in norm(r["Jogador"]):
            continue
        if "hq" in filters and number(r.get("HQ")) != filters["hq"]:
            continue
        result.append(r)
    return result


def create_balanced_teams(rows: list[dict], count: int, language: str = "pt") -> str:
    """Deterministic, approximate balance by total power; never calls the model or DB."""
    count = max(2, min(12, int(count)))
    ranked = [(row, number(row.get("Total Power"))) for row in rows]
    known = sorted(((row, value) for row, value in ranked if value is not None and value >= 0),
                   key=lambda item: (-item[1], item[0]["Jogador"].casefold()))
    if len(known) < count:
        return t(language, "teams_insufficient", players=len(known), teams=count)

    # Keep squad sizes within one player, then assign highest powers to the lowest
    # running team total that still has a free slot.
    base, extras = divmod(len(known), count)
    capacities = [base + (index < extras) for index in range(count)]
    groups = [[] for _ in range(count)]
    totals = [0.0] * count
    for row, power in known:
        available = [i for i in range(count) if len(groups[i]) < capacities[i]]
        index = min(available, key=lambda i: (totals[i], len(groups[i]), i))
        groups[index].append((row, power))
        totals[index] += power

    output = [t(language, "teams_summary", teams=count, players=len(known))]
    for i, group in enumerate(groups):
        output.append(t(language, "teams_label", index=i + 1, count=len(group),
                        power=format_value(totals[i], "total_power", language)))
        output.extend("• " + row["Jogador"] + " — " +
                      format_value(power, "total_power", language) for row, power in group)
        output.append("")
    excluded = len(rows) - len(known)
    if excluded:
        output.append(t(language, "teams_missing", count=excluded))
    return "\n".join(output).rstrip()


def evaluate(rows: list[dict], raw_plan: Any, language: str = "pt") -> str:
    """Evaluate allowlisted, deterministic queries and format in the chosen UI language."""
    p = allowed_plan(raw_plan)
    selected = apply_filters(rows, p["filters"])
    op, metric, group, limit = p["operation"], p["metric"], p["group_by"], p["limit"]
    if op == "unsupported":
        return t(language, "unsupported")
    if not selected:
        return t(language, "no_results")
    if op == "teams":
        return create_balanced_teams(selected, limit, language)
    if op == "count":
        return t(language, "count_result", count=len(selected), total=len(rows))
    if op == "list":
        lines = [t(language, "list_header", count=len(selected))]
        lines.extend("- " + r["Jogador"] for r in selected[:limit])
        if len(selected) > limit:
            lines.append(t(language, "showing", limit=limit))
        return "\n".join(lines)
    if op == "summary":
        lines = [t(language, "summary_header", count=len(selected), total=len(rows))]
        for key in ("total_power", "kills", "troop_power"):
            numbers = [number(row[METRICS[key]]) for row in selected]
            known = [n for n in numbers if n is not None]
            if known:
                lines.append(t(
                    language, "summary_stat", metric=field_title(language, METRICS[key]),
                    value=format_value(sum(known)/len(known), key, language),
                    available=len(known), count=len(selected),
                ))
        from collections import Counter
        ranks = Counter(r["Cargo"] for r in selected if r["Cargo"])
        roles = ", ".join(f"{r}: {n}" for r, n in sorted(ranks.items())) or t(language, "not_reported")
        lines.append(t(language, "summary_roles", roles=roles))
        lines.append(t(language, "missing_not_zero"))
        return "\n".join(lines)
    if op == "group":
        from collections import defaultdict
        buckets = defaultdict(list)
        for row in selected:
            buckets[row.get(GROUPS[group]) or t(language, "not_reported")].append(row)
        lines = []
        for name, subset in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
            values = [number(r[METRICS[metric]]) for r in subset]
            actual = [v for v in values if v is not None]
            avg = format_value(sum(actual)/len(actual), metric, language) if actual else t(language, "not_available")
            lines.append(t(
                language, "group_row", name=name, count=len(subset),
                metric=field_title(language, METRICS[metric]), average=avg,
                available=len(actual),
            ))
        return "\n".join(lines[:20])
    measured = [(r, number(r[METRICS[metric]])) for r in selected]
    valid = [(r, n) for r, n in measured if n is not None]
    if not valid:
        return t(language, "missing_metric", metric=field_title(language, METRICS[metric]), count=len(selected))
    if op in ("sum", "average"):
        total = sum(n for _, n in valid)
        value = total/len(valid) if op == "average" else total
        return t(
            language, "aggregate", metric=field_title(language, METRICS[metric]),
            operation=t(language, "average" if op == "average" else "sum"),
            value=format_value(value, metric, language), available=len(valid),
            count=len(selected),
        )
    if op in ("top", "bottom"):
        descending = op == "top"
        # A lower number is better for ranking metrics.
        if metric.startswith("rank_"):
            descending = not descending
        valid.sort(key=lambda item: item[1], reverse=descending)
        result = [t(
            language, "rank_header", metric=field_title(language, METRICS[metric]),
            direction=t(language, "top" if op == "top" else "bottom"),
            available=len(valid), count=len(selected),
        )]
        for index, (row, val) in enumerate(valid[:limit], 1):
            result.append(t(
                language, "rank_item", index=index, player=row["Jogador"],
                role=row.get("Cargo") or t(language, "role_unknown"),
                value=format_value(val, metric, language),
            ))
        if len(valid) < len(selected):
            result.append(t(language, "rank_missing_note"))
        return "\n".join(result)
    return t(language, "unknown_operation")


def local_fallback_plan(question: str) -> dict:
    """Conservative no-API fallback for Portuguese, English, Chinese and Turkish."""
    q = norm(question)
    # Creating equal-strength squads is fully deterministic: Groq is not needed.
    team_words = ("teams", "team", "squad", "equipes", "equipe", "times",
                  "takim", "ekip", "队伍", "战队", "小队", "队")
    if any(w in q for w in team_words):
        digits = re.search(r"(?<!\d)(1[0-2]|[2-9])(?!\d)", q)
        team_count = int(digits.group(1)) if digits else 6
        return {"operation": "teams", "metric": "total_power", "limit": team_count, "filters": {}}
    metric = "total_power"
    if any(w in q for w in ("kill", "abate", "击杀", "击败", "oldur")):
        metric = "kills"
    elif any(w in q for w in ("tropa", "troop", "birlik", "部队")):
        metric = "troop_power"
    elif any(w in q for w in ("arena", "竞技场")):
        metric = "arena_score"
    elif any(w in q for w in ("heroi", "hero", "kahraman", "英雄")):
        metric = "hero_power"
    elif any(w in q for w in ("soberano", "fase", "phase", "asama", "阶段")):
        metric = "sovereign_phase"
    elif any(w in q for w in ("hq", "cidade", "nivel", "level", "karargah", "主城")):
        metric = "hq"
    op = "unsupported"
    if any(w in q for w in ("mais", "maiores", "maior", "top", "fortes", "ranking", "lider",
                            "highest", "strongest", "most", "best", "top", "enguclu", "enyuksek",
                            "enfazla", "siralama", "最多", "最高", "最强", "排名", "前十", "前五")):
        op = "top"
    elif any(w in q for w in ("menos", "menores", "pior", "fracos", "lowest", "weakest",
                              "least", "endulus", "enaz", "最少", "最低", "最弱")):
        op = "bottom"
    elif any(w in q for w in ("quantos", "quantas", "numero", "contagem", "howmany",
                              "count", "kac", "sayisi", "多少", "几个", "人数")):
        op = "count"
    elif any(w in q for w in ("media", "medio", "average", "mean", "ortalama", "平均")):
        op = "average"
    elif any(w in q for w in ("resumo", "visao", "situacao", "geral", "summary",
                              "overview", "ozet", "genel", "概览", "总结", "汇总")):
        op = "summary"
    match = re.search(r"\br([1-5])\b", question.lower())
    filters = {"cargo": "R" + match.group(1)} if match else {}
    # Short, specific questions about officers must work without Groq.
    role_question = any(word in q for word in (
        "whois", "whoare", "whichplayers", "quem", "quemsao",
        "list", "show", "mostre", "liste", "kim", "kimler",
        "谁是", "有哪些", "成员", "kimdir"
    ))
    if match and op == "unsupported" and role_question:
        op = "list"
    return {"operation": op, "metric": metric, "filters": filters,
            "limit": 15 if op == "list" and match else 5}
