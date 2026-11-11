#!/usr/bin/env python3
"""Count the statuses in vana-client's docs/re/modlog-gaps.md and write the
progress page's data file.

Usage: modlog_progress.py <vana-client checkout> <ref> <out.json>

The checkout needs the history of <ref> (the workflow fetches the branch with
full depth); every commit on <ref> that touched the gaps doc becomes one point
of the history chart.
"""
import json
import re
import subprocess
import sys

DOC = "docs/re/modlog-gaps.md"

# Order matters: the first rule that matches the start of the status wins.
RULES = [
    ("excluded", r"(ours|\*\*upstream|upstream|deviation)"),
    ("blocked", r"(blocked|not built \(lsb never sends|.*\blsb never sends\b)"),
    ("accepted", r"(known limitation|known difference|backend limit)"),
    ("partial", r"(built apart from|partly built|built for one|built; |matches; lsb)"),
    ("unverified", r"(built,? (but )?(not|untested)|not checked( live| against)?$|not checked against|not seen live$|not seen live \(|untested)"),
    ("done", r"(built|matches|answered|closed)"),
    ("open", r"."),
]
CATEGORIES = ["done", "unverified", "partial", "open", "blocked", "accepted", "excluded"]


def split_row(line):
    """Split a markdown table row on pipes that are not inside backticks."""
    cells, cur, tick = [], [], False
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    prev = ""
    for ch in body:
        if ch == "|" and prev == "\\":
            cur[-1] = "|"
            prev = ch
            continue
        prev = ch
        if ch == "`":
            tick = not tick
        if ch == "|" and not tick:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


def clean_status(s):
    s = re.sub(r"\*\(.*?\)\*", "", s)          # italic notes
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = s.replace("*", "").strip()
    return s


def classify(status):
    low = status.lower()
    for cat, pat in RULES:
        if re.match(pat, low):
            return cat
    return "open"


def parse(text):
    sections = []          # [{"title", "counts", "items": n}]
    closed = 0
    backlog = 0
    sec = None
    header = None
    for line in text.splitlines():
        h = re.match(r"^(##+)\s+(.*)", line)
        if h:
            level, title = len(h.group(1)), h.group(2).strip()
            if level == 2:
                header = None
                if re.match(r"^\d+\.", title):
                    sec = {"title": title, "counts": {c: 0 for c in CATEGORIES}}
                    sections.append(sec)
                elif title.lower().startswith("closed"):
                    sec = {"title": title, "closed": True}
                else:
                    sec = None
            continue
        if sec is None:
            continue
        if sec.get("closed"):
            if line.startswith("|") and not line.startswith("|---"):
                cells = split_row(line)
                if cells and cells[0] not in ("Early item", "Item") and any(cells[1:]):
                    closed += 1
            continue
        if line.startswith("- ") and "live-check" in sec["title"].lower():
            backlog += 1
            continue
        if not line.startswith("|"):
            continue
        if line.startswith("|---"):
            continue
        cells = split_row(line)
        if cells[0] in ("Item", "Early item"):
            header = [c.lower() for c in cells]
            continue
        if header is None:
            continue
        if "ours" in sec["title"].lower():
            # Section 13 lists our own deviations and upstream questions, not retail gaps.
            cat = "excluded"
        elif "status" in header:
            status = clean_status(cells[header.index("status")]) if len(cells) > header.index("status") else ""
            cat = classify(status)
        else:
            # Section 12's table has no status column: every row is blocked.
            cat = "blocked"
        sec["counts"][cat] += 1
    sections = [s for s in sections if "counts" in s]
    total = {c: sum(s["counts"][c] for s in sections) for c in CATEGORIES}
    return sections, total, closed, backlog


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def summary(total):
    tracked = total["done"] + total["unverified"] + total["partial"] + total["open"]
    built = total["done"] + total["unverified"]
    return tracked, built, round(100 * built / tracked, 1) if tracked else 0.0


def main():
    repo, ref, out = sys.argv[1:4]
    head = git(repo, "rev-parse", ref).strip()
    head_date = git(repo, "log", "-1", "--format=%cI", head).strip()
    sections, total, closed, backlog = parse(git(repo, "show", f"{head}:{DOC}"))
    tracked, built, pct = summary(total)

    history = []
    log = git(repo, "log", "--first-parent", "--format=%H %cI", ref, "--", DOC).split("\n")
    for row in reversed([r for r in log if r.strip()]):
        sha, date = row.split()
        try:
            _, t, _, _ = parse(git(repo, "show", f"{sha}:{DOC}"))
        except subprocess.CalledProcessError:
            continue
        tr, bu, pc = summary(t)
        history.append({"date": date, "commit": sha[:10], "tracked": tr, "built": bu, "percent": pc,
                        **{c: t[c] for c in CATEGORIES}})

    data = {
        "source": {"repo": "akreao/vana-client", "branch": ref.split("/")[-1], "path": DOC,
                   "commit": head, "commit_date": head_date},
        "tracked": tracked, "built": built, "percent": pct,
        "totals": total, "closed_earlier": closed, "live_backlog": backlog,
        "sections": [{"title": s["title"], **s["counts"]} for s in sections],
        "history": history,
    }
    with open(out, "w") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
    print(f"{built}/{tracked} built or answered ({pct}%), commit {head[:10]}")


if __name__ == "__main__":
    main()
