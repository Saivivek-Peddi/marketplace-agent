"""Step through EFNY (FoodTec) and North Beach Pizza (OrderSave) delivery flows
up to the address/zone check. Dumps structure + screenshots. Places no order."""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
os.makedirs("shots", exist_ok=True)
STEP = 0


def snap(page, tag):
    global STEP
    STEP += 1
    path = f"shots/{STEP:02d}-{tag}.jpg"
    page.screenshot(path=path, quality=45, type="jpeg", full_page=True)
    print(f"[snap {path}] url={page.url}")


def dump(page, label):
    print(f"\n===== {label} :: {page.url}")
    try:
        print("title:", page.title())
        buttons = page.eval_on_selector_all(
            "button, [role=button], input[type=submit], a.btn",
            "els => els.map(e => (e.innerText||e.value||'').trim().slice(0,50)).filter(Boolean)")
        print("buttons:", buttons[:40])
        fields = page.eval_on_selector_all(
            "input:not([type=hidden]), select, textarea",
            "els => els.map(e => `${e.tagName}:${e.type||''}:${e.name||e.id||e.placeholder||''}`)")
        print("fields:", fields[:40])
        text = page.evaluate("document.body.innerText")
        low = text.lower()
        for kw in ("cash", "delivery", "pepperoni", "jalape", "minimum", "zone", "we do not deliver",
                   "guest", "sign in"):
            if kw in low:
                i = low.find(kw)
                print(f"  kw[{kw}]: ...{' '.join(text[max(0,i-70):i+90].split())}...")
    except Exception as e:
        print("dump error:", e)


def try_click(page, texts, timeout=4000):
    for t in texts:
        for sel in (f"button:has-text('{t}')", f"[role=button]:has-text('{t}')",
                    f"a:has-text('{t}')", f"text='{t}'"):
            try:
                page.locator(sel).first.click(timeout=timeout)
                page.wait_for_timeout(2500)
                print(f"[clicked '{t}' via {sel}]")
                return True
            except Exception:
                continue
    print(f"[no click match among {texts}]")
    return False


def try_fill(page, hints, value):
    for h in hints:
        for sel in (f"input[name*='{h}' i]", f"input[id*='{h}' i]", f"input[placeholder*='{h}' i]"):
            try:
                page.locator(sel).first.fill(value, timeout=2500)
                print(f"[filled {sel} = {value}]")
                return True
            except Exception:
                continue
    print(f"[no field match among {hints}]")
    return False


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 1400},
                                  locale="en-US")
        page = ctx.new_page()

        # --- EFNY downtown (FoodTec) ---
        try:
            page.goto("https://escapefromny-downtown.foodtecsolutions.com/",
                      wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            dump(page, "efny-landing")
            snap(page, "efny-landing")
            try_click(page, ["Delivery", "Start Order", "Order Now", "Order Online"])
            dump(page, "efny-after-delivery-click")
            snap(page, "efny-after-delivery")
            # address form, if presented
            try_fill(page, ["street", "address", "addr"], "3 Embarcadero Center")
            try_fill(page, ["zip", "postal"], "94111")
            try_fill(page, ["city"], "San Francisco")
            try_fill(page, ["apt", "suite", "unit"], "Street Level - Codi")
            try_click(page, ["Continue", "Start Order", "Submit", "Go", "Search", "Next"])
            dump(page, "efny-after-address")
            snap(page, "efny-after-address")
        except Exception as e:
            print("EFNY error:", type(e).__name__, e)

        # --- North Beach Pizza Grant Ave (OrderSave) ---
        try:
            page.goto("https://northbeachpizza.com/menu/northbeachpizzagrant?dialogState=orderDetails",
                      wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            dump(page, "nbp-order-dialog")
            snap(page, "nbp-order-dialog")
            try_click(page, ["Delivery"])
            dump(page, "nbp-after-delivery")
            try_fill(page, ["address", "street", "search"], "3 Embarcadero Center, San Francisco, CA 94111")
            page.wait_for_timeout(2500)
            snap(page, "nbp-address-typed")
            # autocomplete dropdown, pick first suggestion
            try_click(page, ["3 Embarcadero", "Embarcadero"])
            dump(page, "nbp-after-address")
            snap(page, "nbp-after-address")
        except Exception as e:
            print("NBP error:", type(e).__name__, e)

        browser.close()


if __name__ == "__main__":
    main()
