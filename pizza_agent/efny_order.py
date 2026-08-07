"""EFNY Downtown (FoodTec) pepperoni+jalapeño delivery order.

Walks: delivery -> PEPPERONI pizza CUSTOMIZE -> add jalapeños -> cart ->
guest checkout -> payment. Only submits the order when env PLACE=1;
otherwise stops at the payment screen and dumps everything it sees.
"""

from __future__ import annotations

import os
import re

from playwright.sync_api import sync_playwright

PLACE = os.environ.get("PLACE") == "1"
NAME_FIRST, NAME_LAST = "Sai Vivek", "Peddi"
PHONE = "5302207864"
EMAIL = "peddisaivivek999@gmail.com"
STREET = "3 Embarcadero Center"
APT = "Street level"
ZIP = "94111"
CITY = "San Francisco"
INSTRUCTIONS = ("Codi event space - AlphaSignal Pizza Agent Challenge. "
                "Look for PIZZA CHALLENGE signs. Call on arrival.")
MAX_TOTAL = 60.0

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
os.makedirs("shots", exist_ok=True)
STEP = 0


def snap(page, tag):
    global STEP
    STEP += 1
    p = f"shots/{STEP:02d}-{tag}.jpg"
    try:
        page.screenshot(path=p, quality=40, type="jpeg", full_page=True)
        print(f"[snap {p}] {page.url}")
    except Exception as e:
        print("[snap fail]", e)


def text_of(page, n=2500):
    try:
        return " ".join(page.evaluate("document.body.innerText").split())[:n]
    except Exception:
        return ""


def dump_controls(page, label):
    print(f"--- controls @ {label}")
    try:
        ctl = page.eval_on_selector_all(
            "input:not([type=hidden]), select, textarea, button, a[href*='cart' i], a[href*='checkout' i]",
            """els => els.map(e => {
                const t = e.tagName, ty = e.type || '';
                const name = e.name || e.id || e.placeholder || '';
                const txt = (e.innerText || e.value || '').trim().slice(0, 45);
                const lbl = e.labels && e.labels[0] ? e.labels[0].innerText.trim().slice(0,45) : '';
                return `${t}:${ty}:${name}:${txt||lbl}`;
            })""")
        for c in ctl[:70]:
            print("   ", c)
    except Exception as e:
        print("ctl err", e)


def click_rx(page, pattern, which=0, timeout=3500):
    try:
        page.get_by_text(re.compile(pattern, re.I)).nth(which).click(timeout=timeout)
        page.wait_for_timeout(1800)
        print(f"[clicked /{pattern}/i]")
        return True
    except Exception as e:
        print(f"[click /{pattern}/i failed {type(e).__name__}]")
        return False


def fill_any(page, hints, value):
    for h in hints:
        sel = f"input[name*='{h}' i], input[id*='{h}' i], input[placeholder*='{h}' i], textarea[name*='{h}' i], textarea[id*='{h}' i], textarea[placeholder*='{h}' i]"
        try:
            page.locator(sel).first.fill(value, timeout=1500)
            print(f"[filled '{h}' = {value[:40]}]")
            return True
        except Exception:
            continue
    print(f"[fill failed for {hints}]")
    return False


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 1600})
        ctx.set_default_timeout(4000)
        page = ctx.new_page()
        page.goto("https://escapefromny-downtown.foodtecsolutions.com/ordering/home",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)
        click_rx(page, r"no,? thanks")
        click_rx(page, r"^delivery$")
        snap(page, "delivery-selected")

        page.goto("https://escapefromny-downtown.foodtecsolutions.com/ordering/menu/Whole%20Pizzas",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        click_rx(page, r"^close$")

        # click CUSTOMIZE belonging to the plain PEPPERONI pizza card
        ok = page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button, a')]
                .filter(b => /customize/i.test(b.innerText || ''));
            for (const b of btns) {
                let e = b;
                for (let i = 0; i < 7; i++) {
                    e = e.parentElement;
                    if (!e) break;
                    const t = e.innerText || '';
                    if (/Red Sauce, Pepperoni and Mozzarella/i.test(t) && t.length < 600) {
                        b.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        print("[customize pepperoni clicked]" if ok else "[customize pepperoni NOT found]")
        page.wait_for_timeout(2500)
        snap(page, "customize-modal")
        print("modal text:", text_of(page, 2800))
        dump_controls(page, "customize-modal")

        # size: prefer Lg-18 for the crowd; fall back to whatever's selected
        for pat in (r"lg-?18", r"large"):
            if click_rx(page, pat):
                break
        # add jalapeños topping
        clicked_jal = False
        for sel in ("label:has-text('Jalape')", "text=/jalape/i"):
            try:
                page.locator(sel).first.click(timeout=2500)
                clicked_jal = True
                print(f"[jalapeño clicked via {sel}]")
                break
            except Exception:
                continue
        if not clicked_jal:
            print("[jalapeño NOT clicked]")
        page.wait_for_timeout(1200)
        snap(page, "after-toppings")
        print("modal text now:", text_of(page, 2000))

        click_rx(page, r"add to order")
        page.wait_for_timeout(2000)
        snap(page, "added")

        # find cart/checkout
        went = False
        for url in ("https://escapefromny-downtown.foodtecsolutions.com/ordering/cart",
                    "https://escapefromny-downtown.foodtecsolutions.com/ordering/checkout"):
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                if "cart" in page.url or "checkout" in page.url:
                    went = True
                    break
            except Exception as e:
                print("nav err", e)
        if not went:
            click_rx(page, r"(checkout|view order|cart)")
        click_rx(page, r"^close$")
        snap(page, "cart")
        print("cart text:", text_of(page, 2500))
        dump_controls(page, "cart")
        click_rx(page, r"check ?out")
        page.wait_for_timeout(2500)
        snap(page, "checkout-1")
        print("checkout text:", text_of(page, 3000))
        dump_controls(page, "checkout-1")

        # guest path if offered
        click_rx(page, r"(guest|continue without|no account)")

        # contact + address
        fill_any(page, ("first"), NAME_FIRST) if False else None
        fill_any(page, ["first"], NAME_FIRST)
        fill_any(page, ["last"], NAME_LAST)
        fill_any(page, ["name"], f"{NAME_FIRST} {NAME_LAST}")
        fill_any(page, ["email"], EMAIL)
        fill_any(page, ["phone"], PHONE)
        fill_any(page, ["street", "address1", "address"], STREET)
        fill_any(page, ["apt", "suite", "unit", "address2"], APT)
        fill_any(page, ["zip", "postal"], ZIP)
        fill_any(page, ["city"], CITY)
        fill_any(page, ["instruction", "note", "comment"], INSTRUCTIONS)
        page.wait_for_timeout(1000)
        snap(page, "checkout-filled")
        dump_controls(page, "checkout-filled")

        # payment: prefer cash
        cash = False
        for pat in (r"cash", r"pay at (the )?(door|store|delivery)", r"pay in person"):
            if click_rx(page, pat):
                cash = True
                break
        print(f"[cash selected: {cash}]")
        body = text_of(page, 3500)
        print("payment area text:", body)
        snap(page, "payment")

        m = re.search(r"total[^$]*\$([0-9]+\.[0-9]{2})", body, re.I)
        total = float(m.group(1)) if m else None
        print(f"[detected total: {total}]")

        if not PLACE:
            print("[DRY MODE — stopping before placing order]")
            browser.close()
            return
        if not cash:
            print("[ABORT — cash not available, refusing to place]")
            browser.close()
            return
        if total is not None and total > MAX_TOTAL:
            print(f"[ABORT — total ${total} exceeds cap ${MAX_TOTAL}]")
            browser.close()
            return

        for pat in (r"place order", r"submit order", r"finish", r"complete order"):
            if click_rx(page, pat, timeout=6000):
                break
        page.wait_for_timeout(6000)
        snap(page, "after-place")
        print("FINAL PAGE TEXT:", text_of(page, 3000))
        browser.close()


if __name__ == "__main__":
    main()
