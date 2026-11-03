from decimal import ROUND_DOWN, Decimal
from fractions import Fraction
from typing import Any

# Weights of the items of the example manifest that bound the revenue of a stock: every
# recipe makes an item of a weight at most that of its inputs, and every product weighs
# at least its highest price, so no production or sale earns more than the weight of
# what it uses.
REVENUE_WEIGHTS = {
    "microchip": Fraction(40),
    "microchip-b": Fraction(40),
    "passive-kit": Fraction(0),
    "pcb-blank": Fraction(0),
    "lcd-panel": Fraction(79, 2),
    "connector-pins": Fraction(0),
    "copper-wire": Fraction(0),
    "plastic-resin": Fraction(0),
    "steel-sheet": Fraction(40),
    "control-board": Fraction(80),
    "power-module": Fraction(0),
    "sensor-module": Fraction(40),
    "display-unit": Fraction(79, 2),
    "enclosure": Fraction(80),
    "cable-harness": Fraction(0),
    "industrial-controller": Fraction(160),
    "smart-monitor": Fraction(399, 2),
    "sensor-gateway": Fraction(120),
}

# The payment terms of the customers of the example manifest.
PAYMENT_TERMS = {
    "system-integrator": 2,
    "tier1-distributor": 4,
    "equipment-maker": 6,
    "retail-chain": 8,
}

# Each product of the final assembly line of the example manifest: hours per unit,
# the components of one unit and one period of its middle demand.
FINAL_ASSEMBLY = {
    "industrial-controller": (
        Decimal("0.32"),
        ("control-board", "power-module", "enclosure", "cable-harness"),
        Decimal(90),
    ),
    "smart-monitor": (
        Decimal("0.25"),
        ("display-unit", "control-board", "power-module", "enclosure"),
        Decimal(95),
    ),
    "sensor-gateway": (
        Decimal("0.18"),
        ("sensor-module", "power-module", "enclosure", "cable-harness"),
        Decimal(80),
    ),
}

# The lines of the components of the example manifest, each with its changeover hours
# and, per component, the hours per unit, the materials of one unit and one period of
# its need at the middle demand of the products.
COMPONENT_LINES = {
    "smt-line": (
        Decimal(2),
        {
            "control-board": (
                Decimal("0.14"),
                {
                    "microchip": Decimal(2),
                    "pcb-blank": Decimal(1),
                    "passive-kit": Decimal(1),
                },
                Decimal(185),
            ),
            "power-module": (
                Decimal("0.112"),
                {
                    "passive-kit": Decimal(2),
                    "pcb-blank": Decimal(1),
                    "copper-wire": Decimal("1.5"),
                },
                Decimal(265),
            ),
            "sensor-module": (
                Decimal("0.112"),
                {
                    "microchip": Decimal(1),
                    "pcb-blank": Decimal(1),
                    "connector-pins": Decimal(2),
                },
                Decimal(80),
            ),
        },
    ),
    "module-assembly-line": (
        Decimal(0),
        {
            "display-unit": (
                Decimal("0.3"),
                {"lcd-panel": Decimal(1), "plastic-resin": Decimal("0.3")},
                Decimal(95),
            ),
            "cable-harness": (
                Decimal("0.15"),
                {"copper-wire": Decimal(3), "connector-pins": Decimal(2)},
                Decimal(170),
            ),
        },
    ),
    "moulding-line": (
        Decimal(0),
        {
            "enclosure": (
                Decimal("0.2"),
                {"steel-sheet": Decimal(2), "plastic-resin": Decimal("0.4")},
                Decimal(265),
            ),
        },
    ),
}

# Each material of the example manifest: its supplier, one period of its need for the
# components, and the minimum and maximum quantity of one order.
MATERIAL_BUYS = {
    "microchip": ("apac-chips", Decimal(450), Decimal(500), Decimal(2000)),
    "passive-kit": ("emea-electronic-parts", Decimal(715), Decimal(0), Decimal(3000)),
    "pcb-blank": ("emea-electronic-parts", Decimal(530), Decimal(0), Decimal(2500)),
    "connector-pins": (
        "emea-electronic-parts",
        Decimal(500),
        Decimal(0),
        Decimal(2500),
    ),
    "copper-wire": ("amer-metals", Decimal("907.5"), Decimal(0), Decimal(4000)),
    "plastic-resin": (
        "apac-displays-plastics",
        Decimal("134.5"),
        Decimal(0),
        Decimal(600),
    ),
    "steel-sheet": ("amer-metals", Decimal(530), Decimal(0), Decimal(2500)),
    "lcd-panel": ("apac-displays-plastics", Decimal(95), Decimal(100), Decimal(500)),
}


# The most revenue a starting stock of the example manifest can bring, at no cost: the
# stock of every warehouse at the revenue weights.
def revenue_bound(stock: dict[str, dict[str, Any]]) -> Fraction:
    return sum(
        (
            Fraction(str(quantity)) * REVENUE_WEIGHTS[item_id]
            for items in stock.values()
            for item_id, quantity in items.items()
        ),
        Fraction(0),
    )


# Whether a run recovers its purchases: a buy accepted after a buy refused for credit,
# from the accepted flag and the reason of each buy in the order they were checked.
def is_recovered(buys: list[tuple[bool, str | None]]) -> bool:
    refused = False
    for accepted, reason in buys:
        if reason == "over_credit_limit":
            refused = True
        elif accepted and refused:
            return True
    return False


# The decisions of the stock sale of the example manifest from an observation over the
# HTTP interface: ship every open order from stock, the distribution center first and
# customers of the shortest payment terms first; then make one period of the middle
# demand of each product on the final assembly line, as its regular hours and the
# components in stock allow, with a changeover of 1 hour for each product.
def stock_sale_decisions(observation: dict[str, Any]) -> list[dict[str, Any]]:
    stock = {
        (warehouse, item_id): Decimal(str(quantity))
        for warehouse, items in observation["stock"].items()
        for item_id, quantity in items.items()
    }
    decisions: list[dict[str, Any]] = []
    orders = sorted(
        observation["customer_orders"],
        key=lambda order: (PAYMENT_TERMS[order["customer"]], order["arrival"]),
    )
    for order in orders:
        left = Decimal(str(order["quantity"])) - Decimal(str(order["shipped"]))
        for warehouse in ("distribution-centre", "main-plant"):
            quantity = min(left, stock.get((warehouse, order["product"]), Decimal(0)))
            if quantity > 0:
                decisions.append(
                    {
                        "kind": "ship",
                        "order": order["id"],
                        "quantity": str(quantity),
                        "warehouse": warehouse,
                    }
                )
                stock[(warehouse, order["product"])] -= quantity
                left -= quantity
    line = observation["lines"]["final-assembly-line"]
    hours = Decimal(str(line["regular_hours_available"]))
    set_for = line["set_for"]
    for product, (time, components, demand) in FINAL_ASSEMBLY.items():
        if set_for != product:
            hours -= 1
        quantity = min(
            [demand, hours / time]
            + [stock[("main-plant", component)] for component in components]
        ).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
        if quantity <= 0:
            continue
        decisions.append(
            {
                "kind": "produce",
                "line": "final-assembly-line",
                "item": product,
                "quantity": str(quantity),
            }
        )
        for component in components:
            stock[("main-plant", component)] -= quantity
        hours -= quantity * time
        set_for = product
    return decisions


# The decisions of the recovery of the example manifest from an observation over the
# HTTP interface: the stock sale; then, on each line of components, as its regular
# hours and the materials in stock allow, the units that bring the stock of each
# component up to two periods of its need; then a buy of each material up to five
# periods of its need, less its stock and its open supplier orders, within the minimum
# and maximum quantity of one order.
def recovery_decisions(observation: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = stock_sale_decisions(observation)
    stock = {
        item_id: Decimal(str(quantity))
        for item_id, quantity in observation["stock"]["main-plant"].items()
    }
    for line_id, (changeover, components) in COMPONENT_LINES.items():
        line = observation["lines"][line_id]
        hours = Decimal(str(line["regular_hours_available"]))
        set_for = line["set_for"]
        for component, (time, materials, need) in components.items():
            room = hours - (changeover if set_for != component else 0)
            quantity = min(
                [2 * need - stock[component], room / time]
                + [stock[item_id] / amount for item_id, amount in materials.items()]
            ).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
            if quantity <= 0:
                continue
            decisions.append(
                {
                    "kind": "produce",
                    "line": line_id,
                    "item": component,
                    "quantity": str(quantity),
                }
            )
            for item_id, amount in materials.items():
                stock[item_id] -= quantity * amount
            hours = room - quantity * time
            set_for = component
    open_quantity: dict[str, Decimal] = {}
    for order in observation["supplier_orders"]:
        material = order["material"]
        open_quantity[material] = open_quantity.get(material, Decimal(0)) + Decimal(
            str(order["open_quantity"])
        )
    for material, (supplier, need, min_quantity, max_quantity) in MATERIAL_BUYS.items():
        wanted = 5 * need - stock[material] - open_quantity.get(material, Decimal(0))
        quantity = min(max_quantity, wanted).quantize(
            Decimal("0.001"), rounding=ROUND_DOWN
        )
        if quantity > 0 and quantity >= min_quantity:
            decisions.append(
                {
                    "kind": "buy",
                    "supplier": supplier,
                    "material": material,
                    "quantity": str(quantity),
                    "warehouse": "main-plant",
                }
            )
    return decisions
