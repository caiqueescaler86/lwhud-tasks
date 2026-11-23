"""Pure, deterministic CSV analysis. No network, DB, dynamic execution or UID output."""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
from datetime import datetime
from typing import Any

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


def sanitize_csv(blob: bytes) -> tuple[list[dict[str, str]], dict[str, int]]:
    if not isinstance(blob, bytes) or not blob or len(blob) > MAX_BYTES:
        raise ValueError("CSV vazio ou maior que 1 MB.")
    if b"\x00" in blob:
        raise ValueError("Arquivo binário não é aceito. Envie apenas CSV.")
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Salve o CSV como UTF-8.") from exc
    head = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(head, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if head.partition("\n")[0].count(";") >= head.partition("\n")[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
    headers = reader.fieldnames or []
    if not headers or len(headers) > 60:
        raise ValueError("Cabeçalho CSV ausente ou grande demais.")
    mapped = [(h, ALIASES.get(norm(h))) for h in headers]
    uid_keys = [h for h in headers if norm(h) in PRIVATE_IDENTIFIERS]
    if "Jogador" not in {dest for _, dest in mapped}:
        raise ValueError("CSV precisa ter a coluna Jogador.")
    unique: dict[tuple[str, ...], tuple[dict[str, str], float, int]] = {}
    total, dupes, skipped = 0, 0, 0
    for raw in reader:
        total += 1
        if total > MAX_ROWS:
            raise ValueError("O arquivo tem mais de 2.000 registros; exporte apenas a aliança desejada.")
        if None in raw or any(value is None for value in raw.values()):
            raise ValueError("CSV tem campos desalinhados.")
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
        raise ValueError("Nenhum jogador válido encontrado no arquivo.")
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


def format_value(value: float | int | None, metric: str) -> str:
    if value is None:
        return "não disponível"
    if metric in {"hq", "rank_kills", "rank_hero", "rank_phase", "rank_arena", "sovereign_phase", "arena_score"}:
        return f"{value:,.0f}".replace(",", ".")
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}".replace(",", ".")


def allowed_plan(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Plano de consulta inválido.")
    op = str(raw.get("operation", "unsupported"))
    if op not in {"summary", "top", "bottom", "count", "list", "average", "sum", "group", "unsupported"}:
        op = "unsupported"
    metric = str(raw.get("metric", "total_power"))
    if metric not in NUMBERS:
        op = "unsupported"
        metric = "total_power"
    group = str(raw.get("group_by", "cargo"))
    if group not in GROUPS:
        group = "cargo"
    try:
        limit = max(1, min(15, int(raw.get("limit", 5))))
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


def evaluate(rows: list[dict], raw_plan: Any) -> str:
    p = allowed_plan(raw_plan)
    selected = apply_filters(rows, p["filters"])
    op, metric, group, limit = p["operation"], p["metric"], p["group_by"], p["limit"]
    if op == "unsupported":
        return "Consigo responder perguntas factuais sobre poder, kills, HQ, heróis, fases, arena, cargos e rankings. Reformule a pergunta usando esses dados."
    if not selected:
        return "Nenhum jogador corresponde aos filtros nesta cópia do CSV. Não há dados para responder."
    if op == "count":
        return f"{len(selected)} jogadores encontrados (de {len(rows)} no snapshot)."
    if op == "list":
        return f"{len(selected)} jogadores encontrados:\n" + "\n".join("- " + r["Jogador"] for r in selected[:limit]) + (f"\n(Mostrando {limit})" if len(selected) > limit else "")
    if op == "summary":
        lines = [f"Snapshot: {len(selected)} jogadores ({len(rows)} no total)."]
        for key in ("total_power", "kills", "troop_power"):
            numbers = [number(row[METRICS[key]]) for row in selected]
            known = [n for n in numbers if n is not None]
            if known:
                lines.append(f"{METRICS[key]}: média {format_value(sum(known)/len(known), key)}; dados disponíveis em {len(known)}/{len(selected)} jogadores.")
        from collections import Counter
        ranks = Counter(r["Cargo"] for r in selected if r["Cargo"])
        lines.append("Cargos observados: " + (", ".join(f"{r}: {n}" for r, n in sorted(ranks.items())) or "não informado"))
        return "\n".join(lines) + "\nValores ausentes não são considerados zero."
    if op == "group":
        from collections import defaultdict
        buckets = defaultdict(list)
        for row in selected:
            buckets[row.get(GROUPS[group]) or "não informado"].append(row)
        lines = []
        for name, subset in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
            values = [number(r[METRICS[metric]]) for r in subset]
            actual = [v for v in values if v is not None]
            avg = format_value(sum(actual)/len(actual), metric) if actual else "não disponível"
            lines.append(f"- {name}: {len(subset)} jogadores, média de {METRICS[metric]} {avg} ({len(actual)} com dados)")
        return "\n".join(lines[:20])
    measured = [(r, number(r[METRICS[metric]])) for r in selected]
    valid = [(r, n) for r, n in measured if n is not None]
    if not valid:
        return f"Não há valores preenchidos de {METRICS[metric]} entre os {len(selected)} jogadores filtrados."
    if op in ("sum", "average"):
        v = sum(n for _, n in valid)
        if op == "average":
            v = v / len(valid)
        return f"{METRICS[metric]} — {'média' if op == 'average' else 'soma'}: {format_value(v,metric)}. Base: {len(valid)} de {len(selected)} jogadores com valor disponível."
    if op in ("top", "bottom"):
        order = op == "top"
        # Rank: 1 is best; for rank fields reverse numeric ordering.
        if metric.startswith("rank_"):
            order = not order
        valid.sort(key=lambda item: item[1], reverse=order)
        result = [f"{METRICS[metric]} — {'maiores/melhores' if op == 'top' else 'menores/piores'} (dados disponíveis: {len(valid)}/{len(selected)}):"]
        for index, (row, val) in enumerate(valid[:limit], 1):
            result.append(f"{index}. {row['Jogador']} ({row.get('Cargo') or 'cargo não informado'}) — {format_value(val, metric)}")
        if len(valid) < len(selected):
            result.append("Jogadores sem métrica preenchida ficaram fora desta classificação.")
        return "\n".join(result)
    return "Não há uma operação segura para essa pergunta."


def local_fallback_plan(question: str) -> dict:
    """Small no-API fallback: we do not claim to understand open-ended questions."""
    q = norm(question)
    metric = "total_power"
    if "kill" in q or "abate" in q:
        metric = "kills"
    elif "tropa" in q:
        metric = "troop_power"
    elif "arena" in q:
        metric = "arena_score"
    elif "heroi" in q:
        metric = "hero_power"
    elif "soberano" in q or "fase" in q:
        metric = "sovereign_phase"
    elif "hq" in q or "cidade" in q or "nivel" in q:
        metric = "hq"
    op = "unsupported"
    if any(word in q for word in ("mais", "maiores", "maior", "top", "fortes", "ranking", "lider")):
        op = "top"
    elif any(word in q for word in ("menos", "menores", "pior", "fracos")):
        op = "bottom"
    elif any(word in q for word in ("quantos", "quantas", "numero", "contagem")):
        op = "count"
    elif any(word in q for word in ("media", "medio")):
        op = "average"
    elif any(word in q for word in ("resumo", "visao", "situacao", "geral")):
        op = "summary"
    match = re.search(r"\br([1-5])\b", question.lower())
    filters = {"cargo": "R" + match.group(1)} if match else {}
    return {"operation": op, "metric": metric, "filters": filters}
