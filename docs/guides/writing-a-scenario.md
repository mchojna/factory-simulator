# Writing a scenario

A scenario is one JSON document that describes how a run goes over time: the horizon,
the starting state, demand shapes, forecasts, disruptions and hidden parameter groups.
Every key and its bounds are in [Scenario fields](../reference/scenario-fields.md). The
examples are written for the smallest manifest of
[Writing a manifest](writing-a-manifest.md).

`POST /api/v1/manifests/{id}/scenarios` takes a scenario of a stored manifest. The
response is 201 and the stored scenario when it is new, 200 and the stored scenario when
the manifest already has it, 404 when the manifest does not exist, and 422 with the
place of the first problem when the scenario breaks a rule. One scenario runs with many
seeds.

## Smallest example

```json
{"horizon": 12}
```

- `horizon` is the only required key: the number of periods, from 1 to 520.
- Every other key has a default: cash 0, no stock, every line at condition 1 and set for
  no item, no open order, no demand shape, no forecast, no disruption and nothing
  hidden.
- The horizon leaves time to buy: a material used in a recipe must be able to arrive
  within it. In the smallest manifest `chip` has a lead time of 2, so a horizon of 2 is
  refused.
- `name` and `description` are text for a person; the agent never sees them.

## Start

`start` is the state of the factory before period 1:

```json
{
  "horizon": 12,
  "start": {
    "cash": 5000,
    "stock": {"main": {"chip": 400, "monitor": 10}},
    "condition": {"assembly": 0.9},
    "set_for": {"assembly": "board"},
    "customer_orders": [
      {"customer": "distributor", "product": "monitor", "quantity": 5, "due": 1}
    ],
    "supplier_orders": [
      {"supplier": "chip-maker", "material": "chip", "quantity": 500, "arrival": 2}
    ]
  }
}
```

- `cash` may be below 0.
- `stock` is the quantity of each item in each warehouse; a missing item starts at 0.
  The warehouse accepts the item, and the stock with the starting supplier orders to the
  warehouse fits its capacity.
- `condition` is the condition of each line, from 0 to 1; a missing line starts at 1.
- `set_for` is the item each line is set for, an item the line makes; a missing line is
  set for no item. With changeovers, the first production of a line set for no item pays
  one.
- A starting customer order names a customer and a product it buys, a quantity above 0
  and a due period from 1 to the horizon. It arrived in period 0 and has the patience,
  price and penalties of its pair.
- A starting supplier order names a supplier, a material of its catalogue, a quantity
  above 0 and an arrival period from 1 to the horizon. With several warehouses it also
  names a `warehouse` that accepts the material. It was placed in period 0 at the drawn
  price, the price of period 1 when the price is drawn every period, without discount or
  express. It arrives in full and accepted in its arrival period, no disruption acts on
  it, and it can be cancelled like any open order.
- Receivables, production, plans and transfers are empty at the start.

## Demand shapes

A demand shape is a factor over time that multiplies base demand:

```json
{
  "horizon": 12,
  "demand_shapes": [
    {"kind": "trend", "target": "all", "rate": 0.01},
    {"kind": "season", "target": {"customer": "distributor"}, "factors": [0.9, 1.1], "period_length": 4},
    {"kind": "step", "target": {"product": "monitor"}, "period": 6, "factor": 1.2},
    {"kind": "ramp", "target": {"customer": "distributor", "product": "monitor"}, "first": 2, "last": 8, "from_factor": 1, "to_factor": 1.5},
    {"kind": "s_curve", "target": "all", "middle": 6, "steepness": 0.5, "from_factor": 0.5, "to_factor": 1}
  ]
}
```

| `kind` | Keys | Bounds |
| --- | --- | --- |
| `trend` | `rate` | `rate` above -1. |
| `season` | `factors`, `period_length` | At least one factor, each at least 0; `period_length` at least 1. |
| `step` | `period`, `factor` | `factor` at least 0. |
| `ramp` | `first`, `last`, `from_factor`, `to_factor` | `last` after `first`; factors at least 0. |
| `s_curve` | `middle`, `steepness`, `from_factor`, `to_factor` | `steepness` above 0; factors at least 0. |

- `period`, `first`, `last` and `middle` are whole numbers and may lie outside the
  horizon. Rates and factors have 4 places.
- `target` is `"all"`; one customer, `{"customer": "distributor"}`; one product,
  `{"product": "monitor"}`; one pair,
  `{"customer": "distributor", "product": "monitor"}`, which the manifest has; or a
  group of customers or products, written `{"<kind>": "<group>"}`, such as
  `{"segment": "new-devices"}`, whose kind matches the group.
- The demand of a pair is its base demand times the factor of every shape that targets
  it.

The factor of each kind in each period is given in
[Customers and demand](../rules/customers-and-demand.md#demand-shapes).

## Written disruptions

A written disruption has a kind, a target, a start, a duration and one effect key:

```json
{
  "horizon": 12,
  "disruptions": [
    {"kind": "supplier_outage", "target": ["chip-maker"], "start": 4, "duration": 3, "notice": 2, "strength": 0.8},
    {"kind": "line_breakdown", "target": "all", "start": 7, "loss": 0.4}
  ]
}
```

| `kind` | Target | Effect key | Bounds of the effect |
| --- | --- | --- | --- |
| `supplier_outage` | suppliers | `strength` | 0 to 1 |
| `quality_drop` | suppliers | `strength` | 0 to 1 |
| `transport_delay` | suppliers | `delay` | whole number, at least 1 |
| `material_shortage` | materials | `strength` | 0 to 1 |
| `price_change` | materials | `factor` | above 0 |
| `demand_shock` | products | `factor` | above 0 |
| `line_breakdown` | lines | `loss` | 0 to 1 |
| `capacity_cut` | lines | `strength` | 0 to 1 |
| `yield_drop` | lines | `strength` | 0 to 1 |

- `target` is a list of identifiers of the kind the disruption acts on, `"all"`, or a
  group of that kind, written `{"<kind>": "<group>"}`, such as `{"region": "asia"}`. A
  list is not empty and names no object twice.
- `start` is a period from 1 to the horizon.
- `duration` is at least 1. A `line_breakdown` has no duration: it acts once, in its
  start period.
- `notice` is 0 by default. The disruption is visible from period `start - notice`,
  which is at least 1. The outage above is visible from period 2 and acts in periods 4,
  5 and 6.
- Every key is a fixed number.
- The disruptions are numbered `disruption-1`, `disruption-2` and so on, in the order of
  `start - notice`, the first period each is visible, then of the list. The list keeps
  its order. The description of a run never shows them.

What each kind does is given in [Disruptions](../rules/disruptions.md).

## Random disruptions

A random disruption is a named rule that draws disruptions from the seed:

```json
{
  "horizon": 12,
  "random_disruptions": [
    {"name": "outages", "kind": "supplier_outage", "target": "all", "chance": 0.05,
     "notice": 1, "duration": {"min": 1, "max": 3},
     "strength": {"min": 0.2, "max": 0.8, "distribution": "triangular", "mode": 0.5}},
    {"name": "breakdowns", "kind": "line_breakdown", "target": ["assembly"],
     "chance": 0.1, "choose": "one", "loss": {"min": 0.1, "max": 0.5}}
  ]
}
```

- `name` is an identifier, unique in the scenario. It keys the random stream of the
  rule, so adding or removing a rule changes no draw of the others.
- `kind`, `target` and the effect key are those of a written disruption.
  `line_breakdown` has no `duration`; every other kind needs one.
- `chance` is the chance from 0 to 1 that a disruption starts in a period.
- Without `choose`, every target of the rule may start its own disruption in every
  period. With `choose: "one"`, at most one disruption starts in a period, on the target
  with the smallest draw.
- `duration` is a fixed number or a uniform range, at least 1. The effect is a fixed
  number or a range of any distribution; the `delay` of a `transport_delay` is uniform
  only. Each is drawn in the start period of the disruption.
- `notice` is 0 by default. A rule keeps every start it draws; a start in a period up to
  `notice` is visible from period 1.
- The description of a run shows the rules, but not the disruptions they draw.

## A written start and a cascade

A rule may start its one disruption at a written period, and a rule may raise the chance
of another:

```json
{
  "horizon": 12,
  "random_disruptions": [
    {"name": "boom", "kind": "demand_shock", "target": "all", "start": 6, "notice": 2,
     "duration": 2, "factor": {"min": 1.2, "max": 2}},
    {"name": "outages", "kind": "supplier_outage", "target": "all", "chance": 0.05,
     "duration": 2, "strength": 0.5,
     "raises": {"rule": "delays", "factor": 3, "periods": 2}},
    {"name": "delays", "kind": "transport_delay", "target": "all", "chance": 0.05,
     "duration": 1, "delay": {"min": 1, "max": 2}}
  ]
}
```

- A rule with `start` starts exactly one disruption, in that period, on one target drawn
  from its `target`. It has no `chance` and no `choose`. Its `start` lies from
  `notice + 1` to the horizon.
- `raises` names another rule of the scenario in `rule`, a `factor` above 1 and a number
  of `periods`, at least 1. A start of the rule in period s multiplies the chance of the
  named rule by the factor, at most 1, in periods s + 1 to s + `periods`. Here an outage
  in period 5 raises the chance of a transport delay to 0.15 in periods 6 and 7.
- A cascade has one level. The named rule has a `chance`, no `start` and no `raises` of
  its own, and no rule names itself.

See [Disruptions](../rules/disruptions.md#cascades) for overlapping windows.

## Forecasts

A forecast entry gives the agent an estimate of the demand of coming periods for the
pairs it targets:

```json
{
  "horizon": 12,
  "forecasts": [
    {"target": "all", "periods_ahead": 3, "noise": 0.1, "noise_growth": 0.05}
  ]
}
```

- `target` has the forms of the target of a demand shape. A pair is targeted by at most
  one entry. A pair with no entry has no forecast.
- `periods_ahead` is from 1 to the horizon.
- `noise` and `noise_growth` are shares from 0 to 1. The error e of a forecast k periods
  ahead is the sum of k increments, each drawn with equal chance over its range: one
  from `-noise` to `noise` and k - 1 from `-noise_growth` to `noise_growth`. It lies
  from -(`noise` + `noise_growth` x (k - 1)) to the same value above 0. Here it lies
  within 0.1 one period ahead and within 0.2 three periods ahead.

See [Information](../rules/information.md#forecasts).

## Hidden groups

`hidden` lists the parameter groups kept from the agent:

```json
{
  "horizon": 12,
  "hidden": ["customers.products.demand", "lines.items.yield"]
}
```

Only these nine names can be listed, each once:

- `customers.products.demand`, which also hides the persistence of demand and the common
  share of every product;
- `suppliers.catalogue.punctuality`, `suppliers.catalogue.delay`,
  `suppliers.catalogue.completeness` and `suppliers.catalogue.acceptance`;
- `lines.items.yield`, `lines.breakdown_chance` and `lines.breakdown_loss`;
- `disruptions.duration`, which also keeps demand shocks out of forecasts.

What each hides is given in
[Information](../rules/information.md#hidden-parameter-groups).

## Errors

A scenario is read against its manifest. The response to the first problem is 422 with
its place, as for a manifest:

```json
{"detail": "disruptions.0.start: is not from 1 to the horizon"}
```

The form of each key is checked first: unknown and missing keys, types, places and
bounds. Then come the rules that need only the scenario, then the rules that need the
manifest or join the horizon with other keys:

| Rule | Example response |
| --- | --- |
| A hidden group is one of the nine names, listed once. | `hidden.0: is not a group that may be hidden` |
| A rule of random disruptions has a unique name; a `chance` without `start` and none with it; a `raises` that names another rule with a chance. | `random_disruptions.0.raises.rule: names its own rule` |
| A drawn duration, a drawn `delay` and `raises.periods` are at least 1. | `random_disruptions.0.duration: is below 1` |
| Every identifier names an object of the right kind in the manifest. | `start.stock.main.glass: is not an item` |
| A starting customer order names a pair the manifest has; a starting supplier order a material of the catalogue. | `start.customer_orders.0.product: is not bought by the customer` |
| A target names objects of the kind the disruption acts on, or a group of that kind with members. | `disruptions.0.target: names chip, not one of its kind` |
| Starts, due periods and arrivals lie from 1 to the horizon; no disruption is visible before period 1. | `disruptions.0.notice: is visible before period 1` |
| The starting stock and starting supplier orders of a warehouse fit its capacity and are items it accepts. | `start.stock.main: takes more space than the warehouse has` |
| A pair has at most one forecast entry, and `periods_ahead` is at most the horizon. | `forecasts.0.periods_ahead: is above the horizon` |
| Price changes never take the lowest price of a material below its salvage value or below a cancellation fee of it. A random price change counts with its smallest factor. | `disruptions.0.factor: takes the price of chip below its salvage value` |
| Every material used in a recipe can arrive within the horizon, or is in the starting stock or a starting supplier order. | `horizon: chip cannot arrive within it and is not at hand` |
| A scenario is refused when an amount of its run can reach 10 to the power 24, the largest the record holds: the quantities over the horizon, the space they can take, the largest amount per unit, or the money from both, which counts up to 1000 changeovers per unit of stock and 1000 units of repair per hour of a line. | `horizon: a run of this scenario can exceed the numbers the record holds` |

- A material can arrive within the horizon when the lead time of one of its catalogue
  entries is below the horizon. The lead time is the express lead time when the entry
  has one, and the largest value of a range.
- The bound on amounts grows with the horizon, the quantities, the prices and the
  interest rates. Every scenario of the library stays within it on the example factory
  with a horizon of 520.
