"""Playwright recon of pizzeria ordering sites from the CI runner.

Prints page structure (links, buttons, forms) so the ordering flow can be
scripted, and saves screenshots to shots/. Never places an order.
"""

from __future__ import annotations

import os
import re

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TARGETS = [
    ("nbp", "https://northbeachpizza.com/"),
    ("efny", "https://escapefromnewyorkpizza.com/"),
]

os.makedirs("shots", exist_ok=True)


def dump(page, tag: str) -> None:
    print(f"\n===== {tag}: {page.url}")
    print("title:", page.title())
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => [e.innerText.trim().slice(0,60), e.href])")
    seen = set()
    for text, href in links:
        if not text or href in seen:
            continue
        seen.add(href)
        if re.search(r"order|menu|deliver|cart|checkout|slice|toast|chownow|menufy|hungerrush|revention",
                     (text + href).lower()):
            print(f"  LINK [{text}] -> {href}")
    buttons = page.eval_on_selector_all(
        "button, [role=button], input[type=submit]",
        "els => els.map(e => e.innerText?.trim().slice(0,60) || e.value || '').filter(Boolean)")
    print("  buttons:", buttons[:25])
    forms = page.eval_on_selector_all(
        "form input, form select",
        "els => els.map(e => `${e.tagName}:${e.type||''}:${e.name||e.id||e.placeholder||''}`)")
    print("  form fields:", forms[:40])
    body = page.evaluate("document.body.innerText.slice(0, 1500)")
    print("  text head:", " ".join(body.split())[:900])


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 2000},
                                  locale="en-US")
        page = ctx.new_page()
        for tag, url in TARGETS:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                dump(page, tag)
                page.screenshot(path=f"shots/{tag}-home.jpg", quality=45, type="jpeg",
                                full_page=True)
                # Follow the most promising ordering link one hop.
                target = page.eval_on_selector_all(
                    "a[href]",
                    "els => { const m = els.find(e => /order/i.test(e.innerText) || /order/i.test(e.href)); return m ? m.href : null }")
                if target:
                    print(f"  following order link: {target}")
                    page.goto(target, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(4000)
                    dump(page, f"{tag}-order")
                    page.screenshot(path=f"shots/{tag}-order.jpg", quality=45, type="jpeg",
                                    full_page=True)
            except Exception as e:
                print(f"  !! {tag}: {type(e).__name__}: {e}")
        browser.close()


if __name__ == "__main__":
    main()
