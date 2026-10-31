"""Reads FENEGOSIDA gold (hallmark 24K) and silver rates per tola, plus spot XAU/XAG (USD/oz)
and USD->NPR, and records them in prices.json. A metal is only written if its Nepal rate looks valid."""
import json, re, sys, urllib.request
from datetime import datetime, timezone, timedelta

URL = "https://www.fenegosida.org/"
NPT = timezone(timedelta(hours=5, minutes=45))
TOLA_G = 11.6638
# step: published tola rates are multiples of this; lo/hi: sanity range for spot USD/oz
METALS = {
    "gold": dict(word="Gold", step=100, sym="XAU", lo=500, hi=20000),
    "silver": dict(word="Silver", step=5, sym="XAG", lo=5, hi=500),
}
GOLD_LABEL = r"(?:hall\s*mark|fine\s*gold|chhapawal|छापावाल)"


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


def to_tola(v, last, step):
    """The site shows either the per-tola or the per-10g rate."""
    if abs(v / last - 1) <= 0.10:
        return int(round(v / step)) * step
    t = v * TOLA_G / 10
    if abs(t / last - 1) <= 0.10:
        return int(round(t / step)) * step
    return None


def parse(text, last, metal):
    c = METALS[metal]
    t = re.sub(r"\s+", " ", text)
    rx = re.compile(r"\b" + c["word"] + r"\b[^0-9]{0,12}[\d.]+\s*%[^0-9]{0,12}(\d[\d,]*(?:\.\d+)?)", re.I)
    cands = [float(m.group(1).replace(",", "")) for m in rx.finditer(t)]
    if metal == "gold":
        for gap in (r"[^0-9]{0,60}?(?:tola|तोला)[^0-9]{0,40}?", r"[^0-9]{0,60}?"):
            for m in re.finditer(GOLD_LABEL + gap + r"(\d[\d,]{4,8})", t, re.I):
                cands.append(float(m.group(1).replace(",", "")))
    for v in cands:
        r = to_tola(v, last, c["step"])
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


def lists(d, metal):
    if metal == "gold":
        return d["np"], d["us"]
    s = d.setdefault("silver", {"np": [], "us": []})
    return s["np"], s["us"]


def upsert(lst, day, value):
    row = next((x for x in lst if x["d"] == day), None)
    if row:
        row["p"] = value
    else:
        lst.append({"d": day, "p": value})
    lst.sort(key=lambda x: x["d"])


def main():
    d = json.load(open("prices.json", encoding="utf-8"))
    vals = {}

    def scan(t):
        for m in METALS:
            if m in vals:
                continue
            npl, _ = lists(d, m)
            if npl:
                v = parse(t, npl[-1]["p"], m)
                if v:
                    vals[m] = v

    seen = raw_text()
    scan(seen)
    if len(vals) < len(METALS):
        t = rendered_text()
        seen += " " + t
        scan(t)
    for m in METALS:
        if m not in vals:
            print(f"WARNING: no valid {m} rate found.")
    if not vals:
        print("Could not find a valid rate. Text seen:\n", re.sub(r"\s+", " ", seen)[:1500])
        sys.exit(1)
    now = datetime.now(NPT)
    today = now.strftime("%Y-%m-%d")
    changed = False
    for m, v in vals.items():
        c = METALS[m]
        npl, usl = lists(d, m)
        row = next((x for x in npl if x["d"] == today), None)
        if row and row["p"] == v:
            print("No change:", m, v)
            continue
        upsert(npl, today, v)
        spot = num("https://api.gold-api.com/price/" + c["sym"], ["price"], c["lo"], c["hi"])
        if spot:
            upsert(usl, today, spot)
        print("Updated:", m, v, spot)
        changed = True
    if changed:
        fx = num("https://open.er-api.com/v6/latest/USD", ["rates", "NPR"], 50, 500)
        if fx:
            d["fx"] = round(fx, 2)
        d["updated"] = now.strftime("%Y-%m-%d %H:%M NPT")
        json.dump(d, open("prices.json", "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
