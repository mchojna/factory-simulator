# Measures and the record

Profit is the one number that scores a run. Beside it, the simulator records 61 measures
in every period, for the whole factory and for each customer, product, supplier, line,
warehouse, route and group.

## Result

`GET /api/v1/runs/{id}/result` gives the result once the run is finished:

| Key | Holds |
| --- | --- |
| `seed` | The seed of the run. |
| `periods` | The number of periods, the horizon. |
| `profit` | The profit of the run. |
| `cash_at_start`, `cash_at_end` | The cash before period 1 and at the close of the last period. |
| `receivables` | The receivables still open at the end. |
| `terms` | Each term of profit: `revenue`, every cost, `interest_paid`, `interest_earned`, `late_penalty`, `lost_sale_penalty` and `salvage`, costs as positive numbers. |
| `measures` | Every measure of the whole run, by key, then by name. |

Profit equals `cash_at_end - cash_at_start + receivables + salvage`; see
[Cash and profit](../rules/cash-and-profit.md). A run of `steady-market` on the example
factory with seed 7 and no decisions ends with `cash_at_start` 0, `cash_at_end`
-736765.4409, `receivables` 0 and `salvage` 27434.2103. Its profit is -736765.4409 - 0 +
0 + 27434.2103 = -709331.2306.

## Flows, levels and ratios

Every measure is one of three kinds:

- A flow counts what happened in a period, such as the units shipped. Over a run it is
  summed.
- A level is a value at the close of a period, such as the cash or the stock. Over a run
  it is its value at the close of the last period.
- A ratio divides two running totals, from period 1 to the period, such as the units
  shipped on time over the units shipped. Over a run it is its value in the last period.
  A ratio with a total of 0 below the line is `null`. Every ratio and every mean is
  rounded half to even to 12 decimal places.

## Keys

| Key | Measures of |
| --- | --- |
| `total` | The whole factory. |
| `customers.<c>` | One customer. |
| `products.<p>` | One product. |
| `pairs.<c>/<p>` | One customer and one product. |
| `warehouses.<w>` | One warehouse. |
| `warehouses.<w>/<i>` | One item in one warehouse. |
| `suppliers.<s>/<m>` | One material from one supplier. |
| `lines.<l>` | One line. |
| `lines.<l>/<i>` | One item on one line. |
| `routes.<from>/<to>` | One route. |
| `groups.<g>` | One group. |
| `reasons.<reason>` | One reason of rejection, for `decisions_rejected` only. |

- In the result and in `GET /api/v1/runs/{id}/periods`, the measures are nested by the
  first part of the key: `measures.total.service`,
  `measures.customers["retail-chain"].service`,
  `measures.pairs["retail-chain/smart-monitor"].service`.
- Every measure kept per customer, product, supplier and material, line or item is also
  kept per group, under `groups.<g>`. See [Groups](../rules/groups.md).

## Measures

### Money

| Measure | Kind | Keys | Counts |
| --- | --- | --- | --- |
| `revenue` | flow | total, customers, products, pairs | The price of the units shipped, paid or not. |
| `material_payment` | flow | total | What accepted units of supplier orders cost. |
| `production_cost` | flow | total | The cost of production started. |
| `overtime_cost` | flow | total, lines | The cost of overtime hours. |
| `changeover_cost` | flow | total, lines | The cost of changeovers. |
| `repair_cost` | flow | total | The cost of repairs. |
| `transport_cost` | flow | total, warehouses | The transport of shipments, at the warehouse they leave from. |
| `transfer_cost` | flow | total, routes | The cost of transfers, in the period a transfer is sent. |
| `storage_cost` | flow | total, warehouses | The storage of stock, and of transfers on the way at their destination. |
| `cancellation_fee` | flow | total, suppliers | Fees of cancelled parts of supplier orders. |
| `interest_paid`, `interest_earned` | flow | total | Interest on cash below 0 and on cash at or above 0. |
| `late_penalty` | flow | total, customers, products, pairs | Penalties for units not yet shipped, in every period from the due period but the one in which the order is lost. |
| `lost_sale_penalty` | flow | total, customers, products, pairs | Penalties for lost sales. |
| `cash` | level | total | The cash at the close. |
| `profit_so_far` | level | total | Cash at the close, less cash at the start, plus receivables at the close. |
| `receivables` | level | total, customers | Receivables open at the close. |
| `periods_below_credit_limit` | flow | total | 1 in a period whose cash, after interest, is below minus the credit limit. |

- Every cost is a positive number. Payments of customers have no measure of their own:
  `revenue` counts shipments.
- `profit_so_far` leaves out the salvage value of stock.

### Customers

| Measure | Kind | Keys | Counts |
| --- | --- | --- | --- |
| `units_ordered` | flow | total, customers, products, pairs | Units of customer orders placed. Orders of the starting state count in period 1. |
| `units_shipped` | flow | total, customers, products, pairs | Units shipped. |
| `units_shipped_on_time` | flow | total, customers, products, pairs | Units shipped in a period at or before the due period of their order. |
| `units_shipped_late` | flow | total, customers, products, pairs | Units shipped after the due period of their order. |
| `units_lost` | flow | total, customers, products, pairs | Units of lost sales. |
| `units_past_due` | flow | total, customers, products, pairs | The full quantity of the orders whose due period is the period, counted at its close. |
| `units_past_due_on_time` | flow | total, customers, products, pairs | The units of those orders shipped on time, counted at the same close. |
| `service` | ratio | total, customers, products, pairs | `units_past_due_on_time` over `units_past_due`: of the units of orders whose due period has passed, the share shipped on time. |
| `on_time_share` | ratio | total, customers, products, pairs | `units_shipped_on_time` over `units_shipped`: of the units shipped, the share shipped on time. |
| `orders_in_full_on_time_share` | ratio | total, customers, products, pairs | Of the closed orders, the share shipped in full by the due period. |
| `mean_lateness` | ratio | total, customers, products, pairs | Periods late times units, over the units shipped late: how late a late unit is, on average. |

- `service` counts an order once its due period has passed, shipped or not. An agent
  that ships nothing has `service` 0. `on_time_share` counts shipped units only, so with
  nothing shipped it is `null`. The fill rate, `units_shipped` over `units_ordered`, is
  no measure of the record.
- Each lost sale is an event `lost_sale` with `quantity`, `amount` and `at_end`.
  `at_end` is true when the end of the run loses the order before its patience has run
  out, and false when the last period of its patience has come.

### Lines

| Measure | Kind | Keys | Counts |
| --- | --- | --- | --- |
| `units_started` | flow | lines, lines with item | Units started, in the start period. |
| `units_good` | flow | lines, lines with item | Good units, in the ready period. |
| `units_scrap` | flow | lines, lines with item | Scrap, in the ready period. |
| `hours_available` | flow | lines | The regular hours the line has in the period: capacity times cut times condition, rounded down to 3 decimal places, as the observation shows them. |
| `regular_hours` | flow | lines | Regular hours of production. |
| `overtime_hours` | flow | lines | Overtime hours. |
| `repair_hours` | flow | lines | Hours of repair. |
| `changeover_hours` | flow | lines | Hours of changeovers. |
| `changeovers` | flow | lines | Changeovers, also those whose time and cost are 0. |
| `breakdowns` | flow | lines | Breakdowns. |
| `condition` | level | lines | The condition at the close. |
| `utilisation` | ratio | lines | Regular hours of production plus hours of changeovers, over the capacity of the line, both summed from period 1. Repair and overtime hours count in neither; the capacity counts in full under a capacity cut. |

### Suppliers

| Measure | Kind | Keys | Counts |
| --- | --- | --- | --- |
| `units_ordered_from_suppliers` | flow | suppliers | Units of supplier orders placed. |
| `units_arrived` | flow | suppliers | Units that arrived. |
| `units_accepted` | flow | suppliers | Arrived units that passed inspection. |
| `units_rejected_at_inspection` | flow | suppliers | Arrived units that failed inspection and were returned. |
| `units_lost_in_delivery` | flow | suppliers | Units lost: the missing part of a delivery without backfill, and the share a supplier outage holds back. |
| `units_cancelled` | flow | suppliers | Units cancelled. |
| `units_arrived_late` | flow | suppliers | Units that arrived after the period of placing plus the lead time used. Every unit of a backfill counts as late. A starting supplier order arrives in its written arrival period and never counts as late. |

### Warehouses and routes

| Measure | Kind | Keys | Counts |
| --- | --- | --- | --- |
| `stock` | level | warehouses, warehouses with item | Stock at the close. |
| `stock_salvage_value` | level | warehouses, warehouses with item | Stock at the close times its salvage value. |
| `stock_space` | level | warehouses with item | The space the stock of an item takes at the close. |
| `space_used` | level | warehouses | The space the stock takes at the close. |
| `units_used` | flow | warehouses with item | Units of the item that production started in the period takes from the stock of the warehouse as inputs. |
| `units_transferred` | flow | routes | Units transferred, in the period a transfer is sent. |

`space_used` counts stock only. The space a warehouse holds against its capacity also
counts production not yet in stock, open supplier orders and transfers on the way; see
[Warehouses and routes](../rules/warehouses-and-routes.md).

### Decisions

| Measure | Kind | Keys | Counts |
| --- | --- | --- | --- |
| `decisions_accepted` | flow | total | Outcomes accepted. |
| `decisions_rejected` | flow | total, reasons | Outcomes rejected, in total and per reason, such as `reasons.not_enough_stock`. |
| `plans_made` | flow | total | Plans made, in the period they are made. |
| `plans_run` | flow | total | Plans executed, in their start period. |
| `plans_rejected` | flow | total | Plans rejected, in their start period. |
| `plans_cancelled` | flow | total | Plans cancelled, in the period of the cancel decision. |
| `observation_size` | flow | total | The number of characters of the observation, written as canonical JSON. |

- An outcome counts in the period it is reported. A plan counts when it is made and
  again in its start period.
- A produce decision rejected when it is made is not a plan. It counts only in
  `decisions_rejected`.
- `observation_size` tells how much text an agent reads. A run of `steady-market` on the
  example factory with seed 7 and no decisions reads 734151 characters over its 52
  periods.

## Tables of the record

The server keeps every run in one DuckDB database file. A period is written whole or not
at all. Every table of a run has the column `run_id`. Outside the 3 operation tables,
which [Operational record](operational-record.md) describes, no row holds a clock time,
a host name or a file location, and two runs with the same manifest, scenario, seed and
decisions give the same rows, apart from the run identifier and the versions.

| Table | One row per | Holds |
| --- | --- | --- |
| `manifests` | manifest | Its identifier, the SHA-256 of its content; the manifest as its author wrote it; `linear`. |
| `scenarios` | scenario | Its identifier, the SHA-256 of the identifier of its manifest and its content; the manifest it belongs to; the scenario with its defaults written. |
| `runs` | run | Its identifier, scenario, seed as decimal text, current period, `finished`, description, and the versions of the package, numpy, Python, pydantic and DuckDB and the platform. A fork also holds `forked_from` and `forked_from_period`. |
| `worlds` | run | The world: every drawn and fixed parameter with its origin, prices drawn every period, base demand, forecasts and their errors, deliveries of normal and of express orders, yields, breakdowns and disruptions. |
| `periods` | closed period | The observation, the submission with its defaults filled in, the state at the close that the agent may see, and the private state: the arrival period of every open buy and of its backfill. |
| `traces` | step or decision | Period, position in the order of execution, step, kind, reference, decision identifier, normalized input, outcome and the complete snapshots before and after. |
| `events` | event | Period, position, step, kind, the identifier of the object it concerns and its other fields. |
| `ledger` | movement of cash | Period, position, step, kind, amount, cash after it, and the identifier it belongs to. |
| `outcomes` | outcome | Period, position, decision identifier, kind of decision, accepted or not, reason, and the whole outcome. |
| `measures` | period, measure and key | `name`, `key` and `value`, such as `service`, `customers.retail-chain` and 0.95; `value` is null for a ratio with a total of 0 below the line. |
| `results` | finished run | Profit, cash at the start and at the end, receivables, the terms of profit and the measures of the whole run. |
| `interactions` | check or refused submission | Position from 1 per run, the period of the run, `kind` (`check` or `refusal`), the submission, the outcomes of a check, and the reason of a refusal. |
| `operation_identities` | operation | The position of the operation in the order of all operations, from 1. |
| `operations` | request, startup or shutdown | The request and its response: the resources it names, the encoded path, the selected headers, the times, the state and what the transport reports. |
| `operation_bodies` | chunk of a body | The operation, the direction, the position, the exact bytes and their SHA-256. |
| `schema_version` | database | The version of the package that created the database. |

- `position` orders the rows of one period in the order things happened. Among the
  outcomes of a period, the plans come first.
- Every decimal is stored with 12 decimal places.
- A database made by another version of the package does not open; the server stops with
  both versions in the message.
- Over HTTP, the private state, the interactions and the trace are readable only through
  the export. See [Information](../rules/information.md).

### Transition trace

The snapshot of a step holds every field of the state except the trace. The snapshot of
a decision holds `plant` and `ledger` as they are when the decision runs, with hours,
reservations, repairs and pending production. `kind` is `step` or the kind of the
decision, and `reference` names the period or the object. `decision_id` is null for a
step; `input` and `outcome` are null when absent. Decimals inside the JSON are exact;
read them with a JSON reader that keeps decimals.

Each of the 6 steps has a row in every period, also a step that changes nothing. The
rows of decisions come before the row of the execution step. A plan keeps the identifier
of its decision. Its outcome can come first in the list of outcomes even when a shipment
runs before it.

A factory with no storage cost, wear or interest starts with cash 1000, 16 chips and 8
boards; a board uses 2 chips and costs 1, a monitor 2 boards and costs 2. The submission
holds a buy decision of 6 chips at 0.5, produce decisions of 2 boards and 2 monitors,
and a ship decision for an unknown order. The rejected ship decision changes nothing.
After production the snapshots hold 12 chips, 4 boards and cash 994. The close adds 2
boards and 2 monitors. 4 lost sales at 10 leave cash 954. The delivery of chips in the
next period gives 18 chips and cash 951.

The first 3 steps of a period stay in memory until the period closes. One transaction
then stores the closed period with its whole trace. A restart rebuilds the steps of the
open period from the record, once each, and checks the traces of the closed periods. A
check of decisions leaves the trace unchanged.

## Export file

`GET /api/v1/runs/{id}/export` gives a finished run as one ZIP file named
`<run id>.zip`. It gives a 409 response during the run. It is readable without the
package.

| File | Holds |
| --- | --- |
| `periods.parquet`, `events.parquet`, `ledger.parquet`, `outcomes.parquet`, `measures.parquet`, `traces.parquet`, `worlds.parquet`, `results.parquet`, `interactions.parquet` | The rows of the run in each table. |
| `manifest.json` | The manifest, as canonical JSON. |
| `scenario.json` | The scenario, as canonical JSON. |
| `run.json` | The row of the run in `runs`, with the seed and the description, as canonical JSON. |
| `operations.parquet` | The operations of the run. |
| `operation_bodies.parquet` | The exact bodies of their requests and responses, in chunks. |
| `operations.json` | The format, the last operation included and the references to bodies held outside the export. |

- The Parquet files hold JSON columns as UTF-8 text and decimals as `DECIMAL(38, 12)`.
- The bodies of earlier exports appear as references; the offline bundle holds their
  bytes. See [Operational record](operational-record.md).
- `run.json` names the versions that wrote the run; report them with the results. See
  [Reporting the version](#reporting-the-version).
- Analyze a study with DuckDB in one of two ways:
  - Read the database file of the server once the server has stopped. The server is the
    only process that opens it while it runs. Every run of the server is in it, so one
    query compares agents, scenarios and seeds.
  - Read the Parquet files of the exports, which hold one run each.

The first query reads the database file, the second a Parquet file of an export:

```python
import duckdb

records = duckdb.connect("data/records/runs.duckdb", read_only=True)
records.sql(
    "select runs.seed, results.profit "
    "from runs join results on results.run_id = runs.id "
    "order by results.profit desc"
)
duckdb.sql(
    "select period, value from 'measures.parquet' "
    "where name = 'cash' and key = 'total' order by period"
)
```

### Reporting the version

A result names everything that makes it repeatable:

- the version of the package, and of numpy and Python: `package_version`,
  `numpy_version` and `python_version` in `run.json` of the export;
- the manifest and the scenario, by name and by identifier; an identifier is the SHA-256
  of their content, so the same identifier means the same content;
- the seeds;
- the settings of each optimizer, such as `time_limit`.

The example manifest and the scenario library are frozen for a version. A change to
them, or to a rule of the factory, the observation or the measures, raises the version
of the package. A run is replayed only with the versions that wrote it. See
[Randomness and fairness](../rules/randomness-and-fairness.md).
