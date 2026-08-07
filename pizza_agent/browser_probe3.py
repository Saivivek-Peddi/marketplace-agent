"""EFNY Downtown (FoodTec) deep probe: delivery -> menu -> pepperoni+jalapeño ->
cart -> checkout. Dumps payment options. Places NO order."""

from __future__ import annotations

import os
import re

from playwright.sync_api import sync_playwright

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


def text_dump(page, label, n=2200):
    try:
        t = " ".join(page.evaluate("document.body.innerText").split())
        print(f"--- {label} text: {t[:n]}")
    except Exception as e:
        print("dump err", e)


def rx(page, pattern):
    return page.get_by_text(re.compile(pattern, re.I))


def click_rx(page, pattern, which=0):
    try:
        loc = rx(page, pattern)
        loc.nth(which).click(timeout=3000)
        page.wait_for_timeout(2000)
        print(f"[clicked /{pattern}/i #{which}]")
        return True
    except Exception as e:
        print(f"[click /{pattern}/i failed: {type(e).__name__}]")
        return False


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 1400})
        ctx.set_default_timeout(4000)
        page = ctx.new_page()
        page.goto("https://escapefromny-downtown.foodtecsolutions.com/ordering/home",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        click_rx(page, r"no,? thanks")
        snap(page, "start")

        # choose DELIVERY radio (click its label text)
        click_rx(page, r"^delivery$")
        page.wait_for_timeout(1500)
        text_dump(page, "after-delivery-radio", 1200)
        snap(page, "after-delivery")

        # address form may pop; dump fields
        try:
            fields = page.eval_on_selector_all(
                "input:not([type=hidden]), select",
                "els => els.map(e => `${e.tagName}:${e.type||''}:${e.name||e.id||e.placeholder||''}`)")
            print("fields now:", fields)
        except Exception as e:
            print(e)
        # try filling any address-ish fields
        for hint, val in (("street", "3 Embarcadero Center"), ("address", "3 Embarcadero Center"),
                          ("zip", "94111"), ("city", "San Francisco"), ("apt", "Codi space")):
            try:
                page.locator(f"input[name*='{hint}' i], input[id*='{hint}' i], input[placeholder*='{hint}' i]").first.fill(val, timeout=1500)
                print(f"[filled {hint}]")
            except Exception:
                pass
        snap(page, "address-form")
        click_rx(page, r"^(continue|save|start order|ok|done)")
        text_dump(page, "after-address", 1000)
        snap(page, "after-address")

        # menu
        if not click_rx(page, r"^menu$"):
            page.goto("https://escapefromny-downtown.foodtecsolutions.com/ordering/menu",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        text_dump(page, "menu", 2500)
        snap(page, "menu")

        # find pizza category then a pepperoni-friendly item
        click_rx(page, r"pizza")
        page.wait_for_timeout(2000)
        text_dump(page, "pizza-category", 2500)
        snap(page, "pizza-category")

        for pat in (r"create your own", r"build your own", r"pepperoni"):
            if click_rx(page, pat):
                break
        page.wait_for_timeout(2000)
        text_dump(page, "item-page", 2500)
        snap(page, "item-page")

        # toppings: look for pepperoni & jalapeno checkboxes
        for top in (r"pepperoni", r"jalape"):
            try:
                el = rx(page, top).nth(0)
                el.click(timeout=2500)
                print(f"[topping clicked: {top}]")
                page.wait_for_timeout(800)
            except Exception as e:
                print(f"[topping {top} failed {type(e).__name__}]")
        snap(page, "toppings")

        click_rx(page, r"add to (order|cart)")
        text_dump(page, "after-add", 1200)
        snap(page, "after-add")

        # go to cart / checkout
        for pat in (r"checkout", r"view (order|cart)", r"my order"):
            if click_rx(page, pat):
                break
        page.wait_for_timeout(2500)
        text_dump(page, "cart", 2000)
        snap(page, "cart")
        click_rx(page, r"checkout")
        page.wait_for_timeout(2500)
        text_dump(page, "checkout", 3000)
        snap(page, "checkout")
        try:
            fields = page.eval_on_selector_all(
                "input:not([type=hidden]), select, label",
                "els => els.map(e => `${e.tagName}:${e.type||''}:${e.name||e.id||e.placeholder||(e.innerText||'').trim().slice(0,40)}`)")
            print("checkout fields:", fields[:60])
        except Exception as e:
            print(e)
        browser.close()


if __name__ == "__main__":
    main()
