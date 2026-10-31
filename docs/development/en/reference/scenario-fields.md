# Scenario fields

These tables define each field of a scenario. Read
[How to read the tables](manifest-fields.md#how-to-read-the-tables) and
[Ranges](manifest-fields.md#ranges) first.

## Scenario

Every number of a scenario is a fixed number, except the duration and the effect of a
random disruption.

### Top level

| Key path | Type | Places | Bounds | Default | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | text | | | none | Name of the scenario. Never shown to the agent. | |
| `description` | text | | | none | Description of the scenario. Never shown to the agent. | |
| `horizon` | periods | 0 | 1 to 520; every material used in a recipe can arrive within it or is at hand | required | Number of periods of a run. | every flow |
| `start` | object | | | empty | State of the factory before period 1. | |
| `demand_shapes` | list of demand shapes | | | `[]` | Factors on base demand over time. | `units_ordered` |
| `forecasts` | list of forecast entries | | at most one entry per pair of customer and product | `[]` | Forecasts of demand in each observation. | the `forecasts` of the observation |
| `disruptions` | list of written disruptions | | | `[]` | Disruptions at written periods, numbered `disruption-1`, `disruption-2` and so on, in the order of `start - notice`, then of the list. | the measure of each kind |
| `random_disruptions` | list of rules of random disruptions | | names unique | `[]` | Rules that draw disruptions from the seed. | the measure of each kind |
| `hidden` | list of names of hidden parameter groups | | the nine names below, each once | `[]` | Parameters kept from the agent. | the description and the observations |

### Start

| Key path | Type | Places | Bounds | Default | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- |
| `start.cash` | money | 4 | may be below 0 | 0 | Cash before period 1. | `cash` |
| `start.stock` | map of warehouse identifier to map of item identifier to quantity | 3 | at least 0; items the warehouse accepts; with the starting supplier orders to the warehouse, fits its capacity | `{}`: 0 of every item | Stock before period 1. | `stock` |
| `start.condition` | map of line identifier to share | 4 | 0 to 1 | `{}`: 1 for every line | Condition before period 1. | `condition` |
| `start.set_for` | map of line identifier to item identifier | | an item the line makes | `{}`: no item | Item each line is set for. With changeovers, the first production of a line set for no item pays one. | `changeovers` |
| `start.customer_orders` | list of customer orders | | | `[]` | Customer orders open at the start. Each arrived in period 0 and has the price, patience and penalties of its pair. | `units_ordered` |
| `start.customer_orders.*.customer` | customer identifier | | a customer | required | Customer of the order. | |
| `start.customer_orders.*.product` | product identifier | | a product the customer buys | required | Product of the order. | |
| `start.customer_orders.*.quantity` | quantity | 3 | above 0 | required | Units ordered. | `units_ordered` |
| `start.customer_orders.*.due` | periods | 0 | 1 to `horizon` | required | Due period of the order. | `units_shipped_late` |
| `start.supplier_orders` | list of supplier orders | | | `[]` | Supplier orders on the way at the start. Each was placed in period 0 at the drawn price, the price of period 1 when the price is drawn every period, without discount or express. It arrives in full and accepted, and can be cancelled. | `units_arrived` |
| `start.supplier_orders.*.supplier` | supplier identifier | | a supplier | required | Supplier of the order. | |
| `start.supplier_orders.*.material` | material identifier | | a material of the catalogue of the supplier | required | Material of the order. | |
| `start.supplier_orders.*.quantity` | quantity | 3 | above 0 | required | Units ordered. | `units_arrived` |
| `start.supplier_orders.*.arrival` | periods | 0 | 1 to `horizon` | required | Period in which the order arrives. | `units_arrived` |
| `start.supplier_orders.*.warehouse` | warehouse identifier | | a warehouse that accepts the material | the only warehouse; required with several | Warehouse the order goes to. | `stock` |

### Demand shapes

Every key of a demand shape changes `units_ordered`. In period t, the demand of a pair
is its base demand times the factor of every shape that targets it.

| Key path | Type | Places | Bounds | Kinds | Effect |
| --- | --- | --- | --- | --- | --- |
| `demand_shapes.*.kind` | `trend`, `season`, `step`, `ramp` or `s_curve` | | required | all | The form of the factor. |
| `demand_shapes.*.target` | `"all"`, an object with `customer`, `product` or both, or a group `{"<kind>": "<group>"}` | | required; a pair the manifest has; a group of customers or products whose kind matches | all | The pairs of customer and product the shape multiplies. |
| `demand_shapes.*.target.customer` | customer identifier | | a customer | all | One customer; every customer when left out. |
| `demand_shapes.*.target.product` | product identifier | | a product | all | One product; every product when left out. |
| `demand_shapes.*.rate` | rate | 4 | above -1 | `trend` | Factor `(1 + rate) ** (t - 1)`. |
| `demand_shapes.*.factors` | list of factors | 4 | at least one; each at least 0 | `season` | Factor `factors[((t - 1) // period_length) % len(factors)]`. |
| `demand_shapes.*.period_length` | periods | 0 | at least 1 | `season` | Periods each factor lasts. |
| `demand_shapes.*.period` | periods | 0 | any whole number | `step` | First period of `factor`. The factor is 1 before it. |
| `demand_shapes.*.factor` | factor | 4 | at least 0 | `step` | Factor from `period` on. |
| `demand_shapes.*.first` | periods | 0 | any whole number | `ramp` | Last period of `from_factor`. |
| `demand_shapes.*.last` | periods | 0 | after `first` | `ramp` | First period of `to_factor`. Between `first` and `last` the factor moves in a straight line. |
| `demand_shapes.*.middle` | periods | 0 | any whole number | `s_curve` | Period half way between the two factors. |
| `demand_shapes.*.steepness` | rate | 4 | above 0 | `s_curve` | Speed of the change: factor `from_factor + (to_factor - from_factor) / (1 + exp(-steepness * (t - middle)))`. |
| `demand_shapes.*.from_factor` | factor | 4 | at least 0 | `ramp`, `s_curve` | Factor before the change. |
| `demand_shapes.*.to_factor` | factor | 4 | at least 0 | `ramp`, `s_curve` | Factor after the change. |

### Forecasts

Every key of a forecast entry changes the `forecasts` of the observation.

| Key path | Type | Places | Bounds | Default | Effect |
| --- | --- | --- | --- | --- | --- |
| `forecasts.*.target` | as `demand_shapes.*.target` | | a pair is targeted by at most one entry | required | Pairs that get a forecast. |
| `forecasts.*.target.customer` | customer identifier | | a customer | every customer | One customer. |
| `forecasts.*.target.product` | product identifier | | a product | every product | One product. |
| `forecasts.*.periods_ahead` | periods | 0 | 1 to `horizon` | required | Periods each forecast looks ahead. |
| `forecasts.*.noise` | share | 4 | 0 to 1 | required | Width of the error one period ahead. |
| `forecasts.*.noise_growth` | share | 4 | 0 to 1 | required | Width of each further increment. The error e of a forecast k periods ahead is the sum of k increments, each drawn with equal chance over its range: one from `-noise` to `noise` and k - 1 from `-noise_growth` to `noise_growth`. It lies from -(`noise` + `noise_growth` x (k - 1)) to the same value above 0. |

### Written disruptions

| Key path | Type | Places | Bounds | Default | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- |
| `disruptions.*.kind` | one of the nine kinds below | | | required | What the disruption acts on and how. | |
| `disruptions.*.target` | list of identifiers, `"all"`, or a group `{"<kind>": "<group>"}` | | objects of the kind the disruption acts on, or a group of them with members; a list not empty and with no identifier twice | required | Objects the disruption acts on. | |
| `disruptions.*.start` | periods | 0 | 1 to `horizon` | required | First period it acts. | the measure of its kind |
| `disruptions.*.duration` | periods | 0 | at least 1; not allowed for `line_breakdown` | required | Periods it acts. | the measure of its kind |
| `disruptions.*.notice` | periods | 0 | at least 0; `start - notice` at least 1 | 0 | Periods before `start` from which it is visible. | the `disruptions` of the observation |
| `disruptions.*.strength` | share | 4 | 0 to 1 | required for its kinds | Effect of `supplier_outage`, `quality_drop`, `material_shortage`, `capacity_cut` and `yield_drop`. | the measure of its kind |
| `disruptions.*.delay` | periods | 0 | at least 1 | required for its kind | Effect of `transport_delay`. | `units_arrived_late` |
| `disruptions.*.factor` | factor | 4 | above 0; price changes keep the lowest price of a material at or above its salvage value and its cancellation fees | required for its kinds | Effect of `demand_shock` and `price_change`. | the measure of its kind |
| `disruptions.*.loss` | share | 4 | 0 to 1 | required for its kind | Effect of `line_breakdown`. | `condition` |

| `kind` | Target | Effect key | Effect while it acts | Changes |
| --- | --- | --- | --- | --- |
| `supplier_outage` | suppliers | `strength` | Arriving quantity from the supplier times (1 - strength). | `units_arrived` |
| `quality_drop` | suppliers | `strength` | Acceptance of deliveries from the supplier times (1 - strength). | `units_rejected_at_inspection` |
| `transport_delay` | suppliers | `delay` | A delivery due in a period it acts arrives `delay` periods later. | `units_arrived_late` |
| `material_shortage` | materials | `strength` | `max_quantity` of the material at every supplier times (1 - strength). | `decisions_rejected` |
| `price_change` | materials | `factor` | Price of the material at every supplier times `factor`, for orders placed while it acts. | `material_payment` |
| `demand_shock` | products | `factor` | Demand of the product from every customer times `factor`. | `units_ordered` |
| `line_breakdown` | lines | `loss` | Condition times (1 - loss), once, in its start period. | `condition` |
| `capacity_cut` | lines | `strength` | Capacity and overtime hours times (1 - strength). | `units_started` |
| `yield_drop` | lines | `strength` | Yield of production started while it acts times (1 - strength). | `units_scrap` |

Two disruptions of the same kind on the same target multiply their effects, except
`delay`, which adds.

### Random disruptions

| Key path | Type | Places | Bounds | Default | Drawn | Effect |
| --- | --- | --- | --- | --- | --- | --- |
| `random_disruptions.*.name` | identifier | | unique in the scenario | required | | Name of the rule. It keys the random stream of the rule. |
| `random_disruptions.*.kind` | one of the nine kinds | | | required | | As for a written disruption. |
| `random_disruptions.*.target` | as `disruptions.*.target` | | as for a written disruption | required | | Objects the rule may hit. Each drawn disruption hits one. |
| `random_disruptions.*.chance` | chance | 4 | 0 to 1 | required without `start`; refused with it | fixed | Chance that a disruption starts in a period: on each target, or once with `choose`. |
| `random_disruptions.*.choose` | `"one"` | | refused with `start` | none | | With `"one"`, at most one disruption starts in a period, on the target with the smallest draw. |
| `random_disruptions.*.start` | periods | 0 | `notice + 1` to `horizon` | none | fixed | The one period in which the rule starts its one disruption, on one target drawn from `target`. |
| `random_disruptions.*.notice` | periods | 0 | at least 0 | 0 | fixed | Periods before its start from which a disruption is visible, from period 1 at the earliest. A rule keeps every start it draws. |
| `random_disruptions.*.duration` | periods | 0 | at least 1; a fixed number or a uniform range; not allowed for `line_breakdown` | required | event | Periods each disruption acts. |
| `random_disruptions.*.strength` | share | 4 | 0 to 1 | required for its kinds | event | Effect, as for a written disruption. |
| `random_disruptions.*.delay` | periods | 0 | at least 1; a fixed number or a uniform range | required for its kind | event | Effect of `transport_delay`. |
| `random_disruptions.*.factor` | factor | 4 | above 0; a price change counts with its smallest factor against salvage values and cancellation fees | required for its kinds | event | Effect of `demand_shock` and `price_change`. |
| `random_disruptions.*.loss` | share | 4 | 0 to 1 | required for its kind | event | Effect of `line_breakdown`. |
| `random_disruptions.*.raises` | object | | | none | | A cascade: after each start of this rule, the chance of another rule is raised. |
| `random_disruptions.*.raises.rule` | rule name | | another rule of the scenario, with a `chance` and without `start` or `raises` | required | | The rule whose chance is raised. |
| `random_disruptions.*.raises.factor` | factor | 4 | above 1 | required | fixed | The chance of the named rule is multiplied by it, at most 1. |
| `random_disruptions.*.raises.periods` | periods | 0 | at least 1 | required | fixed | A start in period s raises the chance in periods s + 1 to s + `periods`. Where windows overlap, the largest factor counts, once. |

A random disruption changes the measure of its kind, as a written disruption does. The
duration and the effect of a drawn disruption are the values drawn in its start period.

### Hidden parameter groups

The names that `hidden` may list:

| Name | What it hides |
| --- | --- |
| `customers.products.demand` | The demand of every customer and product, its persistence, and the common share of every product. |
| `suppliers.catalogue.punctuality` | The chance that a delivery is on time. |
| `suppliers.catalogue.delay` | The extra periods of a late delivery. |
| `suppliers.catalogue.completeness` | The share of the open quantity that arrives. |
| `suppliers.catalogue.acceptance` | The share of the arrived quantity that passes inspection. |
| `lines.items.yield` | The share of started units that come out good. |
| `lines.breakdown_chance` | The chance of a breakdown of a line. |
| `lines.breakdown_loss` | The share of condition a breakdown takes. |
| `disruptions.duration` | The duration of every disruption and rule; no forecast holds a demand shock. |

A hidden group is left out of the description and every observation, the defaults of
groups included. See [Information](../rules/information.md#hidden-parameter-groups).
