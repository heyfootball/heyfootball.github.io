# HeyFootball: builds a page for every team and every match, so people find the site on Google
# ("Benfica vs Porto: score, stats and predictions"). GitHub runs this by itself every 3 hours
# (see .github/workflows/pages.yml). Scores and tables come from the HeyFootball scores worker,
# match stats (possession, shots, passes...) from ESPN's free public data.
# Usage: python scripts/build_pages.py <site folder>
import sys, os, re, json, html, unicodedata, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
SITE = "https://heyfootball.github.io"
WORKER = "https://rf-data.scratchgamesstudio15.workers.dev/"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
LEAGUES = {"PPL": ("Liga Portugal", "por.1"), "PL": ("Premier League", "eng.1"), "PD": ("La Liga", "esp.1"), "SA": ("Serie A", "ita.1"),
           "BL1": ("Bundesliga", "ger.1"), "FL1": ("Ligue 1", "fra.1"), "CL": ("Champions League", "uefa.champions"),
           "DED": ("Eredivisie", "ned.1"), "ELC": ("Championship", "eng.2")}
try:
    from zoneinfo import ZoneInfo
    LIS = ZoneInfo("Europe/Lisbon")
except Exception:                       # no time zone data on this computer: use UTC
    LIS = timezone.utc
NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(LIS).date().isoformat()
esc = lambda s: html.escape(str(s if s is not None else ""))

def get_json(url, headers=None, tries=3):
    import time
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HeyFootball page builder (+https://heyfootball.github.io)", **(headers or {})})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == tries - 1: raise
            time.sleep(3 * (i + 1))

def slug(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "team"

def when(t):
    d = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(LIS)
    return d.strftime("%a %d %b %Y, %H:%M"), d.date().isoformat()

# ---------- the data ----------
try:
    data = get_json(WORKER)
except Exception:          # the worker had a hiccup: ask the Supabase backup route instead
    data = get_json("https://botczxlxmzxgpbxgflin.supabase.co/functions/v1/scores", {"apikey": "sb_publishable_z7tZBtDopjaRRVP1bXPppg_MEQQ0HDe"})
# the names people actually type into Google
FULL = {"Barça": "Barcelona", "Man City": "Manchester City", "Man United": "Manchester United", "Atleti": "Atlético Madrid", "Inter": "Inter Milan",
        "Bayern": "Bayern Munich", "Spurs": "Tottenham", "Nottingham": "Nottingham Forest", "Newcastle": "Newcastle United", "Brighton Hove": "Brighton",
        "Wolverhampton": "Wolves", "Leverkusen": "Bayer Leverkusen", "Dortmund": "Borussia Dortmund", "M'gladbach": "Borussia Mönchengladbach",
        "Athletic": "Athletic Bilbao", "Real Sociedad": "Real Sociedad", "Shaktar": "Shakhtar Donetsk", "Bodø/Glimt": "Bodø/Glimt", "PSV": "PSV Eindhoven",
        "SL Benfica": "Benfica", "Sporting CP": "Sporting CP", "RB Leipzig": "RB Leipzig", "PAE AEK": "AEK Athens", "Sl. Bratislava": "Slovan Bratislava",
        "Slavia Praha": "Slavia Prague", "Como 1907": "Como", "RC Lens": "Lens", "Stade Rennais": "Rennes", "Olympique Lyon": "Lyon", "Marseille": "Marseille"}
fix = lambda n: FULL.get(n, n)
tables = {k: [[fix(r[0])] + list(r[1:]) for r in v] for k, v in (data.get("leagues") or {}).items() if v}
for key in ("live", "res", "hist", "fx"):
    for m in data.get(key) or []:
        m["h"], m["a"] = fix(m.get("h")), fix(m.get("a"))
seen, matches = set(), []
for key, st in (("live", "live"), ("res", "ft"), ("hist", "ft"), ("fx", "up")):
    for m in data.get(key) or []:
        if not m.get("id") or m["id"] in seen or m.get("c") not in LEAGUES or not m.get("t"):
            continue
        seen.add(m["id"]); m = dict(m); m["st"] = st
        if st == "ft" and m.get("hs") is None:
            continue
        t = datetime.fromisoformat(m["t"].replace("Z", "+00:00"))
        if st == "up" and t > NOW + timedelta(days=21):
            continue
        if st == "ft" and t < NOW - timedelta(days=150):
            continue
        matches.append(m)
matches.sort(key=lambda m: m["t"])
for m in matches:
    m["slug"] = f'{when(m["t"])[1]}-{slug(m["h"])}-vs-{slug(m["a"])}'

# league position of every team
pos = {}
for lg, rows in tables.items():
    for i, r in enumerate(rows):
        pos.setdefault(r[0], (lg, i + 1, r, len(rows)))
teams = sorted({m["h"] for m in matches} | {m["a"] for m in matches} | set(pos))
team_slug = {t: slug(t) for t in teams}
played = lambda t: [m for m in matches if m["st"] == "ft" and t in (m["h"], m["a"])][::-1]
coming = lambda t: [m for m in matches if m["st"] in ("up", "live") and t in (m["h"], m["a"])]

def result(m, t):
    f, a = (m["hs"], m["as"]) if m["h"] == t else (m["as"], m["hs"])
    return "W" if f > a else "L" if f < a else "D"

def strength(t):
    """How strong a team looks: (points per game, goal difference per game) from its league table, or recent form."""
    if t in pos:
        r = pos[t][2]; g = max(1, r[1] + r[2] + r[3]); gd = r[5] if len(r) > 5 and r[5] is not None else 0
        return r[4] / g, gd / g
    p = played(t)[:6]
    if not p: return 1.3, 0
    pts = sum(3 if result(m, t) == "W" else 1 if result(m, t) == "D" else 0 for m in p)
    gd = sum((m["hs"] - m["as"]) * (1 if m["h"] == t else -1) for m in p)
    return pts / len(p), gd / len(p)

def predict(m):
    import math
    (ph_, gh_), (pa_, ga_) = strength(m["h"]), strength(m["a"])
    d = 0.6 * (ph_ - pa_) + 0.12 * (gh_ - ga_) + 0.25          # 0.25 = home advantage
    draw = round(26 - 6 * min(abs(d), 1.5))
    home = round((100 - draw) / (1 + math.exp(-1.3 * d)))
    gh = max(0, min(4, round(1.35 + 0.6 * d))); ga = max(0, min(4, round(1.1 - 0.6 * d)))
    return gh, ga, home, draw, 100 - draw - home

# ---------- ESPN match stats for recent finished games ----------
STAT_ROWS = [("possessionPct", "Possession", "%"), ("totalShots", "Shots", ""), ("shotsOnTarget", "Shots on target", ""), ("totalPasses", "Passes", ""),
             ("accuratePasses", "Accurate passes", ""), ("wonCorners", "Corners", ""), ("foulsCommitted", "Fouls", ""), ("offsides", "Offsides", ""),
             ("saves", "Saves", ""), ("yellowCards", "Yellow cards", ""), ("redCards", "Red cards", "")]
ALIAS = {"psg": "paris", "spurs": "tottenham", "atleti": "atletico", "barca": "barcelona", "inter": "internazionale", "bayern": "munich",
         "gladbach": "monchengladbach", "wolves": "wolverhampton", "forest": "nottingham", "villa": "aston"}
STOP = {"fc", "cf", "sc", "ac", "afc", "club", "de", "cd", "sl", "sad", "ssc", "as", "us", "calcio"}
def words(s):
    raw = re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()).split()
    w = [x for x in raw if len(x) > 2 and x not in STOP]
    return w + [ALIAS[x] for x in raw if x in ALIAS]
def same(a, b):
    x, y = words(a), words(b)
    return any(p == q or (len(p) >= 4 and len(q) >= 4 and (p.startswith(q) or q.startswith(p))) for p in x for q in y)
boards = {}
def espn_stats(m):
    lg = LEAGUES[m["c"]][1]; t = datetime.fromisoformat(m["t"].replace("Z", "+00:00"))
    for day in (t, t - timedelta(days=1)):
        key = (lg, day.strftime("%Y%m%d"))
        if key not in boards:
            try: boards[key] = get_json(f"{ESPN}{lg}/scoreboard?dates={key[1]}").get("events") or []
            except Exception: boards[key] = []
        for e in boards[key]:
            comp = (e.get("competitions") or [{}])[0]; names = [c["team"]["displayName"] + " " + c["team"].get("shortDisplayName", "") for c in comp.get("competitors", [])]
            if len(names) == 2 and ((same(names[0], m["h"]) and same(names[1], m["a"])) or (same(names[0], m["a"]) and same(names[1], m["h"]))):
                try:
                    teams_ = get_json(f"{ESPN}{lg}/summary?event={e['id']}").get("boxscore", {}).get("teams") or []
                except Exception:
                    return None
                pick = lambda tm: {s["name"]: s.get("displayValue") for s in tm.get("statistics", [])}
                home = next((x for x in teams_ if same(x["team"]["displayName"] + " " + x["team"].get("shortDisplayName", ""), m["h"])), None)
                away = next((x for x in teams_ if x is not home), None)
                return (pick(home), pick(away)) if home and away else None
    return None
stats = {}
for m in matches:
    if m["st"] == "ft" and datetime.fromisoformat(m["t"].replace("Z", "+00:00")) > NOW - timedelta(days=6):
        try: stats[m["id"]] = espn_stats(m)
        except Exception: stats[m["id"]] = None

# ---------- page parts ----------
HIT = ('<script>/* visitor stats: anonymous, no cookies */fetch("https://botczxlxmzxgpbxgflin.supabase.co/rest/v1/rpc/hit",{method:"POST",keepalive:true,'
       'headers:{apikey:"sb_publishable_z7tZBtDopjaRRVP1bXPppg_MEQQ0HDe","Content-Type":"application/json"},'
       'body:JSON.stringify({p_path:location.pathname,p_ref:document.referrer||null})}).catch(()=>{})</script>')
CSS = """<style>.score{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center;text-align:center;margin:18px 0}.score b{font-size:54px;font-weight:900;padding:6px 18px;border-radius:16px;background:#ffffff14}
.score a{font-size:22px;font-weight:800;color:inherit}.pill{display:inline-block;padding:3px 10px;border-radius:99px;background:#ffffff14;font-weight:700;font-size:14px;margin:0 6px 6px 0}
.fm{display:inline-block;width:26px;height:26px;line-height:26px;border-radius:7px;text-align:center;font-weight:800;font-size:13px;margin-right:3px;color:#fff}.fm.W{background:#1f9d55}.fm.D{background:#8a94a6}.fm.L{background:#c1121f}
.bar{display:flex;height:10px;border-radius:9px;overflow:hidden;background:#ffffff18}.bar i{display:block;background:#2d6cdf}.bar i+i{background:#ff3d6e}.me td{color:#ffd23f;font-weight:800}
.body table{width:100%}.list a{display:block;padding:8px 0;border-bottom:1px solid #ffffff14}.grid2{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:6px}</style>"""
def head(title, desc, url, ld):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{url}">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}"><meta property="og:site_name" content="HeyFootball">
<meta name="twitter:card" content="summary"><meta name="theme-color" content="#070b17">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet"><link rel="stylesheet" href="../blog/style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%E2%9A%BD%3C/text%3E%3C/svg%3E">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>{CSS}</head><body>
<header class="top"><div class="wrap"><a class="brand" href="../"><span>⚽ HEY<b>FOOTBALL</b></span><small>Football</small></a>
<nav aria-label="Main"><a href="../teams/">Teams</a><a href="../matches/">Matches</a><a href="../blog/">Blog</a><a class="play" href="../">Play free ▶</a></nav></div></header>
<main class="wrap">"""
def foot():
    return f"""</main><footer><div class="wrap"><p class="fine">Scores and tables from football-data.org, match stats from ESPN. Our predictions are for fun.
HeyFootball is a free fan-made football game and is not linked to any club, league or media outlet. <a href="../">Play HeyFootball</a> · <a href="../blog/">Blog</a> · <a href="../teams/">Teams</a> · <a href="../matches/">Matches</a></p></div></footer>
{HIT}
</body></html>"""
CTA = '<div class="cta"><div><h3>Think you know better?</h3><p>Predict real matches, open player packs and battle your friends. Free, in your browser, no download.</p></div><a class="btn" href="../?play=pred">Make your prediction ▶</a></div>'
tlink = lambda t: f'<a href="../teams/{team_slug[t]}.html">{esc(t)}</a>' if t in team_slug else esc(t)
mlink = lambda m, txt: f'<a href="../matches/{m["slug"]}.html">{txt}</a>'
def form_html(t):
    p = played(t)[:5]
    return "".join(f'<span class="fm {result(m, t)}" title="{esc(m["h"])} {m["hs"]}-{m["as"]} {esc(m["a"])}">{result(m, t)}</span>' for m in p[::-1]) or "–"

def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

# ---------- match pages ----------
for m in matches:
    lg = LEAGUES[m["c"]][0]; nice, day = when(m["t"]); url = f'{SITE}/matches/{m["slug"]}.html'
    gh, ga, ph, pd, pa = predict(m); s = stats.get(m["id"])
    status = {"ft": "Full time", "live": "🔴 Live now", "up": "Kick-off " + nice.split(", ")[1]}[m["st"]]
    title = f'{m["h"]} vs {m["a"]}: score, stats and predictions | HeyFootball'
    if m["st"] == "ft":
        desc = f'{m["h"]} {m["hs"]}-{m["as"]} {m["a"]} ({lg}, {nice.split(",")[0]}). Full-time score, match stats, form guide and head-to-head.'
    else:
        desc = f'{m["h"]} vs {m["a"]} ({lg}) on {nice} Lisbon time: our score prediction, team form, league table and head-to-head.'
    ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": f'{m["h"]} vs {m["a"]}', "sport": "Soccer", "startDate": m["t"],
          "eventStatus": "https://schema.org/EventScheduled", "description": desc, "url": url,
          "homeTeam": {"@type": "SportsTeam", "name": m["h"]}, "awayTeam": {"@type": "SportsTeam", "name": m["a"]},
          "superEvent": {"@type": "SportsEvent", "name": lg}}
    if m.get("v"): ld["location"] = {"@type": "Place", "name": m["v"]}
    b = [head(title, desc, url, ld)]
    b.append(f'<nav class="crumbs" aria-label="Breadcrumb"><a href="../">HeyFootball</a> › <a href="../matches/">Matches</a> › {esc(lg)}</nav><article class="post"><div class="post-head">')
    b.append(f'<span class="cat">{esc(lg)}</span><h1>{esc(m["h"])} vs {esc(m["a"])}</h1><p class="dek">{esc(status)} · {esc(nice)} (Lisbon time){" · 🏟️ " + esc(m["v"]) if m.get("v") else ""}</p></div><div class="body">')
    if m["st"] in ("ft", "live"):
        b.append(f'<div class="score"><span>{tlink(m["h"])}</span><b>{m["hs"]} - {m["as"]}</b><span>{tlink(m["a"])}</span></div>')
    else:
        b.append(f'<div class="score"><span>{tlink(m["h"])}</span><b>vs</b><span>{tlink(m["a"])}</span></div>')
    if s:
        rows = []
        for k, n, u in STAT_ROWS:
            a, z = s[0].get(k), s[1].get(k)
            if a is None and z is None: continue
            try: fa, fz = float(a or 0), float(z or 0)
            except ValueError: fa = fz = 0
            tot = (fa + fz) or 1
            rows.append(f'<tr><td><b>{esc(a or 0)}{u}</b></td><td style="width:55%"><small>{n}</small><div class="bar"><i style="width:{fa / tot * 100:.0f}%"></i><i style="width:{fz / tot * 100:.0f}%"></i></div></td><td style="text-align:right"><b>{esc(z or 0)}{u}</b></td></tr>')
        if rows: b.append(f'<h2>Match stats</h2><table>{"".join(rows)}</table>')
    b.append(f'<h2>{"Our prediction" if m["st"] == "up" else "What we predicted"}</h2>')
    b.append(f'<p>Based on both teams\' league form and home advantage, we {"expect" if m["st"] == "up" else "expected"} <strong>{esc(m["h"])} {gh}-{ga} {esc(m["a"])}</strong>.</p>')
    b.append(f'<p><span class="pill">🏠 {esc(m["h"])} win {ph}%</span><span class="pill">🤝 Draw {pd}%</span><span class="pill">✈️ {esc(m["a"])} win {pa}%</span></p>')
    if m["st"] == "ft":
        right = (gh, ga) == (m["hs"], m["as"]); res_ok = (gh > ga) == (m["hs"] > m["as"]) and (gh < ga) == (m["hs"] < m["as"])
        b.append(f'<p>{"🎯 We got the exact score!" if right else "✅ We got the result right." if res_ok else "❌ Not this time. Football!"}</p>')
    b.append('<h2>Form guide</h2><table><tr><th>Team</th><th>Last 5</th><th>League</th></tr>')
    for t in (m["h"], m["a"]):
        p_ = pos.get(t); lgpos = f'{p_[1]}{"th" if 10 <= p_[1] % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(p_[1] % 10, "th")} in {esc(p_[0])} · {p_[2][4]} pts' if p_ else "–"
        b.append(f'<tr><td>{tlink(t)}</td><td>{form_html(t)}</td><td>{lgpos}</td></tr>')
    b.append("</table>")
    h2h = [x for x in matches if x["st"] == "ft" and {x["h"], x["a"]} == {m["h"], m["a"]} and x["id"] != m["id"]][::-1][:5]
    if h2h:
        b.append('<h2>Head to head</h2><div class="list">' + "".join(mlink(x, f'{when(x["t"])[0].split(",")[0]} · {esc(x["h"])} {x["hs"]}-{x["as"]} {esc(x["a"])}') for x in h2h) + "</div>")
    b.append(CTA)
    more = [x for x in matches if x["c"] == m["c"] and x["id"] != m["id"] and abs((datetime.fromisoformat(x["t"].replace("Z", "+00:00")) - datetime.fromisoformat(m["t"].replace("Z", "+00:00"))).days) <= 3][:8]
    if more:
        b.append(f'<h2>More {esc(lg)} matches</h2><div class="list">' + "".join(mlink(x, f'{esc(x["h"])} {str(x["hs"]) + "-" + str(x["as"]) if x["st"] != "up" else "vs"} {esc(x["a"])}') for x in more) + "</div>")
    b.append("</div></article>" + foot())
    write(os.path.join(OUT, "matches", m["slug"] + ".html"), "".join(b))

# ---------- team pages ----------
for t in teams:
    url = f"{SITE}/teams/{team_slug[t]}.html"; p_ = pos.get(t); pl, nx = played(t), coming(t)
    title = f"{t}: results, fixtures, form and table | HeyFootball"
    desc = (f"{t} are {p_[1]} in the {p_[0]} with {p_[2][4]} points. " if p_ else f"{t}: ") + "Latest results, next matches, form guide and predictions."
    ld = {"@context": "https://schema.org", "@type": "SportsTeam", "name": t, "sport": "Soccer", "url": url}
    if p_: ld["memberOf"] = {"@type": "SportsOrganization", "name": p_[0]}
    b = [head(title, desc, url, ld), f'<nav class="crumbs" aria-label="Breadcrumb"><a href="../">HeyFootball</a> › <a href="../teams/">Teams</a> › {esc(t)}</nav><article class="post"><div class="post-head">']
    b.append(f'<span class="cat">{esc(p_[0]) if p_ else "Team"}</span><h1>{esc(t)}</h1><p class="dek">{esc(desc)}</p></div><div class="body">')
    b.append(f"<h2>Form</h2><p>{form_html(t)}</p>")
    if nx:
        b.append('<h2>Next matches</h2><div class="list">' + "".join(mlink(m, f'{"🔴 LIVE · " if m["st"] == "live" else ""}{when(m["t"])[0]} · {esc(m["h"])} vs {esc(m["a"])} · {esc(LEAGUES[m["c"]][0])}') for m in nx[:6]) + "</div>")
    if pl:
        b.append('<h2>Latest results</h2><div class="list">' + "".join(mlink(m, f'{result(m, t)} · {when(m["t"])[0].split(",")[0]} · {esc(m["h"])} {m["hs"]}-{m["as"]} {esc(m["a"])}') for m in pl[:10]) + "</div>")
    if p_:
        rows = tables[p_[0]]
        b.append(f'<h2>{esc(p_[0])} table</h2><table><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th></tr>')
        for i, r in enumerate(rows):
            gd = r[5] if len(r) > 5 and r[5] is not None else "-"
            b.append(f'<tr class="{"me" if r[0] == t else ""}"><td>{i + 1}</td><td>{tlink(r[0])}</td><td>{r[1] + r[2] + r[3]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{gd}</td><td><b>{r[4]}</b></td></tr>')
        b.append("</table>")
    b.append(CTA.replace("Make your prediction ▶", f"Play as a {esc(t)} fan ▶").replace("../?play=pred", "../"))
    b.append("</div></article>" + foot())
    write(os.path.join(OUT, "teams", team_slug[t] + ".html"), "".join(b))

# ---------- index pages ----------
ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Football teams | HeyFootball"}
b = [head("Football teams: results, fixtures and form | HeyFootball", "Every team in the Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Liga Portugal and the Champions League: results, fixtures, form and tables.", f"{SITE}/teams/", ld)]
b.append('<article class="post"><div class="post-head"><h1>Football teams</h1><p class="dek">Results, fixtures, form and league tables for every team.</p></div><div class="body">')
for code, (lg, _) in LEAGUES.items():
    ts = [r[0] for r in tables.get(lg, [])] or sorted({x for m in matches if m["c"] == code for x in (m["h"], m["a"])})
    if ts: b.append(f'<h2>{esc(lg)}</h2><div class="grid2">' + "".join(f'<a href="{team_slug[x]}.html">{esc(x)}</a>' for x in ts if x in team_slug) + "</div>")
b.append("</div></article>" + foot()); write(os.path.join(OUT, "teams", "index.html"), "".join(b))
ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Football matches | HeyFootball"}
b = [head("Football matches: scores, stats and predictions | HeyFootball", "Today's football matches, upcoming fixtures with our score predictions, and the latest results with full match stats.", f"{SITE}/matches/", ld)]
b.append('<article class="post"><div class="post-head"><h1>Football matches</h1><p class="dek">Upcoming games with our predictions, live scores and the latest results with stats.</p></div><div class="body">')
up = [m for m in matches if m["st"] in ("live", "up")][:60]; done = [m for m in matches if m["st"] == "ft"][::-1][:80]
if up: b.append('<h2>Coming up</h2><div class="list">' + "".join(mlink(m, f'{"🔴 LIVE · " if m["st"] == "live" else ""}{when(m["t"])[0]} · {esc(m["h"])} vs {esc(m["a"])} · {esc(LEAGUES[m["c"]][0])}') for m in up) + "</div>")
if done: b.append('<h2>Latest results</h2><div class="list">' + "".join(mlink(m, f'{when(m["t"])[0].split(",")[0]} · {esc(m["h"])} {m["hs"]}-{m["as"]} {esc(m["a"])} · {esc(LEAGUES[m["c"]][0])}') for m in done) + "</div>")
b.append(CTA + "</div></article>" + foot()); write(os.path.join(OUT, "matches", "index.html"), "".join(b))

# ---------- sitemap: the game, the blog, every team and match page ----------
urls = [(f"{SITE}/", "daily", "1.0")]
blog = os.path.join(OUT, "blog")
if os.path.isdir(blog):
    for f in sorted(os.listdir(blog)):
        if f.endswith(".html") and f != "post.html":
            urls.append((f"{SITE}/blog/" + ("" if f == "index.html" else f), "weekly", "0.8" if f == "index.html" else "0.7"))
urls += [(f"{SITE}/teams/", "daily", "0.8"), (f"{SITE}/matches/", "hourly", "0.8")]
urls += [(f"{SITE}/teams/{team_slug[t]}.html", "daily", "0.6") for t in teams]
urls += [(f'{SITE}/matches/{m["slug"]}.html', "hourly" if m["st"] != "ft" else "weekly", "0.6") for m in matches]
sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
sm += "".join(f"<url><loc>{esc(u)}</loc><lastmod>{TODAY}</lastmod><changefreq>{c}</changefreq><priority>{p}</priority></url>\n" for u, c, p in urls) + "</urlset>\n"
write(os.path.join(OUT, "sitemap.xml"), sm)
print(f"teams: {len(teams)} | matches: {len(matches)} | with stats: {sum(1 for v in stats.values() if v)} | sitemap urls: {len(urls)}")
