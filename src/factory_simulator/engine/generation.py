"""The manifest generated from counts of objects and a seed: its table and its rules.

Examples:
    >>> counts = {
    ...     "materials": 2,
    ...     "components": 1,
    ...     "products": 1,
    ...     "suppliers": 1,
    ...     "customers": 1,
    ...     "lines": 1,
    ... }
    >>> sorted(generate_manifest(counts, 0)["materials"])
    ['material-1', 'material-2']
"""

from collections.abc import Mapping
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from factory_simulator.engine.draws.streams import draw_uniform, open_stream
from factory_simulator.engine.draws.values import draw_periods, draw_value
from factory_simulator.engine.models.manifest import Range
from factory_simulator.engine.numbers import InputError, in_decimal_context, round_to

# The smallest and largest value of every drawn parameter in the example manifest, with
# the values of its groups and the bounds of its ranges.
GENERATOR_RANGES: Mapping[str, tuple[Decimal, Decimal] | tuple[int, int]] = {
    "materials.space": (Decimal("0.001"), Decimal("0.020")),
    "components.space": (Decimal("0.002"), Decimal("0.025")),
    "products.space": (Decimal("0.020"), Decimal("0.040")),
    "catalogue.price": (Decimal("0.4500"), Decimal("45.6000")),
    "catalogue.lead_time": (1, 5),
    "catalogue.punctuality": (Decimal("0.8000"), Decimal("0.9700")),
    "catalogue.delay": (1, 2),
    "catalogue.completeness": (Decimal("0.9500"), Decimal("1.0000")),
    "catalogue.acceptance": (Decimal("0.9500"), Decimal("1.0000")),
    "customer_products.price": (Decimal("108.0000"), Decimal("199.5000")),
    "customer_products.transport_cost": (Decimal("2.1600"), Decimal("5.0400")),
    "customer_products.demand": (Decimal("6.000"), Decimal("80.000")),
    "customer_products.lead_time": (1, 2),
    "customer_products.patience": (2, 4),
    "customer_products.late_penalty": (Decimal("3.0000"), Decimal("12.0000")),
    "customer_products.lost_sale_penalty": (Decimal("20.0000"), Decimal("30.0000")),
    "lines.wear_per_period": (Decimal("0.0020"), Decimal("0.0060")),
    "lines.wear_per_hour": (Decimal("0.0002"), Decimal("0.0006")),
    "lines.breakdown_chance": (Decimal("0.0100"), Decimal("0.0300")),
    "lines.breakdown_loss": (Decimal("0.0500"), Decimal("0.4000")),
    "lines.repair_cost": (Decimal("800.0000"), Decimal("2500.0000")),
    "lines.repair_time": (Decimal("8.000"), Decimal("16.000")),
    "lines.repair_limit": (Decimal("0.5000"), Decimal("0.7000")),
    "line_items.time": (Decimal("0.112"), Decimal("0.320")),
    "line_items.cost": (Decimal("3.9200"), Decimal("11.2000")),
    "line_items.yield": (Decimal("0.9500"), Decimal("1.0000")),
    "cash.credit_interest": (Decimal("0.0003"), Decimal("0.0003")),
    "cash.debit_interest": (Decimal("0.0015"), Decimal("0.0015")),
    "cash.overdraft_interest": (Decimal("0.0040"), Decimal("0.0040")),
}

# The middle of the smallest and largest relative half width of the ranges of every
# parameter that the example writes as a range.
GENERATOR_HALF_WIDTHS: Mapping[str, Decimal] = {
    "catalogue.price": Decimal("0.0972"),
    "catalogue.lead_time": Decimal("0.2500"),
    "catalogue.punctuality": Decimal("0.0536"),
    "catalogue.delay": Decimal("0.3333"),
    "catalogue.completeness": Decimal("0.0179"),
    "catalogue.acceptance": Decimal("0.0128"),
    "customer_products.demand": Decimal("0.5333"),
    "lines.breakdown_loss": Decimal("0.5143"),
    "line_items.yield": Decimal("0.0128"),
}

# The kinds of objects counted, in the order the generated description names them.
COUNT_KINDS = ("materials", "components", "products", "suppliers", "customers", "lines")

# The drawn keys of a line, in the order they are drawn and written.
LINE_KEYS = (
    "wear_per_period",
    "wear_per_hour",
    "breakdown_chance",
    "breakdown_loss",
    "repair_cost",
    "repair_time",
    "repair_limit",
)

# The keys of a customer product, in the order they are drawn and written.
CUSTOMER_PRODUCT_KEYS = (
    "price",
    "transport_cost",
    "demand",
    "lead_time",
    "patience",
    "late_penalty",
    "lost_sale_penalty",
)

# The smallest and largest price of a customer product in the example manifest over
# the lowest cost of its product: 189.0000 / 104.28 and 160.0000 / 65.98.
MATCHED_PRICE_RATIOS = Range(min=Decimal("1.8124"), max=Decimal("2.4250"))

# The chance that a material has a second supplier.
SECOND_SOURCE_CHANCE = Decimal("0.3000")
# The prices of a second supplier over those of the first.
SECOND_SOURCE_PRICE_FACTOR = Decimal("1.15")
# The chance that a customer buys a product besides the products it surely buys.
SECOND_CUSTOMER_CHANCE = Decimal("0.5000")
# The hours a line needs at the middle of demand over its capacity.
LINE_LOAD = Decimal("0.85")
# The space the stock needs over the capacity of the warehouse.
WAREHOUSE_LOAD = Decimal("0.75")
# The storage cost of an item over its lowest cost.
STORAGE_COST_SHARE = Decimal("0.005")
# The salvage value of a material over its lowest price.
MATERIAL_SALVAGE_SHARE = Decimal("0.4")
# The salvage value of a made item over the salvage values of its inputs.
MADE_SALVAGE_SHARE = Decimal("0.8")
# The most inputs of one recipe.
MOST_INPUTS = 4
# The periods of use the starting stock of an item covers, before its lead time.
STOCK_PERIODS = 3

# A number written by the generator: a decimal or a whole number.
type Number = Decimal | int
# How the price of a customer product is drawn: within its row of the table, or as
# the lowest cost of its product times a ratio of `MATCHED_PRICE_RATIOS`.
type Economy = Literal["unrestricted", "matched"]
# A drawn value: a fixed number, or the bounds of a uniform range.
type Drawn = Number | tuple[Number, Number]


def numbered(kind: str, count: int) -> list[str]:
    """Give the names of the objects of one kind by number.

    Args:
        kind (str): The kind, such as "material".
        count (int): How many there are.

    Returns:
        list[str]: `<kind>-1` to `<kind>-<count>`.

    Examples:
        >>> numbered("line", 2)
        ['line-1', 'line-2']
    """
    return [f"{kind}-{position}" for position in range(1, count + 1)]


def number_json(value: Drawn) -> object:
    """Write a number or a range as the JSON of a manifest.

    Args:
        value (Decimal | int | tuple[Decimal | int, Decimal | int]): A fixed number,
            or the bounds of a uniform range.

    Returns:
        object: A decimal as text with its places, a whole number as it is, or a
            mapping with `min` and `max`.

    Examples:
        >>> number_json((Decimal("0.900"), Decimal("1.000")))
        {'min': '0.900', 'max': '1.000'}
    """
    if isinstance(value, tuple):
        return {"min": number_json(value[0]), "max": number_json(value[1])}
    if isinstance(value, int):
        return value
    return format(value, "f")


def draw_number(parameter: str, path: str, seed: int) -> Number:
    """Draw a fixed number of a parameter between its bounds in `GENERATOR_RANGES`.

    Args:
        parameter (str): The row of `GENERATOR_RANGES`.
        path (str): The dotted path of the number, which names its stream.
        seed (int): The seed of the generator.

    Returns:
        Decimal | int: The number, with the places of the row.

    Examples:
        >>> 1 <= draw_number("catalogue.lead_time", "x", 0) <= 5
        True
    """
    low, high = GENERATOR_RANGES[parameter]
    uniform = draw_uniform(open_stream(seed, "generator", path))
    if isinstance(low, int) and isinstance(high, int):
        return draw_periods(Range(min=low, max=high), uniform)
    return draw_value(Range(min=Decimal(low), max=Decimal(high)), uniform)


def draw_range(parameter: str, path: str, seed: int) -> tuple[Number, Number]:
    """Draw a uniform range around a middle drawn like a fixed number.

    The bounds are `m * (1 - h)` and `m * (1 + h)` with h of `GENERATOR_HALF_WIDTHS`,
    rounded half to even to the places of the row and kept within its smallest and
    largest value.

    Args:
        parameter (str): The row of `GENERATOR_RANGES`.
        path (str): The dotted path of the range, which names its stream.
        seed (int): The seed of the generator.

    Returns:
        tuple[Decimal | int, Decimal | int]: The lower and upper bound.

    Examples:
        >>> low, high = draw_range("line_items.yield", "x", 0)
        >>> Decimal("0.96") <= low <= high <= 1
        True
    """
    smallest, largest = GENERATOR_RANGES[parameter]
    middle = Decimal(draw_number(parameter, path, seed))
    half_width = GENERATOR_HALF_WIDTHS[parameter]
    exponent = Decimal(1) if isinstance(smallest, int) else Decimal(smallest)
    bounds = [
        min(
            max((middle * share).quantize(exponent), Decimal(smallest)),
            Decimal(largest),
        )
        for share in (1 - half_width, 1 + half_width)
    ]
    if isinstance(smallest, int):
        return int(bounds[0]), int(bounds[1])
    return bounds[0], bounds[1]


def middle_of(value: Drawn) -> Decimal:
    """Give the middle of a range, or a fixed number as it is.

    Args:
        value (Decimal | int | tuple[Decimal | int, Decimal | int]): A number or the
            bounds of a range.

    Returns:
        Decimal: `(min + max) / 2` for a range.

    Examples:
        >>> middle_of((Decimal("4"), Decimal("6")))
        Decimal('5')
    """
    if isinstance(value, tuple):
        return (Decimal(value[0]) + Decimal(value[1])) / 2
    return Decimal(value)


def choose_inputs(path: str, inputs: list[str], seed: int) -> list[str]:
    """Choose the different inputs of one recipe from its stream.

    The first draw gives the count k from 1 to `min(4, len(inputs))`; each later draw
    takes, of the inputs not yet chosen in the order of their numbers, the one at
    place `floor(u * count left)`.

    Args:
        path (str): The path of the recipe, which names its stream.
        inputs (list[str]): The items it may use, in the order of their numbers.
        seed (int): The seed of the generator.

    Returns:
        list[str]: The chosen inputs, in the order of their numbers.

    Examples:
        >>> choose_inputs("recipe", ["material-1", "material-2", "material-3"], 0)
        ['material-3']
    """
    stream = open_stream(seed, "generator", path)
    count = draw_periods(
        Range(min=1, max=min(MOST_INPUTS, len(inputs))), draw_uniform(stream)
    )
    left = list(inputs)
    chosen: list[str] = []
    for _ in range(count):
        place = int((draw_uniform(stream) * len(left)).to_integral_value(ROUND_FLOOR))
        chosen.append(left.pop(min(place, len(left) - 1)))
    return [item for item in inputs if item in chosen]


def is_drawn_below(path: str, chance: Decimal, seed: int) -> bool:
    """Tell whether the one draw of a choice is below its chance.

    Args:
        path (str): The path of the choice, which names its stream.
        chance (Decimal): The chance.
        seed (int): The seed of the generator.

    Returns:
        bool: True when the draw is below the chance.

    Examples:
        >>> is_drawn_below("x", Decimal(0), 0)
        False
    """
    return draw_uniform(open_stream(seed, "generator", path)) < chance


def round_up(value: Decimal, places: int) -> Decimal:
    """Round a number up to a number of places.

    Args:
        value (Decimal): The number.
        places (int): Places after the point.

    Returns:
        Decimal: The number rounded up.

    Examples:
        >>> round_up(Decimal("70.588"), 0)
        Decimal('71')
    """
    return round_to(value, places, ROUND_CEILING)


def sources_of(
    materials: list[str], suppliers: list[str], seed: int
) -> dict[str, list[str]]:
    """Give the suppliers of every material, its first supplier first.

    Args:
        materials (list[str]): The materials.
        suppliers (list[str]): The suppliers.
        seed (int): The seed of the generator.

    Returns:
        dict[str, list[str]]: Per material, the suppliers that sell it.

    Examples:
        >>> sources_of(["material-1", "material-2"], ["supplier-1"], 0)
        {'material-1': ['supplier-1'], 'material-2': ['supplier-1']}
    """
    sources: dict[str, list[str]] = {}
    for position, material in enumerate(materials):
        first = position % len(suppliers)
        sources[material] = [suppliers[first]]
        path = f"materials.{material}.second_source"
        if len(suppliers) > 1 and is_drawn_below(path, SECOND_SOURCE_CHANCE, seed):
            sources[material].append(suppliers[(first + 1) % len(suppliers)])
    for position, supplier in enumerate(suppliers):
        material = materials[position % len(materials)]
        if supplier not in sources[material]:
            sources[material].append(supplier)
    return sources


def buyers_of(
    products: list[str], customers: list[str], seed: int
) -> dict[str, list[str]]:
    """Give the products every customer buys.

    Args:
        products (list[str]): The products.
        customers (list[str]): The customers.
        seed (int): The seed of the generator.

    Returns:
        dict[str, list[str]]: Per customer, the products it buys, in their order.

    Examples:
        >>> buyers_of(["product-1"], ["customer-1"], 0)
        {'customer-1': ['product-1']}
    """
    bought: dict[str, list[str]] = {}
    for customer_position, customer in enumerate(customers):
        bought[customer] = []
        for product_position, product in enumerate(products):
            surely = (
                product_position % len(customers) == customer_position
                or customer_position % len(products) == product_position
            )
            path = f"customers.{customer}.products.{product}"
            if surely or is_drawn_below(path, SECOND_CUSTOMER_CHANCE, seed):
                bought[customer].append(product)
    return bought


def draw_customer_product(
    customer_id: str, product_id: str, seed: int
) -> dict[str, Drawn]:
    """Draw the terms of a customer product.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product it buys.
        seed (int): The seed of the generator.

    Returns:
        dict[str, Decimal | int | tuple[Decimal | int, Decimal | int]]: Its price,
            transport cost, demand range, lead time, patience and penalties.

    Examples:
        >>> sorted(draw_customer_product("customer-1", "product-1", 0))[:2]
        ['demand', 'late_penalty']
    """
    path = f"customers.{customer_id}.products.{product_id}"
    return {
        key: draw_written(f"customer_products.{key}", f"{path}.{key}", seed)
        for key in CUSTOMER_PRODUCT_KEYS
    }


def draw_matched_price(
    customer_id: str, product_id: str, lowest_cost: Decimal, seed: int
) -> Decimal:
    """Draw the price of a customer product in the matched economy.

    The draw of its price gives a ratio within `MATCHED_PRICE_RATIOS` in place of a
    price within its row of the table.

    Args:
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product it buys.
        lowest_cost (Decimal): The lowest cost of the product.
        seed (int): The seed of the generator.

    Returns:
        Decimal: The lowest cost times the ratio, rounded half to even to 4 places.

    Examples:
        >>> draw_matched_price("customer-1", "product-1", Decimal("35.3776"), 0)
        Decimal('67.0830')
    """
    path = f"customers.{customer_id}.products.{product_id}.price"
    uniform = draw_uniform(open_stream(seed, "generator", path))
    return round_to(lowest_cost * draw_value(MATCHED_PRICE_RATIOS, uniform), 4)


def draw_written(parameter: str, path: str, seed: int) -> Drawn:
    """Draw a parameter as a range when the example writes it as one, else as fixed.

    Args:
        parameter (str): The row of `GENERATOR_RANGES`.
        path (str): The dotted path of the value, which names its stream.
        seed (int): The seed of the generator.

    Returns:
        Decimal | int | tuple[Decimal | int, Decimal | int]: The fixed number or the
            bounds of the range.

    Examples:
        >>> draw_written("customer_products.patience", "x", 0) in (2, 3, 4)
        True
    """
    if parameter in GENERATOR_HALF_WIDTHS:
        return draw_range(parameter, path, seed)
    return draw_number(parameter, path, seed)


def lower_bound(value: Drawn) -> Decimal:
    """Give the lower bound of a range, or a fixed number as it is.

    Args:
        value (Decimal | int | tuple[Decimal | int, Decimal | int]): A number or the
            bounds of a range.

    Returns:
        Decimal: The lower bound.

    Examples:
        >>> lower_bound((Decimal("2.4"), Decimal("2.6")))
        Decimal('2.4')
    """
    return Decimal(value[0] if isinstance(value, tuple) else value)


def upper_bound(value: Drawn) -> Decimal:
    """Give the upper bound of a range, or a fixed number as it is.

    Args:
        value (Decimal | int | tuple[Decimal | int, Decimal | int]): A number or the
            bounds of a range.

    Returns:
        Decimal: The upper bound.

    Examples:
        >>> upper_bound((Decimal("2.4"), Decimal("2.6")))
        Decimal('2.6')
    """
    return Decimal(value[1] if isinstance(value, tuple) else value)


def second_source(price: Drawn, lead_time: Drawn) -> tuple[Drawn, Drawn]:
    """Give the price and lead time of an entry of a material other than its first.

    Args:
        price (Decimal | int | tuple[Decimal | int, Decimal | int]): The price of the
            first entry.
        lead_time (Decimal | int | tuple[Decimal | int, Decimal | int]): The lead time
            of the first entry.

    Returns:
        tuple[Decimal | int | tuple[Decimal | int, Decimal | int], Decimal | int |
            tuple[Decimal | int, Decimal | int]]: The price times 1.15, each bound
            rounded half to even to 4 places, and the lead time less 1, each bound at
            least 1.

    Examples:
        >>> second_source(Decimal("2.4000"), 2)
        (Decimal('2.7600'), 1)
        >>> second_source(Decimal("2.4000"), (3, 5))
        (Decimal('2.7600'), (2, 4))
    """
    low = round_to(lower_bound(price) * SECOND_SOURCE_PRICE_FACTOR, 4)
    high = round_to(upper_bound(price) * SECOND_SOURCE_PRICE_FACTOR, 4)
    later_price: Drawn = (low, high) if isinstance(price, tuple) else low
    shortest = max(1, int(lower_bound(lead_time)) - 1)
    longest = max(1, int(upper_bound(lead_time)) - 1)
    later_lead_time: Drawn = (
        (shortest, longest) if isinstance(lead_time, tuple) else shortest
    )
    return later_price, later_lead_time


def line_capacity(hours: Decimal) -> Decimal:
    """Give the capacity of a line: its hours at the middle of demand at a load of 0.85.

    Args:
        hours (Decimal): The hours its items need at the middle of demand.

    Returns:
        Decimal: `hours / 0.85` rounded up to whole hours, at least 1, with 3 places.

    Examples:
        >>> line_capacity(Decimal("60.000"))
        Decimal('71.000')
    """
    return round_to(max(Decimal(1), round_up(hours / LINE_LOAD, 0)), 3)


def material_salvage(lowest_price: Decimal) -> Decimal:
    """Give the salvage value of a material: 0.4 times its lowest price.

    Args:
        lowest_price (Decimal): Its lowest price in any catalogue.

    Returns:
        Decimal: The salvage value, rounded half to even to 4 places.

    Examples:
        >>> material_salvage(Decimal("2.4000"))
        Decimal('0.9600')
    """
    return round_to(MATERIAL_SALVAGE_SHARE * lowest_price, 4)


def needs_of(
    recipes: Mapping[str, list[str]],
    product_needs: Mapping[str, Decimal],
    items: list[str],
) -> dict[str, Decimal]:
    """Give the need of every item per period from the need of every product.

    A component or a material needs the sum of the needs of the items whose recipe
    holds it.

    Args:
        recipes (Mapping[str, list[str]]): The inputs of every made item.
        product_needs (Mapping[str, Decimal]): The need of every product per period.
        items (list[str]): Every item, materials first, then components, then
            products.

    Returns:
        dict[str, Decimal]: The need of every item per period.

    Examples:
        >>> needs_of({"p": ["m"]}, {"p": Decimal("5")}, ["m", "p"])
        {'m': Decimal('5'), 'p': Decimal('5')}
    """
    need = dict.fromkeys(items, Decimal(0)) | dict(product_needs)
    for item in reversed(items):
        for input_id in recipes.get(item, []):
            need[input_id] += need[item]
    return need


def terms_json(terms: Mapping[str, Drawn]) -> dict[str, object]:
    """Write every number and range of a mapping as the JSON of a manifest.

    Args:
        terms (Mapping[str, Decimal | int | tuple[Decimal | int, Decimal | int]]):
            Numbers and ranges by key.

    Returns:
        dict[str, object]: The same keys with their JSON.

    Examples:
        >>> terms_json({"lead_time": 2})
        {'lead_time': 2}
    """
    return {key: number_json(value) for key, value in terms.items()}


def draw_catalogues(
    sources: Mapping[str, list[str]], peak: Mapping[str, Decimal], seed: int
) -> dict[str, dict[str, dict[str, Drawn]]]:
    """Draw the catalogue entry of every supplier and material it sells.

    Args:
        sources (Mapping[str, list[str]]): The suppliers of every material, its first
            supplier first.
        peak (Mapping[str, Decimal]): The need of every material at the largest
            demand.
        seed (int): The seed of the generator.

    Returns:
        dict[str, dict[str, dict[str, Decimal | int | tuple[Decimal | int, Decimal |
            int]]]]: Per material and supplier, its terms.

    Examples:
        >>> drawn = draw_catalogues({"m": ["s"]}, {"m": Decimal("5")}, 0)
        >>> drawn["m"]["s"]["max_quantity"]
        Decimal('10.000')
    """
    entries: dict[str, dict[str, dict[str, Drawn]]] = {}
    for material, suppliers in sources.items():
        entries[material] = {}
        first = f"suppliers.{suppliers[0]}.catalogue.{material}"
        price = draw_written("catalogue.price", f"{first}.price", seed)
        lead_time = draw_written("catalogue.lead_time", f"{first}.lead_time", seed)
        for position, supplier in enumerate(suppliers):
            path = f"suppliers.{supplier}.catalogue.{material}"
            terms: dict[str, Drawn] = {"price": price, "lead_time": lead_time}
            if position > 0:
                terms["price"], terms["lead_time"] = second_source(price, lead_time)
            most = max(Decimal(1), round_up(2 * peak[material], 0))
            terms["max_quantity"] = round_to(most, 3)
            for key in ("punctuality", "delay", "completeness", "acceptance"):
                terms[key] = draw_written(f"catalogue.{key}", f"{path}.{key}", seed)
            entries[material][supplier] = terms
    return entries


def draw_line(line_id: str, hours: Decimal, seed: int) -> dict[str, Drawn]:
    """Draw the terms of a line, its wear low enough that full use keeps it above 0.

    Args:
        line_id (str): The identifier of the line.
        hours (Decimal): The hours its items need at the middle of demand.
        seed (int): The seed of the generator.

    Returns:
        dict[str, Decimal | int | tuple[Decimal | int, Decimal | int]]: Its capacity,
            wear, breakdown and repair terms.

    Examples:
        >>> draw_line("line-1", Decimal("60"), 0)["capacity"]
        Decimal('71.000')
    """
    capacity = line_capacity(hours)
    terms: dict[str, Drawn] = {"capacity": capacity}
    for key in LINE_KEYS:
        terms[key] = draw_written(f"lines.{key}", f"lines.{line_id}.{key}", seed)
    wear_limit = (1 - lower_bound(terms["wear_per_period"])) / capacity
    terms["wear_per_hour"] = min(
        lower_bound(terms["wear_per_hour"]),
        round_to(wear_limit, 4, ROUND_FLOOR),
    )
    return terms


def costs_and_salvage(
    recipes: Mapping[str, list[str]],
    lowest_prices: Mapping[str, Decimal],
    item_costs: Mapping[str, Decimal],
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Give the lowest cost and the salvage value of every item.

    A material costs its lowest price and keeps 0.4 of it; a made item costs its
    inputs plus its own cost on its line and keeps 0.8 of the salvage of its inputs.

    Args:
        recipes (Mapping[str, list[str]]): The inputs of every made item, components
            before products.
        lowest_prices (Mapping[str, Decimal]): The lowest price of every material.
        item_costs (Mapping[str, Decimal]): The cost of every made item on its line.

    Returns:
        tuple[dict[str, Decimal], dict[str, Decimal]]: The lowest cost and the salvage
            value of every item, salvage rounded half to even to 4 places.

    Examples:
        >>> costs_and_salvage({"c": ["m"]}, {"m": Decimal("2")}, {"c": Decimal("1")})
        ... # doctest: +NORMALIZE_WHITESPACE
        ({'m': Decimal('2'), 'c': Decimal('3')},
         {'m': Decimal('0.8000'), 'c': Decimal('0.6400')})
    """
    lowest_costs = dict(lowest_prices)
    salvage = {
        material: material_salvage(price) for material, price in lowest_prices.items()
    }
    for item, inputs in recipes.items():
        lowest_costs[item] = sum(
            (lowest_costs[input_id] for input_id in inputs), item_costs[item]
        )
        inputs_salvage = sum((salvage[input_id] for input_id in inputs), Decimal(0))
        salvage[item] = round_to(MADE_SALVAGE_SHARE * inputs_salvage, 4)
    return lowest_costs, salvage


@in_decimal_context
def generate_manifest(
    counts: Mapping[str, int], seed: int, economy: Economy = "unrestricted"
) -> dict[str, object]:
    """Generate the JSON body of a linear manifest from counts of objects and a seed.

    Every choice and every number is drawn from a stream `generator, <path>`; a
    number of the example factory is drawn within its row of `GENERATOR_RANGES`, and
    capacities, maximum quantities, storage costs, salvage values and the credit
    limit follow from the drawn demand, prices and times. In the matched economy the
    price of a customer product is the lowest cost of its product times a ratio drawn
    within `MATCHED_PRICE_RATIOS`.

    Args:
        counts (Mapping[str, int]): The number of `materials`, `components`,
            `products`, `suppliers`, `customers` and `lines`, each at least 1, with
            `lines` at most `components + products`.
        seed (int): The seed of the generator, from 0 to `2 ** 128 - 1`.
        economy (Literal['unrestricted', 'matched'], optional): How prices of customer
            products are drawn, `unrestricted` when not given.

    Returns:
        dict[str, object]: The manifest as JSON, numbers as text.

    Raises:
        InputError: If a count is below 1, at the first such count in the order of
            `COUNT_KINDS`; if `lines` is above `components + products`, at `lines`.

    Examples:
        >>> counts = {
        ...     "materials": 1,
        ...     "components": 1,
        ...     "products": 1,
        ...     "suppliers": 1,
        ...     "customers": 1,
        ...     "lines": 1,
        ... }
        >>> generate_manifest(counts, 0)["name"]
        'Generated factory'
    """
    for kind in COUNT_KINDS:
        if counts[kind] < 1:
            raise InputError(f"{kind}: must be at least 1")
    if counts["lines"] > counts["components"] + counts["products"]:
        raise InputError("lines: must be at most components + products")
    kinds = {kind: numbered(kind[:-1], counts[kind]) for kind in COUNT_KINDS}
    materials, components, products = (
        kinds["materials"],
        kinds["components"],
        kinds["products"],
    )
    made = [*components, *products]
    recipes = {
        item: choose_inputs(f"{kind}.{item}.recipes.standard", inputs, seed)
        for kind, inputs in (("components", materials), ("products", components))
        for item in kinds[kind]
    }
    line_of = {
        item: kinds["lines"][position % counts["lines"]]
        for position, item in enumerate(made)
    }

    customer_products = {
        customer: {
            product: draw_customer_product(customer, product, seed) for product in held
        }
        for customer, held in buyers_of(products, kinds["customers"], seed).items()
    }
    demands: dict[str, list[Drawn]] = {product: [] for product in products}
    for held in customer_products.values():
        for product, terms in held.items():
            demands[product].append(terms["demand"])
    middles = {
        product: sum((middle_of(demand) for demand in ranges), Decimal(0))
        for product, ranges in demands.items()
    }
    tops = {
        product: sum((upper_bound(demand) for demand in ranges), Decimal(0))
        for product, ranges in demands.items()
    }
    need = needs_of(recipes, middles, [*materials, *made])
    peak = needs_of(recipes, tops, [*materials, *made])

    line_items: dict[str, dict[str, Drawn]] = {}
    for item in made:
        path = f"lines.{line_of[item]}.items.{item}"
        line_items[item] = {
            key: draw_written(f"line_items.{key}", f"{path}.{key}", seed)
            for key in ("time", "cost", "yield")
        }
    lines: dict[str, object] = {}
    for line in kinds["lines"]:
        on_line = [item for item in made if line_of[item] == line]
        hours = sum(
            (need[item] * lower_bound(line_items[item]["time"]) for item in on_line),
            Decimal(0),
        )
        lines[line] = terms_json(draw_line(line, hours, seed)) | {
            "items": {item: terms_json(line_items[item]) for item in on_line}
        }

    sources = sources_of(materials, kinds["suppliers"], seed)
    entries = draw_catalogues(sources, peak, seed)
    first_entries = {
        material: entries[material][sources[material][0]] for material in materials
    }
    lowest_costs, salvage = costs_and_salvage(
        recipes,
        {
            material: lower_bound(terms["price"])
            for material, terms in first_entries.items()
        },
        {item: lower_bound(terms["cost"]) for item, terms in line_items.items()},
    )
    if economy == "matched":
        for customer, held in customer_products.items():
            for product, terms in held.items():
                terms["price"] = draw_matched_price(
                    customer, product, lowest_costs[product], seed
                )
    items: dict[str, dict[str, object]] = {}
    space_needed = Decimal(0)
    for kind in ("materials", "components", "products"):
        items[kind] = {}
        for item in kinds[kind]:
            space = Decimal(draw_number(f"{kind}.space", f"{kind}.{item}.space", seed))
            body: dict[str, object] = {
                "space": number_json(space),
                "storage_cost": number_json(
                    round_to(STORAGE_COST_SHARE * lowest_costs[item], 4)
                ),
                "salvage_value": number_json(salvage[item]),
            }
            if item in recipes:
                body["recipes"] = {"standard": dict.fromkeys(recipes[item], "1.000")}
                periods = Decimal(STOCK_PERIODS + 1)
            else:
                periods = STOCK_PERIODS + upper_bound(first_entries[item]["lead_time"])
            items[kind][item] = body
            space_needed += space * need[item] * periods

    sales = sum(
        (
            lower_bound(terms["price"]) * middle_of(terms["demand"])
            for held in customer_products.values()
            for terms in held.values()
        ),
        Decimal(0),
    )
    cash: dict[str, object] = {"credit_limit": number_json(round_to(2 * sales, 4))}
    for key in ("credit_interest", "debit_interest", "overdraft_interest"):
        cash[key] = number_json(draw_number(f"cash.{key}", f"cash.{key}", seed))
    plant = max(Decimal("0.001"), round_up(space_needed / WAREHOUSE_LOAD, 3))
    named = ", ".join(f"{counts[kind]} {kind}" for kind in COUNT_KINDS)
    prices = " and matched prices" if economy == "matched" else ""
    return {
        "name": "Generated factory",
        "description": f"Generated from {named} with seed {seed}{prices}.",
        **items,
        "suppliers": {
            supplier: {
                "catalogue": {
                    material: terms_json(entries[material][supplier])
                    for material in materials
                    if supplier in sources[material]
                }
            }
            for supplier in kinds["suppliers"]
        },
        "customers": {
            customer: {
                "products": {
                    product: terms_json(terms) for product, terms in held.items()
                }
            }
            for customer, held in customer_products.items()
        },
        "lines": lines,
        "warehouses": {"plant": {"capacity": number_json(plant)}},
        "cash": cash,
    }
