# 🍕 Pizza Agent

Autonomously orders a **pepperoni jalapeño pizza** to the AlphaSignal Pizza Agent
Challenge venue (3 Embarcadero Center, SF) via the Domino's ordering API.
Pays **cash at the door** — no card needed (organizers cover fees).

## Fastest path (zero installs, stdlib only)

```bash
python3 -m pizza_agent.order_now --name "Your Name" --phone 4155551234
```

It locates the nearest open Domino's, builds the pizza, prices it, shows the
total, and asks for one final `y` before placing. Add `--yes` for fully
autonomous no-touch ordering, `--dry-run` to stop after pricing.

## Judge-pleasing mode: Claude drives the tools

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pip install anthropic          # or: uv sync --extra harness
python3 -m pizza_agent.chat
```

Then just tell it: *"order a large pepperoni jalapeño pizza to the venue"* —
Claude calls `find_stores` → `price_pizza` → `place_order` live in a CC-style
tool loop, confirming price with you before the irreversible step.

## Options

- `--size small|medium|large|xl`, `--qty N`
- Card instead of cash: set `PIZZA_CARD_NUMBER`, `PIZZA_CARD_EXP` (MMYY),
  `PIZZA_CARD_CVV`, `PIZZA_CARD_ZIP`
- Track the order: https://www.dominos.com/en/pages/tracker/
