# Manifest fields

These tables define each field of a manifest. Read
[How to read the tables](#how-to-read-the-tables) and [Ranges](#ranges) first.

## How to read the tables

- A key path joins keys with dots, and writes a map key, such as an identifier, or a
  position in a list as `*`: `materials.*.space` is the `space` of every material.
- Type is the kind of a number, or text, an identifier, a list, a map or an object.
- Places is the number of decimal places of a number: 3 for quantity, space and hours;
  4 for money, share, chance, rate and factor; 0 for periods, which are whole numbers.
  A number with more places is refused; a number with fewer is padded with zeros.
- Default is the value of a key that is left out. "required" marks a key without a
  default. In a manifest, a required parameter may come from a group.
- Drawn is the moment a range is drawn from the seed: `run` once per run, `period` once
  per period, `event` once per delivery, breakdown or drawn disruption. `fixed` marks a
  number that is never a range. A number with another moment is a fixed number or a
  range.
- A rule that compares a range with another number uses the bound of the range that is
  worst for the rule.
- Changes names the measure that the key changes. See
  [Measures and the record](measures-and-the-record.md).

## Ranges

A range is an object in place of a fixed number. Its keys appear under the key of the
parameter, such as `materials.*.storage_cost.min`.

| Key | Type | Rule |
| --- | --- | --- |
| `min`, `max` | numbers of the kind of the parameter | Required. `min` is at most `max`; below `max` for a triangular, normal or lognormal range. |
| `distribution` | `uniform`, `triangular`, `normal` or `lognormal` | Default `uniform`. A range of periods is uniform only. |
| `mode` | number of the kind of the parameter | Triangular only, required. From `min` to `max`; the most likely value. |
| `mean`, `sd` | numbers of the kind of the parameter | Normal only, required. `mean` is from `min` to `max` and `sd` above 0. The normal distribution is cut to `min` to `max`. |
| `median` | number of the kind of the parameter | Lognormal only, required. From `min` to `max`; `min` is above 0. |
| `spread` | number with 4 places | Lognormal only, required. Above 0 and at most 10. The natural logarithm of the value is normal with mean the logarithm of `median` and standard deviation `spread`, cut to `min` to `max`. |
| `drawn` | `run` or `period` | Only on a range of a catalogue `price`, in the entry or in the defaults of a group. Default `run`: drawn once per run. `period`: drawn for every period before period 1; an order keeps the price of the period in which it is placed. |

A key of another distribution, or `drawn` on any other range, is refused.

The description of a run adds `cut_mean` to every range: the mean of its distribution
cut to `min` and `max`, rounded half to even to 6 decimal places. A normal range keeps
its own `mean`, the uncut mean. A lognormal demand of median 35 and spread 0.4, cut to
14 to 70, has the `cut_mean` 36.222159. A manifest or scenario that writes `cut_mean` is
refused.

## Manifest

### Top level

| Key path | Type | Default | Effect |
| --- | --- | --- | --- |
| `name` | text | none | Name of the factory. Shown to the agent; changes no run. |
| `description` | text | none | Description of the factory. Shown only. |
| `period_name` | text | none | Name of one period, such as "week". Shown only. |
| `materials` | map of identifier to material | required | Items bought from suppliers. |
| `components` | map of identifier to component | required | Items made from materials. |
| `products` | map of identifier to product | required | Items made from components and sold. |
| `suppliers` | map of identifier to supplier | required | Companies that sell materials. |
| `customers` | map of identifier to customer | required | Companies that buy products. |
| `lines` | map of identifier to line | required | Production lines. |
| `warehouses` | map of identifier to warehouse | required | Stores of items. |
| `cash` | object | required | Credit limit and interest rates. |
| `routes` | map of warehouse to map of warehouse to route | `{}` | One-way routes between warehouses. |
| `groups` | map of identifier to group | `{}` | Defaults, targets and measures shared by members. |

An identifier is lower case letters, digits and single hyphens, starts with a letter
and has at most 40 characters. Materials, components and products share one set of
identifiers; suppliers, customers, lines, warehouses and groups each have their own.

### Items

The keys of materials, components and products.

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `materials.*.name`, `materials.*.description`, `materials.*.unit`, `components.*.name`, `components.*.description`, `components.*.unit`, `products.*.name`, `products.*.description`, `products.*.unit` | text | | | none | | Shown to the agent; changes no run. | |
| `materials.*.space`, `components.*.space`, `products.*.space` | space | 3 | above 0 | required | fixed | Space one unit takes in a warehouse. | `space_used` |
| `materials.*.storage_cost`, `components.*.storage_cost`, `products.*.storage_cost` | money | 4 | at least 0 | required | run | Cost of holding one unit for one period, times the `storage_factor` of its warehouse. | `storage_cost` |
| `materials.*.salvage_value`, `components.*.salvage_value`, `products.*.salvage_value` | money | 4 | at least 0; for a material, at most its lowest price at any supplier, discounts included; for a component or product, at most the smallest, over its recipes and lines, of its inputs at their salvage values plus the `cost` of the line item | required | run | Worth of one unit in stock at the end of the run. | `stock_salvage_value` |
| `materials.*.groups`, `components.*.groups`, `products.*.groups` | list of group identifiers | | groups that exist; at most one of each kind | `[]` | | Groups whose defaults the item takes, in this order. | |
| `components.*.recipes`, `products.*.recipes` | map of recipe name to map of input identifier to quantity | 3 | at least one recipe, each with at least one input; quantities above 0; the inputs of a component are materials, of a product components | required | fixed | Units of each input used per unit started. | `stock` |
| `components.*.default_recipe`, `products.*.default_recipe` | recipe name | | one of `recipes` | the only recipe, also when written as null; required with several | fixed | Recipe of a produce decision that names none. | `stock` |
| `products.*.common_share` | share | 4 | 0 to 1; above 0 only when two or more customers buy the product with a range of `demand` | 0 | fixed | Share of the variation of demand that the customers of the product have in common. At 0 the demand of each customer varies on its own. | `units_ordered` |

### Suppliers

| Key path | Type | Bounds | Default | Effect |
| --- | --- | --- | --- | --- |
| `suppliers.*.name`, `suppliers.*.description` | text | | none | Shown only. |
| `suppliers.*.catalogue` | map of material identifier to catalogue entry | not empty; every key a material | required | The materials the supplier sells, with their terms. |
| `suppliers.*.groups` | list of group identifiers | groups that exist; at most one of each kind | `[]` | Groups whose defaults the entries of the supplier take, before the groups of the material. |

### Catalogue entries

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `suppliers.*.catalogue.*.price` | money | 4 | at least 0 | required | run, or period with `drawn: period` | Price of one accepted unit. | `material_payment` |
| `suppliers.*.catalogue.*.lead_time` | periods | 0 | at least 1 | required | run | Periods from placing an order to its arrival when on time. | `units_arrived` |
| `suppliers.*.catalogue.*.max_quantity` | quantity | 3 | above 0 | required | run | Largest quantity of the material ordered from this supplier in one period. | `decisions_rejected` |
| `suppliers.*.catalogue.*.punctuality` | chance | 4 | 0 to 1 | required | run | Chance that a delivery is on time. | `units_arrived_late` |
| `suppliers.*.catalogue.*.delay` | periods | 0 | at least 1 | required | event | Extra periods of a late delivery. | `units_arrived` |
| `suppliers.*.catalogue.*.completeness` | share | 4 | 0 to 1 | required | event | Share of the open quantity that arrives. | `units_arrived` |
| `suppliers.*.catalogue.*.acceptance` | share | 4 | 0 to 1 | required | event | Share of the arrived quantity that passes inspection and is paid. | `units_accepted` |
| `suppliers.*.catalogue.*.cancellation_fee` | money | 4 | at least 0; at most the lowest price, discounts included | 0 | run | Fee per cancelled unit. | `cancellation_fee` |
| `suppliers.*.catalogue.*.backfill_delay` | periods | 0 | at least 0 | 0 | run | Periods after a delivery when the part held back by completeness arrives; 0 loses it. | `units_lost_in_delivery` |
| `suppliers.*.catalogue.*.express_lead_time` | periods | 0 | at least 1; below `lead_time` | none: no express order | run | Lead time of an express order. | `units_arrived` |
| `suppliers.*.catalogue.*.express_cost` | money | 4 | at least 0 | required with `express_lead_time`, refused without it | run | Extra price per unit of an express order. | `material_payment` |
| `suppliers.*.catalogue.*.min_quantity` | quantity | 3 | at least 0; at most `max_quantity` | none: no minimum | run | Smallest quantity of one order. Makes `linear` false and the manifest an economies-of-scale manifest; a value of 0 adds no integer variable to a program. | `decisions_rejected` |
| `suppliers.*.catalogue.*.discounts` | list of discount tiers | | `from` rises and `price` falls from one tier to the next | `[]` | | An order takes the price of the highest tier its quantity reaches, for every unit. Makes the manifest an economies-of-scale manifest. | `material_payment` |
| `suppliers.*.catalogue.*.discounts.*.from` | quantity | 3 | from `min_quantity`, or 0 without one, to `max_quantity` | required | fixed | Smallest quantity of an order at the price of the tier. | `material_payment` |
| `suppliers.*.catalogue.*.discounts.*.price` | money | 4 | at least 0; the first tier below `price` | required | run | Price of every unit of an order that reaches the tier. | `material_payment` |

### Customers

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `customers.*.name`, `customers.*.description` | text | | | none | | Shown only. | |
| `customers.*.products` | map of product identifier to customer product | | not empty; every key a product | required | | The products the customer buys, with their terms. | |
| `customers.*.payment_terms` | periods | 0 | at least 0 | 0 | run | Periods from a shipment to its payment; 0 pays at once. | `receivables` |
| `customers.*.groups` | list of group identifiers | | groups that exist; at most one of each kind | `[]` | | Groups whose defaults the customer takes, before the groups of the product. | |

### Customer products

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `customers.*.products.*.price` | money | 4 | at least 0 | required | run | Price of one shipped unit. | `revenue` |
| `customers.*.products.*.transport_cost` | money | 4 | at least 0 | required | run | Cost of shipping one unit, times the `transport_factor` of the warehouse it leaves. | `transport_cost` |
| `customers.*.products.*.demand` | quantity | 3 | at least 0 | required | period | Base demand per period, before demand shapes and disruptions. | `units_ordered` |
| `customers.*.products.*.demand_persistence` | share | 4 | 0 to 1; only with a range of `demand` | 0 | fixed | Share p of the base demand of a period carried into the next: `base(t) = p * base(t - 1) + (1 - p) * draw(t)`. | `units_ordered` |
| `customers.*.products.*.lead_time` | periods | 0 | at least 0 | required | run | Periods from the arrival of a customer order to its due period; 0 makes it due at once. | `units_shipped_late` |
| `customers.*.products.*.patience` | periods | 0 | at least 0 | required | run | Periods after the due period before the rest of an order is lost. | `units_lost` |
| `customers.*.products.*.late_penalty` | money | 4 | at least 0 | required | run | Penalty per unit not shipped by the close of each period from the due period, but the period in which the order is lost. | `late_penalty` |
| `customers.*.products.*.lost_sale_penalty` | money | 4 | at least 0 | required | run | Penalty per unit lost. | `lost_sale_penalty` |

### Lines

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lines.*.name`, `lines.*.description` | text | | | none | | Shown only. | |
| `lines.*.warehouse` | warehouse identifier | | accepts every input and output of the line; every input can reach it along routes | the only warehouse; required with several | fixed | Warehouse the line takes its inputs from and puts its output into. | `stock` |
| `lines.*.capacity` | hours | 3 | above 0 | required | run | Production hours per period at condition 1. | `units_started` |
| `lines.*.wear_per_period` | share | 4 | 0 to 1 | required | run | Share of condition lost every period. | `condition` |
| `lines.*.wear_per_hour` | rate | 4 | at least 0; `wear_per_hour * (capacity + overtime_hours)` at most `1 - wear_per_period`, each at its largest value | required | run | Condition lost per production hour. | `condition` |
| `lines.*.breakdown_chance` | chance | 4 | 0 to 1 | required | run | Chance of a breakdown in a period. | `breakdowns` |
| `lines.*.breakdown_loss` | share | 4 | 0 to 1 | required | event | Share of condition lost in a breakdown. | `condition` |
| `lines.*.repair_cost` | money | 4 | at least 0 | required | run | Cost of restoring a condition of 1. | `repair_cost` |
| `lines.*.repair_time` | hours | 3 | above 0 | required | run | Hours used to restore a condition of 1. | `units_started` |
| `lines.*.repair_limit` | share | 4 | above 0, at most 1 | required | run | Largest condition restored in one period. | `condition` |
| `lines.*.overtime_hours` | hours | 3 | at least 0 | 0 | run | Extra production hours per period at condition 1. | `units_started` |
| `lines.*.overtime_cost` | money | 4 | at least 0 | required when `overtime_hours` can be above 0, refused when `overtime_hours` is left out or fixed at 0 | run | Cost of one overtime hour. | `overtime_cost` |
| `lines.*.items` | map of component or product identifier to line item | | not empty | required | | The items the line makes, and how. | |
| `lines.*.groups` | list of group identifiers | | groups that exist; at most one of each kind | `[]` | | Groups whose defaults the line takes, before the groups of the item. | |

### Line items

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lines.*.items.*.time` | hours | 3 | above 0 | required | run | Hours per unit started. | `units_started` |
| `lines.*.items.*.cost` | money | 4 | at least 0 | required | run | Cost per unit started. | `production_cost` |
| `lines.*.items.*.yield` | share | 4 | 0 to 1 | required | period | Share of started units that come out good. | `units_scrap` |
| `lines.*.items.*.lead_time` | periods | 0 | at least 1 | 1 | run | Production started in period t enters stock at the close of period t + `lead_time` - 1. | `stock` |
| `lines.*.items.*.changeover_time` | hours | 3 | at least 0 | none | run | Regular hours to set the line for this item. Makes `linear` false and the manifest an economies-of-scale manifest; a value of 0 adds no integer variable to a program. | `units_started` |
| `lines.*.items.*.changeover_cost` | money | 4 | at least 0 | none | run | Cost of setting the line for this item. Makes `linear` false and the manifest an economies-of-scale manifest; a value of 0 adds no integer variable to a program. | `changeover_cost` |

### Warehouses

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `warehouses.*.name`, `warehouses.*.description` | text | | | none | | Shown only. | |
| `warehouses.*.capacity` | space | 3 | above 0 | required | fixed | Space the warehouse has. | `decisions_rejected` |
| `warehouses.*.storage_factor` | factor | 4 | above 0 | 1 | fixed | Factor on the storage cost of items here. | `storage_cost` |
| `warehouses.*.transport_factor` | factor | 4 | above 0 | 1 | fixed | Factor on the transport cost of shipments from here. | `transport_cost` |
| `warehouses.*.accepts` | list of `"materials"`, `"components"`, `"products"` and groups of items | | not empty; no entry twice; every material accepted by some warehouse | all three kinds | fixed | What the warehouse may hold. | `decisions_rejected` |
| `warehouses.*.accepts.*.group` | group identifier | | a group of materials, components or products | required in a group entry | fixed | A group of items the warehouse accepts, written `{"group": "<identifier>"}`. | `decisions_rejected` |

### Routes

In `routes.*.*` the first `*` is the warehouse a route leaves and the second the
warehouse it reaches. A route joins two different warehouses, one way.

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `routes.*.*.cost` | money | 4 | at least 0 | required | run | Cost per unit transferred. | `transfer_cost` |
| `routes.*.*.lead_time` | periods | 0 | at least 0 | required | run | Periods a transfer takes; 0 arrives at once. | `stock` |

### Groups

| Key path | Type | Bounds | Default | Effect |
| --- | --- | --- | --- | --- |
| `groups.*.kind` | identifier | not `customer` or `product` | required | A free word such as `region`; an object is in at most one group of each kind. |
| `groups.*.defaults` | object | only the keys its members use | none | The values the group gives its members. |

| Key path | Members that use it | Keys it may give |
| --- | --- | --- |
| `groups.*.defaults.items` | materials, components, products | `groups.*.defaults.items.space`, `groups.*.defaults.items.storage_cost`, `groups.*.defaults.items.salvage_value`, `groups.*.defaults.items.common_share` (products only) |
| `groups.*.defaults.catalogue` | materials, suppliers | `groups.*.defaults.catalogue.price`, `groups.*.defaults.catalogue.lead_time`, `groups.*.defaults.catalogue.max_quantity`, `groups.*.defaults.catalogue.punctuality`, `groups.*.defaults.catalogue.delay`, `groups.*.defaults.catalogue.completeness`, `groups.*.defaults.catalogue.acceptance`, `groups.*.defaults.catalogue.cancellation_fee`, `groups.*.defaults.catalogue.backfill_delay`, `groups.*.defaults.catalogue.express_lead_time`, `groups.*.defaults.catalogue.express_cost`, `groups.*.defaults.catalogue.min_quantity` |
| `groups.*.defaults.line_items` | components, products, lines | `groups.*.defaults.line_items.time`, `groups.*.defaults.line_items.cost`, `groups.*.defaults.line_items.yield`, `groups.*.defaults.line_items.lead_time`, `groups.*.defaults.line_items.changeover_time`, `groups.*.defaults.line_items.changeover_cost` |
| `groups.*.defaults.customer_products` | products, customers | `groups.*.defaults.customer_products.price`, `groups.*.defaults.customer_products.transport_cost`, `groups.*.defaults.customer_products.demand`, `groups.*.defaults.customer_products.demand_persistence`, `groups.*.defaults.customer_products.lead_time`, `groups.*.defaults.customer_products.patience`, `groups.*.defaults.customer_products.late_penalty`, `groups.*.defaults.customer_products.lost_sale_penalty` |
| `groups.*.defaults.customers` | customers | `groups.*.defaults.customers.payment_terms` |
| `groups.*.defaults.lines` | lines | `groups.*.defaults.lines.capacity`, `groups.*.defaults.lines.wear_per_period`, `groups.*.defaults.lines.wear_per_hour`, `groups.*.defaults.lines.breakdown_chance`, `groups.*.defaults.lines.breakdown_loss`, `groups.*.defaults.lines.repair_cost`, `groups.*.defaults.lines.repair_time`, `groups.*.defaults.lines.repair_limit`, `groups.*.defaults.lines.overtime_hours`, `groups.*.defaults.lines.overtime_cost` |

- A key of `defaults` has the type, places, bounds and moment of drawing of the key of
  the same name in the member: `groups.*.defaults.catalogue.price` is like
  `suppliers.*.catalogue.*.price`, `drawn` included. A fixed key is given as a fixed
  number only. Discounts are never given by a group.
- A member takes a value in this order: the value written in it; the defaults of its
  groups, in the order it lists them; the built-in default. A catalogue entry asks the
  groups of the supplier, then those of the material; a customer product the groups of
  the customer, then those of the product; a line item the groups of the line, then
  those of the item.
- A range given by a group is drawn separately for every member.
- A group has at least one member, and its members are of one type. Materials,
  components and products are three types.
- A group identifier is not `materials`, `components`, `products`, `all`, `written` or
  `default`.

### Cash

| Key path | Type | Places | Bounds | Default | Drawn | Effect | Changes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cash.credit_limit` | money | 4 | at least 0 | required | fixed | The amount L. Cash below -L pays the overdraft rate, and a buy decision may not take cash, less what open supplier orders owe, below -L. | `interest_paid`, `decisions_rejected` |
| `cash.credit_interest` | rate | 4 | 0 to 1 | required | fixed | Share of cash at or above 0 earned per period. | `interest_earned` |
| `cash.debit_interest` | rate | 4 | 0 to 1; at least `credit_interest` | required | fixed | Share of cash below 0, down to -L, paid per period. | `interest_paid` |
| `cash.overdraft_interest` | rate | 4 | 0 to 1; at least `debit_interest` | required | fixed | Share of cash below -L paid per period. | `interest_paid` |
