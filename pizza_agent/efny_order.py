"""EFNY Downtown (FoodTec): large pepperoni + jalapeño, delivery, cash at door.

Handles the order-type modal, the CUSTOMIZE toppings UI, guest-or-signup
checkout. Env PLACE=1 places for real ONLY if all guards pass:
cart shows pepperoni AND jalapeño, cash payment selected, total <= $60.
"""

from __future__ import annotations

import os
import re

from playwright.sync_api import sync_playwright

PLACE = os.environ.get("PLACE") == "1"
PHONE = "5302207864"
EMAIL = "peddisaivivek999@gmail.com"
PASSWORD = "PizzaAgent2026!"
INSTRUCTIONS = ("Codi event space - AlphaSignal Pizza Agent Challenge. "
                "Look for PIZZA CHALLENGE signs. Call on arrival.")
MAX_TOTAL = 60.0
BASE = "https://escapefromny-downtown.foodtecsolutions.com"
CARD = "Red Sauce, Pepperoni and Mozzarella"

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


def dlg(page):
    try:
        return page.evaluate("""() => {
            const ds = [...document.querySelectorAll("[role=dialog], .modal.show, .modal[style*=block]")]
                .filter(d => d.offsetParent !== null || d.getClientRects().length);
            return ds.length ? ds[ds.length-1].innerText.slice(0, 2000) : "";
        }""")
    except Exception:
        return ""


def click_rx(page, pattern, which=0, timeout=3000, scope_dialog=False):
    try:
        base = page.locator("[role=dialog], .modal.show").last if scope_dialog else page
        base.get_by_text(re.compile(pattern, re.I)).nth(which).click(timeout=timeout)
        page.wait_for_timeout(1500)
        print(f"[clicked /{pattern}/i dialog={scope_dialog}]")
        return True
    except Exception as e:
        print(f"[click /{pattern}/i dialog={scope_dialog} failed {type(e).__name__}]")
        return False


def resolve_order_type(page):
    d = dlg(page)
    if "How would you like to order" in d or "order type" in d.lower():
        click_rx(page, r"^delivery$", scope_dialog=True)
        click_rx(page, r"^asap", scope_dialog=True)
        click_rx(page, r"continue ordering", scope_dialog=True)
        page.wait_for_timeout(2000)
        print("[order-type modal resolved]")
        return True
    return False


def js_click_in_card(page, marker, btn_pattern):
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
    }""", [marker, btn_pattern])


def fill_any(page, hints, value):
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


def dump_controls(page, label, n=70):
    print(f"--- controls @ {label}")
    try:
        ctl = page.eval_on_selector_all(
            "input:not([type=hidden]), select, textarea, button, a[href]",
            """els => els.filter(e => e.offsetParent !== null).map(e => {
                const lbl = e.labels && e.labels[0] ? e.labels[0].innerText.trim().slice(0,40) : '';
                return `${e.tagName}:${e.type||''}:${e.name||e.id||e.placeholder||''}:${(e.innerText||e.value||'').trim().slice(0,40)||lbl}`;
            })""")
        for c in ctl[:n]:
            print("   ", c)
    except Exception as e:
        print("ctl err", e)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 1600})
        ctx.set_default_timeout(3500)
        page = ctx.new_page()

        page.goto(f"{BASE}/ordering/menu/Whole%20Pizzas", wait_until="domcontentloaded",
                  timeout=45000)
        page.wait_for_timeout(3500)
        click_rx(page, r"no,? thanks")
        click_rx(page, r"^close$")

        # set Lg-18 on pepperoni card
        size = page.evaluate("""(marker) => {
            for (const s of document.querySelectorAll('select')) {
                let e = s;
                for (let i = 0; i < 8; i++) {
                    e = e.parentElement;
                    if (!e) break;
                    const t = e.innerText || '';
                    if (t.includes(marker) && t.length < 800) {
                        const opt = [...s.options].find(o => /lg-?18/i.test(o.text));
                        if (opt) { s.value = opt.value; s.dispatchEvent(new Event('change', {bubbles:true})); return opt.text; }
                    }
                }
            }
            return null;
        }""", CARD)
        print(f"[size: {size}]")

        # trigger order-type modal via CUSTOMIZE, resolve, land in toppings UI
        print(f"[customize: {js_click_in_card(page, CARD, 'customize')}]")
        page.wait_for_timeout(2500)
        if resolve_order_type(page):
            # customize may need re-click after modal
            page.wait_for_timeout(1500)
            if not dlg(page):
                print(f"[customize again: {js_click_in_card(page, CARD, 'customize')}]")
                page.wait_for_timeout(2500)
        snap(page, "customize")
        d = dlg(page)
        print("CUSTOMIZE DIALOG:", d[:2000] if d else "(none)")
        if not d:
            print("page:", body_text(page, 1200))

        # size + jalapeño inside customize UI
        click_rx(page, r"lg-?18", scope_dialog=True)
        jal = page.evaluate("""() => {
            const scope = [...document.querySelectorAll("[role=dialog], .modal.show")].pop() || document;
            const cands = [...scope.querySelectorAll('label, li, div, span')]
                .filter(e => /jalape/i.test(e.innerText || '') && (e.innerText || '').length < 60);
            for (const c of cands) {
                const box = c.querySelector('input[type=checkbox]') ||
                            (c.htmlFor ? document.getElementById(c.htmlFor) : null);
                try { (box || c).click(); return c.innerText.trim().slice(0, 50); } catch (e) {}
            }
            return null;
        }""")
        print(f"[jalapeño: {jal}]")
        page.wait_for_timeout(1000)
        snap(page, "toppings")
        print("dialog now:", dlg(page)[:1200])

        # add from dialog
        added = page.evaluate("""() => {
            const scope = [...document.querySelectorAll("[role=dialog], .modal.show")].pop();
            if (!scope) return null;
            const b = [...scope.querySelectorAll('button, input[type=submit]')]
                .find(b => /add to order/i.test(b.innerText || b.value || ''));
            if (b) { b.click(); return true; }
            return false;
        }""")
        print(f"[dialog add: {added}]")
        if added is None:
            print(f"[card add: {js_click_in_card(page, CARD, 'add to order')}]")
            page.wait_for_timeout(2000)
            resolve_order_type(page)
            print(f"[card add 2: {js_click_in_card(page, CARD, 'add to order')}]")
        page.wait_for_timeout(3000)
        snap(page, "added")
        print("after add:", body_text(page, 1500))
        dump_controls(page, "after-add", 40)

        # checkout
        if not click_rx(page, r"check ?out"):
            page.evaluate("""() => {
                const b = [...document.querySelectorAll('button, a')]
                    .find(b => /checkout|view order/i.test(b.innerText || ''));
                if (b) b.click();
            }""")
            page.wait_for_timeout(2500)
        page.wait_for_timeout(2500)
        snap(page, "checkout")
        print("CHECKOUT URL:", page.url)
        print("CHECKOUT:", body_text(page, 3000))
        dump_controls(page, "checkout")

        # ---- Checkout details page (guest form + delivery address) ----
        if "checkout" not in page.url:
            page.goto(f"{BASE}/ordering/checkout/details", wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

        def fill_exact(name, value):
            try:
                page.locator(f"input[name='{name}'], textarea[name='{name}']").first.fill(value, timeout=2000)
                print(f"[filled {name}]")
                return True
            except Exception as e:
                print(f"[fill {name} failed {type(e).__name__}]")
                return False

        fill_exact("firstName", "Sai Vivek")
        fill_exact("lastName", "Peddi")
        fill_exact("email", EMAIL)
        fill_exact("guestPhone", PHONE)
        # untick marketing spam if on
        for cb in ("subscribe", "smsMarketing"):
            try:
                page.locator(f"input[name='{cb}']").first.uncheck(timeout=1200)
            except Exception:
                pass
        try:
            page.select_option("select[name='addressType']", label="Business", timeout=3000)
            print("[addressType=Business]")
        except Exception as e:
            print("[addressType failed]", e)
        page.wait_for_timeout(2500)
        snap(page, "address-type")
        dump_controls(page, "address-form", 60)
        # address fields revealed after type selection
        fill_any(page, ["business", "company", "organization"], "Codi - AlphaSignal Pizza Challenge")
        fill_any(page, ["street", "address"], "3 Embarcadero Center")
        fill_any(page, ["suite", "apt", "unit", "floor"], "Street level")
        fill_any(page, ["zip", "postal"], "94111")
        fill_any(page, ["city"], "San Francisco")
        fill_any(page, ["cross"], "Sacramento St & Front St")
        fill_any(page, ["instruction", "note", "comment"], INSTRUCTIONS)
        snap(page, "details-filled")
        try:
            page.locator("#continue-to-order-details-btn").click(timeout=4000)
            print("[continue to order details]")
        except Exception:
            click_rx(page, r"continue to order details")
        page.wait_for_timeout(3500)
        snap(page, "order-details")
        od_text = body_text(page, 3500)
        print("ORDER DETAILS:", od_text)
        dump_controls(page, "order-details", 50)
        fill_any(page, ["instruction", "note", "comment"], INSTRUCTIONS)

        # continue to payment
        cont = False
        for sel in ("#continue-to-payment-btn", "button:has-text('CONTINUE')"):
            try:
                page.locator(sel).first.click(timeout=3500)
                cont = True
                print(f"[continued via {sel}]")
                break
            except Exception:
                continue
        if not cont:
            click_rx(page, r"(payment|continue)")
        page.wait_for_timeout(3500)
        snap(page, "payment-page")
        pay_text = body_text(page, 3500)
        print("PAYMENT PAGE:", pay_text)
        dump_controls(page, "payment", 60)

        # pick cash
        cash = False
        for sel in ("label:has-text('Cash')", "input[value*='cash' i]", "text=/pay.*(store|door|cash)/i"):
            try:
                page.locator(sel).first.click(timeout=2500)
                cash = True
                print(f"[cash via {sel}]")
                break
            except Exception:
                continue
        page.wait_for_timeout(1500)
        body = body_text(page, 3500)
        snap(page, "payment-selected")
        m = re.search(r"total[^$]*\$([0-9]+\.[0-9]{2})", body, re.I)
        total = float(m.group(1)) if m else None
        has_pizza = bool(re.search(r"pepperoni", od_text + body, re.I))
        has_jal = bool(re.search(r"jalape", od_text + body, re.I))
        print(f"[guards] pepperoni={has_pizza} jalapeno={has_jal} cash={cash} total={total}")

        if not PLACE:
            print("[DRY MODE — not placing]")
        elif not (has_pizza and cash) or (total is not None and total > MAX_TOTAL):
            print("[GUARDS FAILED — not placing]")
            if not has_jal:
                print("[note: jalapeño missing would also have blocked]")
        elif not has_jal:
            print("[GUARDS FAILED — jalapeño missing from order]")
        else:
            for sel in ("#place-order-btn", "button:has-text('PLACE ORDER')",
                        "button:has-text('SUBMIT ORDER')", "button:has-text('COMPLETE')"):
                try:
                    page.locator(sel).first.click(timeout=5000)
                    print(f"[PLACED via {sel}]")
                    break
                except Exception:
                    continue
            page.wait_for_timeout(9000)
            snap(page, "placed")
            print("FINAL:", body_text(page, 3000))
        browser.close()


if __name__ == "__main__":
    main()
