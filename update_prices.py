"""Reads the FENEGOSIDA hallmark (24K fine) gold rate per tola and records it in prices.json,
together with spot XAU/USD and USD->NPR. Writes nothing unless the Nepal rate looks valid."""
import json, re, sys, urllib.request
from datetime import datetime, timezone, timedelta

URL = "https://www.fenegosida.org/"
NPT = timezone(timedelta(hours=5, minutes=45))
LABEL = r"(?:hall\s*mark|fine\s*gold|chhapawal|छापावाल)"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")


def raw_text():
    try:
        html = get(URL)
        return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
    except Exception as e:
        print("raw fetch failed:", e)
        return ""


def rendered_text():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(URL, wait_until="networkidle", timeout=45000)
        pg.wait_for_timeout(3000)
        t = pg.inner_text("body")
        b.close()
        return t


GOLD_RE = re.compile(r"\bGold\b[^0-9]{0,12}[\d.]+\s*%[^0-9]{0,12}(\d[\d,]*(?:\.\d+)?)", re.I)


def to_tola(v, last):
    """The site shows either the per-tola or the per-10g rate; tola rates are multiples of 100."""
    if abs(v / last - 1) <= 0.10:
        return int(round(v / 100.0)) * 100
    t = v * 11.6638 / 10
    if abs(t / last - 1) <= 0.10:
        return int(round(t / 100.0)) * 100
    return None


def parse(text, last):
    t = re.sub(r"\s+", " ", text)
    cands = [float(m.group(1).replace(",", "")) for m in GOLD_RE.finditer(t)]
    for gap in (r"[^0-9]{0,60}?(?:tola|तोला)[^0-9]{0,40}?", r"[^0-9]{0,60}?"):
        for m in re.finditer(LABEL + gap + r"(\d[\d,]{4,8})", t, re.I):
            cands.append(float(m.group(1).replace(",", "")))
    for v in cands:
        r = to_tola(v, last)
        if r:
            return r
    return None


def num(url, path, lo, hi):
    try:
        j = json.loads(get(url))
        for k in path:
            j = j[k]
        v = float(j)
        return v if lo < v < hi else None
    except Exception as e:
        print("skip", url, e)
        return None


def main():
    d = json.load(open("prices.json", encoding="utf-8"))
    last = d["np"][-1]["p"]
    seen = raw_text()
    v = parse(seen, last)
    if not v:
        t = rendered_text()
        seen += " " + t
        v = parse(t, last)
    if not v:
        print("Could not find a valid gold rate. Text seen:\n", re.sub(r"\s+", " ", seen)[:1500])
        sys.exit(1)
    now = datetime.now(NPT)
    today = now.strftime("%Y-%m-%d")
    row = next((x for x in d["np"] if x["d"] == today), None)
    if row and row["p"] == v:
        print("No change:", v)
        return
    if row:
        row["p"] = v
    else:
        d["np"].append({"d": today, "p": v})
    spot = num("https://api.gold-api.com/price/XAU", ["price"], 500, 20000)
    fx = num("https://open.er-api.com/v6/latest/USD", ["rates", "NPR"], 50, 500)
    if spot:
        r = next((x for x in d["us"] if x["d"] == today), None)
        if r:
            r["p"] = spot
        else:
            d["us"].append({"d": today, "p": spot})
    if fx:
        d["fx"] = round(fx, 2)
    for k in ("np", "us"):
        d[k].sort(key=lambda x: x["d"])
    d["updated"] = now.strftime("%Y-%m-%d %H:%M NPT")
    json.dump(d, open("prices.json", "w", encoding="utf-8"), indent=1)
    print("Updated:", v, spot, fx)


if __name__ == "__main__":
    main()
