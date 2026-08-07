"""Recon from the CI runner: find pizzerias that deliver to the Financial District
with guest-friendly online ordering. Prints findings, orders nothing."""

from __future__ import annotations

import gzip
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
      "Accept-Encoding": "gzip"}

MARKERS = ("slice", "menufy", "chownow", "toasttab", "square", "beyondmenu",
           "grubhub", "doordash", "cash", "checkout", "order online")


def fetch(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw.decode(errors="replace")
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def ddg(query: str, n: int = 8) -> list[str]:
    status, html = fetch("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query))
    if status != 200:
        print(f"  [ddg {status}] {html[:200]}")
        return []
    links = re.findall(r'uddg=([^&"]+)', html)
    out = []
    for l in links[:n]:
        out.append(urllib.parse.unquote(l))
    return out


def probe_site(url: str) -> None:
    status, html = fetch(url)
    if status != 200:
        print(f"  {url} -> {status} {html[:120]}")
        return
    low = html.lower()
    hits = sorted({m for m in MARKERS if m in low})
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    print(f"  {url} -> 200 title={title.group(1).strip()[:80] if title else '?'} markers={hits}")


def main() -> None:
    print("=== search: pizza delivery FiDi ===")
    for q in (
        "north beach pizza san francisco order online",
        "pizza delivery \"financial district\" san francisco pay cash",
        "slice pizzeria delivery 94111 embarcadero",
    ):
        print(f"[q] {q}")
        for link in ddg(q):
            print("   ", link)

    print("\n=== probe known candidates ===")
    for url in (
        "https://www.northbeachpizza.com/",
        "https://slicelife.com/pizzerias/ca/san-francisco",
        "https://api.slicelife.com/services/core/restaurants?zip=94111",
    ):
        probe_site(url)


if __name__ == "__main__":
    main()
