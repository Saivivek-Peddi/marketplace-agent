"""EFNY Downtown (FoodTec) pepperoni+jalapeño delivery order — DOM-surgical version.

Env PLACE=1 submits for real; otherwise dry (stops at payment, dumps all)."""

from __future__ import annotations

import os
import re

from playwright.sync_api import sync_playwright

PLACE = os.environ.get("PLACE") == "1"
PHONE = "5302207864"
EMAIL = "peddisaivivek999@gmail.com"
INSTRUCTIONS = ("Codi event space - AlphaSignal Pizza Agent Challenge. "
                "Look for PIZZA CHALLENGE signs. Call on arrival.")
MAX_TOTAL = 60.0
BASE = "https://escapefromny-downtown.foodtecsolutions.com"

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


def body_text(page, n=2500):
    try:
        return " ".join(page.evaluate("document.body.innerText").split())[:n]
    except Exception:
        return ""


def dialog_text(page, n=2500):
    try:
        return page.evaluate("""() => {
            const d = document.querySelector("[role=dialog], .modal.show, .modal[style*=block], .ReactModal__Content");
            return d ? d.innerText.slice(0, %d) : "";
        }""" % n)
    except Exception:
        return ""


def click_rx(page, pattern, which=0, timeout=3500):
    try:
        page.get_by_text(re.compile(pattern, re.I)).nth(which).click(timeout=timeout)
        page.wait_for_timeout(1800)
        print(f"[clicked /{pattern}/i]")
        return True
    except Exception as e:
        print(f"[click /{pattern}/i failed {type(e).__name__}]")
        return False


def js_click_in_card(page, card_marker, btn_pattern):
    return page.evaluate("""([marker, pat]) => {
        const rx = new RegExp(pat, 'i');
        const btns = [...document.querySelectorAll('button, a, input[type=submit]')]
            .filter(b => rx.test(b.innerText || b.value || ''));
        for (const b of btns) {
            let e = b;
            for (let i = 0; i < 8; i++) {
                e = e.parentElement;
                if (!e) break;
                const t = e.innerText || '';
                if (t.includes(marker) && t.length < 800) { b.click(); return true; }
            }
        }
        return false;
    }""", [card_marker, btn_pattern])


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 1600})
        ctx.set_default_timeout(4000)
        page = ctx.new_page()
        page.goto(f"{BASE}/ordering/home", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)
        click_rx(page, r"no,? thanks")
        click_rx(page, r"^delivery$")
        snap(page, "delivery")

        page.goto(f"{BASE}/ordering/menu/Whole%20Pizzas", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        click_rx(page, r"^close$")

        # header/nav discovery: all links + labeled buttons
        try:
            nav = page.evaluate("""() => ({
                links: [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).slice(0, 60),
                labeled: [...document.querySelectorAll('button, a')]
                    .map(b => `${b.id||''}|${b.getAttribute('aria-label')||''}|${(b.className||'').toString().slice(0,40)}`)
                    .filter(s => /cart|order|check|bag|basket/i.test(s)).slice(0, 30),
            })""")
            print("NAV:", nav)
        except Exception as e:
            print("nav err", e)

        # size Lg-18 on the PEPPERONI card
        ok = page.evaluate("""() => {
            const sels = [...document.querySelectorAll('select')];
            for (const s of sels) {
                let e = s;
                for (let i = 0; i < 8; i++) {
                    e = e.parentElement;
                    if (!e) break;
                    const t = e.innerText || '';
                    if (t.includes('Red Sauce, Pepperoni and Mozzarella') && t.length < 800) {
                        const opt = [...s.options].find(o => /lg-?18/i.test(o.text));
                        if (opt) { s.value = opt.value; s.dispatchEvent(new Event('change', {bubbles: true})); return opt.text; }
                    }
                }
            }
            return null;
        }""")
        print(f"[pepperoni size set: {ok}]")

        clicked = js_click_in_card(page, "Red Sauce, Pepperoni and Mozzarella", "customize")
        print(f"[customize clicked: {clicked}]")
        page.wait_for_timeout(5000)
        snap(page, "customize")
        dt = dialog_text(page, 3000)
        print("DIALOG:", dt if dt else "(no dialog found)")
        if not dt:
            print("page text:", body_text(page, 1500))
            print("URL now:", page.url)

        # jalapeño checkbox inside dialog (or page)
        jal = page.evaluate("""() => {
            const scope = document.querySelector("[role=dialog], .modal.show, .ReactModal__Content") || document;
            const els = [...scope.querySelectorAll('label, input, span, div')]
                .filter(e => /jalape/i.test(e.innerText || e.value || ''));
            for (const e of els) {
                const box = e.querySelector && e.querySelector("input[type=checkbox]");
                const target = box || e;
                try { target.click(); return (e.innerText || '').slice(0, 60); } catch (err) {}
            }
            return null;
        }""")
        print(f"[jalapeño: {jal}]")
        page.wait_for_timeout(1200)
        snap(page, "jalapeno")
        print("DIALOG after topping:", dialog_text(page, 1500))

        # ADD TO ORDER inside dialog first, else pepperoni card
        added = page.evaluate("""() => {
            const scope = document.querySelector("[role=dialog], .modal.show, .ReactModal__Content");
            if (scope) {
                const b = [...scope.querySelectorAll('button, input[type=submit]')]
                    .find(b => /add to order/i.test(b.innerText || b.value || ''));
                if (b) { b.click(); return 'dialog'; }
            }
            return null;
        }""")
        if not added:
            added = 'card' if js_click_in_card(page, "Red Sauce, Pepperoni and Mozzarella", "add to order") else None
        print(f"[added via: {added}]")
        page.wait_for_timeout(3000)
        snap(page, "after-add")
        print("after-add text:", body_text(page, 1800))
        print("after-add dialog:", dialog_text(page, 1500))

        # follow whatever checkout affordance now exists
        for pat in (r"check ?out", r"view order", r"go to order", r"review order"):
            if click_rx(page, pat):
                break
        page.wait_for_timeout(3000)
        snap(page, "post-add-nav")
        print("URL:", page.url)
        print("checkout text:", body_text(page, 3000))

        # guest checkout
        click_rx(page, r"(guest|continue without|no account)")

        def fill_any(hints, value):
            for h in hints:
                sel = (f"input[name*='{h}' i], input[id*='{h}' i], input[placeholder*='{h}' i], "
                       f"textarea[name*='{h}' i], textarea[id*='{h}' i], textarea[placeholder*='{h}' i]")
                try:
                    page.locator(sel).first.fill(value, timeout=1500)
                    print(f"[filled {h}]")
                    return True
                except Exception:
                    continue
            print(f"[fill failed {hints}]")
            return False

        fill_any(["first"], "Sai Vivek")
        fill_any(["last"], "Peddi")
        fill_any(["email"], EMAIL)
        fill_any(["phone"], PHONE)
        fill_any(["street", "address"], "3 Embarcadero Center")
        fill_any(["apt", "suite", "unit"], "Street level")
        fill_any(["zip", "postal"], "94111")
        fill_any(["city"], "San Francisco")
        fill_any(["instruction", "note", "comment"], INSTRUCTIONS)
        snap(page, "filled")
        try:
            ctl = page.eval_on_selector_all(
                "input:not([type=hidden]), select, textarea, button",
                "els => els.map(e => `${e.tagName}:${e.type||''}:${e.name||e.id||e.placeholder||''}:${(e.innerText||e.value||'').trim().slice(0,40)}`)")
            print("controls:", ctl[:60])
        except Exception as e:
            print(e)

        cash = any(click_rx(page, p) for p in
                   (r"\bcash\b", r"pay at (the )?(door|store)", r"pay in person"))
        print(f"[cash: {cash}]")
        body = body_text(page, 3500)
        print("payment page:", body)
        snap(page, "payment")
        m = re.search(r"total[^$]*\$([0-9]+\.[0-9]{2})", body, re.I)
        total = float(m.group(1)) if m else None
        print(f"[total: {total}]")

        if not PLACE:
            print("[DRY MODE — stopping before placing]")
        elif not cash:
            print("[ABORT — no cash option]")
        elif total is not None and total > MAX_TOTAL:
            print(f"[ABORT — ${total} > ${MAX_TOTAL}]")
        else:
            for pat in (r"place order", r"submit order", r"complete order", r"finish"):
                if click_rx(page, pat, timeout=6000):
                    break
            page.wait_for_timeout(7000)
            snap(page, "placed")
            print("FINAL:", body_text(page, 3000))
        browser.close()


if __name__ == "__main__":
    main()
