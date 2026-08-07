"""Diagnostic matrix for the ServiceMethodNotAllowed rejections. Prints, never orders."""

from __future__ import annotations

import json

from . import dominos

ADDRESSES = [
    ("3 Embarcadero Center", "94111", "Business"),
    ("3 Embarcadero Center", "94111", "House"),
    ("301 Clay St", "94111", "Business"),
    ("50 California St", "94111", "Business"),
    ("100 Pine St", "94111", "House"),
]


def probe():
    print("=== store locator (delivery) for 3 Embarcadero Center 94111 ===")
    stores = dominos.find_stores("3 Embarcadero Center", "San Francisco, CA 94111")
    for s in stores[:4]:
        print(json.dumps({
            "StoreID": s.get("StoreID"),
            "addr": s.get("AddressDescription", "").split("\n")[0],
            "IsOnlineNow": s.get("IsOnlineNow"),
            "IsOpen": s.get("IsOpen"),
            "IsDeliveryStore": s.get("IsDeliveryStore"),
            "AllowDeliveryOrders": s.get("AllowDeliveryOrders"),
            "ServiceIsOpen": s.get("ServiceIsOpen"),
            "MinDistance": s.get("MinDistance"),
        }))
    if not stores:
        print("NO STORES")
        return
    sid = stores[0]["StoreID"]

    print(f"\n=== carryout pricing sanity at #{sid} ===")
    o = dominos.build_order(sid, "3 Embarcadero Center", "San Francisco", "CA", "94111",
                            "Test", "Probe", "5302207864", "peddisaivivek999@gmail.com")
    o["Order"]["ServiceMethod"] = "Carryout"
    r = dominos.price_order(o)
    print("carryout:", dominos.errors_in(r) or f"OK total={dominos.order_total(r)}")

    for street, zipc, typ in ADDRESSES:
        o = dominos.build_order(sid, street, "San Francisco", "CA", zipc,
                                "Test", "Probe", "5302207864", "peddisaivivek999@gmail.com",
                                delivery_instructions="")
        o["Order"]["Address"]["Type"] = typ
        r = dominos.price_order(o)
        errs = dominos.errors_in(r)
        print(f"delivery {street} {zipc} ({typ}): {errs or f'OK total={dominos.order_total(r)}'}")

    print("\n=== locator per alternate address: which store does Domino's assign? ===")
    for street in ("301 Clay St", "50 California St"):
        alt = dominos.find_stores(street, "San Francisco, CA 94111")
        if alt:
            s0 = alt[0]
            print(street, "->", s0.get("StoreID"), s0.get("AddressDescription", "").split("\n")[0],
                  "ServiceIsOpen:", s0.get("ServiceIsOpen"))
            o = dominos.build_order(s0["StoreID"], street, "San Francisco", "CA", "94111",
                                    "Test", "Probe", "5302207864", "peddisaivivek999@gmail.com")
            r = dominos.price_order(o)
            print("   price:", dominos.errors_in(r) or f"OK total={dominos.order_total(r)}")
        else:
            print(street, "-> NO STORES")


if __name__ == "__main__":
    probe()
