# Decisions

The agent acts through six kinds of decision. Each decision is one JSON object with the
key `kind`: `ship`, `cancel`, `transfer`, `repair`, `produce` or `buy`. The harness
sends the decisions of one period together, in one submission. A rejected decision comes
back with a reason and the numbers behind it. Decisions can be checked first, without
changing the run.

## The six decisions

| Decision | What it does |
| --- | --- |
| Ship | Sends a quantity of an open customer order from a warehouse to the customer. |
| Cancel | Ends a quantity of a supplier order that has not arrived, for a fee per unit, or ends a plan, without a fee. |
| Transfer | Moves a quantity of an item along a route from one warehouse to another. |
| Repair | Restores an amount of the condition of a line. |
| Produce | Starts a quantity of an item on a line with a recipe, now or in a later period, in regular hours or in overtime. |
| Buy | Places a supplier order for a quantity of a material, into a warehouse, as a normal or an express order. |

The examples below use the example factory. The meaning of every reason is in
[Reasons of rejection](#reasons-of-rejection).

### Ship

```json
{"kind": "ship", "order": "order-1-1", "quantity": 10.000, "warehouse": "distribution-centre"}
```

- `order`: the identifier of an open customer order.
- `quantity`: the units to ship. It may be less than the open quantity; the rest of the
  order stays open.
- `warehouse`: the warehouse the units leave from. It may be left out when the manifest
  has one warehouse.

Reasons, in the order checked: `unknown_order`, `unknown_warehouse`,
`over_open_quantity`, `not_enough_stock`.

When accepted, the stock falls, the revenue is earned and the transport cost is paid.
The customer pays at once or later, by its payment terms. See
[Customers and demand](customers-and-demand.md).

### Cancel

```json
{"kind": "cancel", "order": "buy-1-6", "quantity": 100.000}
```

- `order`: the identifier of an open supplier order (`buy-...`) or of a plan
  (`make-...`).
- `quantity`: the units of the supplier order to cancel. A cancel decision for a plan
  has no `quantity`.

Reasons, in the order checked: `unknown_order`, `wrong_quantity`, `over_open_quantity`,
`below_min_quantity`, `below_discount_tier`.

- A cancel decision that leaves part of a supplier order open must leave the quantity
  ordered, less all its cancellations, at or above the minimum quantity of the material
  and the quantity of the discount tier the order was priced at. Supplier orders of the
  starting state are not checked against the minimum quantity.
- The order keeps its unit price.
- The cancellation of a supplier order pays the cancellation fee of the catalogue for
  every unit cancelled. An order with nothing left open closes.

See [Suppliers](suppliers.md). The cancellation of a plan is in [Plans](#plans).

### Transfer

```json
{"kind": "transfer", "item": "industrial-controller", "quantity": 30.000, "source": "main-plant", "destination": "distribution-centre"}
```

- `item`: the item to move.
- `quantity`: the units to move.
- `source` and `destination`: the warehouses at the two ends of a route.

Reasons, in the order checked: `unknown_route`, `not_accepted`, `not_enough_stock`,
`transferred_this_period`, `not_enough_space`.

When accepted, the stock of `source` falls at once and the cost of the route per unit is
paid. The units reach `destination` after the lead time of the route. From `main-plant`
to `distribution-centre` this is 1 period at 0.8 per unit. See
[Warehouses and routes](warehouses-and-routes.md).

### Repair

```json
{"kind": "repair", "line": "smt-line", "amount": 0.0500}
```

- `line`: the line to repair.
- `amount`: the condition to restore, above 0 and at most 4 decimal places.

Reasons, in the order checked: `unknown_line`, `over_repair_limit`,
`over_full_condition`, `not_enough_hours`.

When accepted, the repair uses `amount * repair_time` hours of the line in this period
and pays `amount * repair_cost` at once. The condition rises at the close of the period.
On `smt-line`, a repair of 0.05 uses 0.05 x 16 = 0.8 hours and costs 0.05 x 2500 = 125.
See [Production](production.md).

### Produce

```json
{"kind": "produce", "line": "smt-line", "item": "control-board", "quantity": 200.000, "recipe": "standard", "overtime": false}
```

- `line`: the line that makes the item.
- `item`: the component or product to make.
- `quantity`: the units to start.
- `recipe`: one of the recipes of the item. Left out, it is the default recipe of the
  item.
- `overtime`: true to make the units in overtime hours. Left out, it is false.
- `start`: the period in which production starts. Left out, it is the current period. A
  later period makes a plan; see [Plans](#plans).

Reasons, in the order checked: `start_outside_horizon`, `unknown_line`,
`line_cannot_make_item`, `unknown_recipe`, `not_enough_hours`, `not_enough_input`,
`not_enough_space`.

When accepted, the input items leave the stock of the warehouse of the line at once, the
hours are used and the production cost is paid. A line set for another item, or for
none, first changes over, for the changeover hours and cost of the item. In the example,
in period 1 of `steady-market`, `smt-line` is set for no item. 400 `microchip`, 200
`pcb-blank` and 200 `passive-kit` leave stock, the line uses 2 + 200 x 0.14 = 30 hours
and the factory pays 300 + 200 x 4.9 = 1280. See [Production](production.md).

### Buy

```json
{"kind": "buy", "supplier": "apac-chips", "material": "microchip", "quantity": 500.000, "warehouse": "main-plant", "express": true}
```

- `supplier`: the supplier to order from.
- `material`: a material in the catalogue of the supplier.
- `quantity`: the units to order.
- `warehouse`: the warehouse the delivery goes to. It may be left out when the manifest
  has one warehouse.
- `express`: true for an express order: a shorter lead time for an extra price per unit.
  Left out, it is false.

Reasons, in the order checked: `unknown_supplier`, `not_in_catalogue`,
`unknown_warehouse`, `not_accepted`, `no_express`, `below_min_quantity`,
`over_max_quantity`, `not_enough_space`, `over_credit_limit`.

When accepted, a supplier order is placed. Its unit price is set when it is placed.
Nothing is paid now; accepted units are paid when they arrive. `apac-chips` delivers
`microchip` in a lead time drawn from 3 to 5 periods (4 with seed 0), or in 2 periods as
an express order for 1.625 more per unit. See [Suppliers](suppliers.md) and
[Cash and profit](cash-and-profit.md).

## The submission

The harness sends a submission to `POST /api/v1/runs/{id}/decisions` as
`{"period": 7, "decisions": [...]}`, with the number of the current period.

- A submission may hold any number of decisions of any kinds, in any order. An empty
  list is valid: the period closes with no decision.
- Each decision gets the identifier `<period>-<n>`, with n its position in the list
  from 1. What an accepted decision creates carries the same period and n: `ship-7-1`,
  `cancel-7-2`, `transfer-7-3`, `repair-7-4`, `make-7-5`, `buy-7-6`.
- A number is a JSON number or decimal text. A quantity is above 0 with at most 3
  decimal places.
- A submission is refused whole, and the run stays in its period, when it names another
  period than the current one, or has an unknown key, a value of the wrong type, a
  quantity or amount not above 0 or with too many decimal places, or a ship or buy
  decision without `warehouse` in a manifest with several warehouses. The record keeps
  every such refused submission as an interaction, apart from the run.
- The record and the outcomes hold each decision with its defaults filled in.

## Order of execution

The decisions are executed by kind: every ship decision first, then every cancel,
transfer, repair, produce and buy decision. Within a kind they are executed in the order
of the submission. Plans that start in the period are executed first among the produce
decisions, by identifier. Each decision is checked against the state that the decisions
accepted before it leave.

The order has these consequences:

- A ship decision uses only the stock present when the decisions start. A transfer,
  production or supplier order of the same period adds nothing it can use.
- A transfer decision uses only the stock present when the transfers start.
- The space that cancel decisions free counts for the later decisions, and a buy
  decision no longer counts what the cancelled units would have cost.
- Repair hours are taken before any production hour of the period.
- The check of the credit limit sees the cash after every other decision of the period.
- A plan cannot be cancelled in the period it is made.

## Executed whole or rejected whole

- A decision that passes every check is executed in full.
- A decision that does not pass a check is rejected in full. It gets the reason of the
  first check it does not pass, with the numbers behind it, and the state does not
  change.
- The simulator never lowers a quantity to make a decision fit.
- Only a buy decision is rejected for lack of cash. Every other decision is executed
  even when it takes cash below 0 or below minus the credit limit.

The outcomes of a period come back in the observation of the next period, in the order
of execution. An accepted outcome holds `decision_id`, `decision`, `accepted: true` and
`reference`, the identifier of what it created. A rejected outcome holds `decision_id`,
`decision`, `accepted: false`, `reason` and, for most reasons, `asked` and `available`.
For example, a buy decision for 2500 `microchip` from `apac-chips`, which sells at most
2000 per period, is rejected with `over_max_quantity`, `asked` 2500 and `available`
2000.

## Reasons of rejection

`asked` and `available` are in the unit of the check: units, hours, condition, space or
money. A dash means the outcome has no such number.

| Reason | Decisions | Rejected when | `asked` | `available` |
| --- | --- | --- | --- | --- |
| `unknown_order` | ship, cancel | The customer order or supplier order does not exist or is closed, or the plan does not exist or has already run. | - | - |
| `unknown_warehouse` | ship, buy | The warehouse does not exist. | - | - |
| `unknown_route` | transfer | No route goes from `source` to `destination`. | - | - |
| `unknown_line` | repair, produce | The line does not exist. | - | - |
| `unknown_supplier` | buy | The supplier does not exist. | - | - |
| `unknown_recipe` | produce | The recipe is not one of the recipes of the item. | - | - |
| `not_in_catalogue` | buy | The material is not in the catalogue of the supplier. | - | - |
| `line_cannot_make_item` | produce | The line does not make the item. | - | - |
| `not_accepted` | transfer, buy | The item does not exist, or the warehouse does not accept it. The outcome names the `item`. | - | - |
| `wrong_quantity` | cancel | A plan is named with a quantity, or a supplier order without one. | - | - |
| `start_outside_horizon` | produce | `start` is before the current period or after the horizon. | - | - |
| `no_express` | buy | The order is express, and the supplier has no express lead time for the material. | - | - |
| `over_open_quantity` | ship, cancel | The quantity is above the open quantity of the order. | quantity | open quantity |
| `not_enough_stock` | ship, transfer | The quantity is above the stock of the item in the warehouse. | quantity | stock |
| `transferred_this_period` | transfer | The quantity is above the stock of the item in the source less the units that transfers of lead time 0 brought there in the period. | quantity | stock less the units brought in by transfers of lead time 0 |
| `over_repair_limit` | repair | The amount, with the repairs of the line accepted earlier in the period, is above the repair limit of the line. | amount | repair limit less repairs accepted |
| `over_full_condition` | repair | The amount, with the repairs of the line accepted earlier in the period, would take the condition above 1. | amount | 1 less condition less repairs accepted |
| `not_enough_hours` | repair, produce | The hours needed are above the hours the line has left in the period under the limits of [Hours and condition](production.md#hours-and-condition). A produce decision in overtime checks its changeover hours against the regular hours first, then its production hours against the overtime hours. | hours needed | the fewest hours left under the limits that apply |
| `not_enough_input` | produce | An input item is short in the warehouse of the line. The outcome names the first short `item` by identifier. | input needed | its stock |
| `not_enough_space` | transfer, produce, buy | The space the warehouse holds after the decision would be above its capacity; see [Open orders hold their space](warehouses-and-routes.md#open-orders-hold-their-space). | space the decision adds | capacity less space held before |
| `below_min_quantity` | buy, cancel | A buy decision is below the minimum quantity, or a cancel decision leaves the order below it. | quantity, or quantity left after the cancellation | minimum quantity |
| `below_discount_tier` | cancel | The cancel decision leaves the order below the quantity of the discount tier it was priced at. | quantity cancelled | quantity left before the cancellation, less the quantity of the tier |
| `over_max_quantity` | buy | The quantity, with the orders of the material from the supplier accepted earlier in the period, is above the largest quantity the supplier takes per period, cut by any active material shortage. | quantity | largest quantity less orders accepted earlier |
| `over_credit_limit` | buy | Cash, less what open supplier orders still owe, less the cost of this buy decision, would fall below minus the credit limit. | quantity times unit price | cash plus credit limit less what open orders owe; may be below 0 |

## Checking without executing

`POST /api/v1/runs/{id}/checks` takes the same body as a submission. Its response is
`{"outcomes": [...]}`: the outcome each decision would have if submitted now.

- The outcomes, in the order of execution, are those that submitting the same decisions
  in the same period gives. The check changes nothing in the run.
- A check may be made any number of times in a period.
- The record keeps every check as an interaction, apart from the run.
- A check that names another period, or breaks the form of a submission, is refused like
  a submission. A finished run takes no check.

## Plans

A plan is a produce decision with a `start` after the current period, such as
`{"kind": "produce", "line": "smt-line", "item": "control-board", "quantity": 200.000, "start": 3}`.

- When it is made, only four checks apply: `start` is within the horizon, the line
  exists, the line makes the item and the recipe is one of the recipes of the item. A
  plan that passes is accepted, with a reference such as `make-1-5`.
- A plan holds no hours, no input items and no space, pays nothing, and does not change
  the item the line is set for.
- Every observation lists every plan not yet started, with its defaults filled in.
- A cancel decision without a quantity ends a plan, up to and in its start period,
  without a fee: `{"kind": "cancel", "order": "make-1-5"}`.
- In its start period, the plan goes through every check of a produce decision against
  the state at that moment, like a decision made in that period. A plan that does not
  pass a check is rejected with its reason. A plan that passes becomes a production with
  the same identifier.
- Its outcome comes with the outcomes of its start period, listed first. It holds the
  `decision_id` and `decision` of the decision that made it: `1-5` for `make-1-5`.
- Its start period is the start period of the production, for yield and for an active
  yield drop.

## Worked example

A run of `steady-market` on the example factory with seed 0. In period 1 the agent
submits six decisions, one of each kind, in the order buy, produce, repair, transfer,
cancel and ship. A check of the six gives the same outcomes as the submission. The
simulator executes them by kind, so the outcomes come back in the reverse order:

| Decision | Outcome |
| --- | --- |
| `1-6`: ship 22.5 units of `order-1-1` from `distribution-centre` | Accepted as `ship-1-6`. |
| `1-5`: cancel 100 units of `buy-1-1` | Rejected with `unknown_order`: cancel decisions are executed before buy decisions, so `buy-1-1` does not exist yet. |
| `1-4`: transfer 30 `industrial-controller` from `main-plant` to `distribution-centre` | Rejected with `not_enough_stock`, `asked` 30 and `available` 0. |
| `1-3`: repair 0.05 of the condition of `smt-line` | Rejected with `over_full_condition`, `asked` 0.05 and `available` 0: the condition of the line is 1. |
| `1-2`: produce 200 `control-board` on `smt-line` | Accepted as `make-1-2`. |
| `1-1`: buy 500 `microchip` from `apac-chips` into `main-plant` | Accepted as `buy-1-1`. |

- The shipment pays transport of 22.5 x 3.84 x 0.85 = 73.44 at once. Its revenue, 22.5 x
  152 = 3420, is paid by `equipment-maker` in period 7.
- The production pays 300 for the changeover and 200 x 4.9 = 980. At the close of period
  1, 193.88 good units enter stock and 6.12 units are scrap.
- The supplier order `buy-1-1` has the unit price 6.3762 and is expected in period 5.
  Nothing is paid for it in period 1.
- The three rejected decisions change nothing. After storage costs and interest, cash at
  the close of period 1 is -1828.26249.
