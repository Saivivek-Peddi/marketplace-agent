"""Minimal Domino's Power API client. Python stdlib only — no installs needed.

Flow: find_stores -> build_order -> price_order -> place_order.
Payment defaults to cash at the door, so no card is required.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

BASE = "https://order.dominos.com/power"
HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://order.dominos.com/en/pages/order/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}

# Topping codes on the standard menu: X = pizza sauce, C = cheese,
# P = pepperoni, J = jalapeño peppers.
PEPPERONI_JALAPENO = {
    "X": {"1/1": "1"},
    "C": {"1/1": "1"},
    "P": {"1/1": "1"},
    "J": {"1/1": "1"},
}

SIZES = {
    "small": "10SCREEN",
    "medium": "12SCREEN",
    "large": "14SCREEN",
    "xl": "P16IBKZA",  # 16" Brooklyn style
}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code} from {url}: {body[:500]}") from e


def find_stores(street: str, city_state_zip: str, service: str = "Delivery") -> list[dict]:
    """Return open delivery stores nearest to the address, best first."""
    qs = urllib.parse.urlencode({"s": street, "c": city_state_zip, "type": service})
    data = _get(f"{BASE}/store-locator?{qs}")
    stores = data.get("Stores", [])
    good = [
        s for s in stores
        if s.get("IsOnlineNow") and s.get("IsDeliveryStore") is not False
        and s.get("ServiceIsOpen", {}).get(service)
    ]
    return good or stores


def store_details(store_id: str) -> dict:
    return _get(f"{BASE}/store/{store_id}/profile")


def build_order(
    store_id: str,
    street: str,
    city: str,
    region: str,
    postal_code: str,
    first_name: str,
    last_name: str,
    phone: str,
    email: str,
    size_code: str = "14SCREEN",
    quantity: int = 1,
    delivery_instructions: str = "",
) -> dict:
    address = {
        "Street": street,
        "City": city,
        "Region": region,
        "PostalCode": postal_code,
        "Type": "Business",
    }
    if delivery_instructions:
        address["DeliveryInstructions"] = delivery_instructions
    return {
        "Order": {
            "Address": address,
            "Coupons": [],
            "CustomerID": "",
            "Email": email,
            "Extension": "",
            "FirstName": first_name,
            "LastName": last_name,
            "LanguageCode": "en",
            "OrderChannel": "OLO",
            "OrderID": "",
            "OrderMethod": "Web",
            "OrderTaker": None,
            "Payments": [],
            "Phone": re.sub(r"\D", "", phone),
            "Products": [
                {
                    "Code": size_code,
                    "Options": PEPPERONI_JALAPENO,
                    "Qty": quantity,
                    "ID": 1,
                    "isNew": True,
                }
            ],
            "ServiceMethod": "Delivery",
            "SourceOrganizationURI": "order.dominos.com",
            "StoreID": str(store_id),
            "Tags": {},
            "Version": "1.0",
            "NoCombine": True,
            "Partners": {},
            "NewUser": True,
            "metaData": {},
            "Amounts": {},
            "BusinessDate": "",
            "EstimatedWaitMinutes": "",
            "PriceOrderTime": "",
        }
    }


def price_order(order: dict) -> dict:
    return _post(f"{BASE}/price-order", order)


def order_total(priced: dict) -> float | None:
    return priced.get("Order", {}).get("Amounts", {}).get("Customer")


def errors_in(response: dict) -> list[str]:
    out = []
    order = response.get("Order", response)
    if response.get("Status") == -1 or order.get("Status") == -1:
        for item in order.get("StatusItems", []) + response.get("StatusItems", []):
            code = item.get("Code", "")
            if code and code not in ("AutoAddedOrderId", "FutureTime"):
                out.append(code)
        for prod in order.get("Products", []):
            for item in prod.get("StatusItems", []):
                out.append(f"{prod.get('Code')}: {item.get('Code')}")
        if not out:
            out.append("UnknownOrderError")
    return out


def _card_type(number: str) -> str:
    if re.match(r"^4", number):
        return "VISA"
    if re.match(r"^(5[1-5]|2[2-7])", number):
        return "MASTERCARD"
    if re.match(r"^3[47]", number):
        return "AMEX"
    if re.match(r"^6(011|5)", number):
        return "DISCOVER"
    return "VISA"


def attach_payment(
    order: dict,
    amount: float,
    card_number: str = "",
    card_expiration: str = "",
    card_cvv: str = "",
    card_zip: str = "",
    tip: float = 0.0,
) -> None:
    """Attach payment: credit card if provided, otherwise cash at the door."""
    if card_number:
        number = re.sub(r"\D", "", card_number)
        payment = {
            "Type": "CreditCard",
            "Amount": round(amount + tip, 2),
            "Number": number,
            "CardType": _card_type(number),
            "Expiration": re.sub(r"\D", "", card_expiration),
            "SecurityCode": card_cvv,
            "PostalCode": card_zip,
            "TipAmount": tip,
        }
    else:
        payment = {"Type": "Cash", "Amount": round(amount, 2)}
    order["Order"]["Payments"] = [payment]


def place_order(order: dict) -> dict:
    return _post(f"{BASE}/place-order", order)
