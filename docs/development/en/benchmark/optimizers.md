# Optimizers

The benchmark has 8 agents: no decisions, the reference optimizer, 5 limited optimizers
and the informed optimizer.

## The optimizers

Each agent is one module of `factory_simulator.benchmark.optimizers`:

| Agent | Module | What it knows | What it plans |
| --- | --- | --- | --- |
| `no_decisions` | `no_decisions.py` | Nothing. | An empty list of decisions every period. Its profit is the 0 of the normalized score. |
| `reference_optimizer` | `reference.py` | The whole world of the run. | The program from the period to the end of the run. Its profit is the reference, the 1 of the normalized score. |
| `full_horizon_optimizer` | `full_horizon.py` | The description and the observations. | The program from the period to the end of the run, with expected demand. |
| `rolling_optimizer` | `rolling.py` | The description and the observations. | The program over a window as long as the longest chain of lead times from a buy to a sale, plus 2 periods, with expected demand and a terminal value of stock. |
| `buffered_rolling_optimizer` | `buffered_rolling.py` | The description and the observations. | The program of the rolling optimizer, with stock at the end of its window worth 1.2 times its cost in place of 1.01. |
| `aligned_optimizer` | `aligned.py` | The description and the observations. | The program over the window of the rolling optimizer, with demand only from the open customer orders and the forecasts. |
| `informed_optimizer` | `informed.py` | The description and the observations, and the description of a twin run of its scenario with nothing hidden. | The program of the rolling optimizer, at the terminal value factor it is given, 1.01 or 1.2, with every hidden range at the `cut_mean` the twin shows. |
| `myopic_optimizer` | `myopic.py` | The description and the observations. | The program over the current period only, with a terminal value of stock and of orders still on the way. |

The full-horizon, rolling, buffered rolling, aligned and myopic optimizers are the
limited optimizers: they know only the description and the observations. The informed
optimizer is a diagnostic.

- Every optimizer solves one program of profit with HiGHS, from the real state of the
  run, every period. The program is mixed-integer when the first period of its window
  has a buy decision, or a buy decision has a minimum quantity above 0 or discount
  tiers, or a line item has a changeover time or cost above 0, and linear otherwise.
  Whether a period buys is a yes-or-no choice: a period whose cash, less what open
  supplier orders owe, is below minus the credit limit places no buy decision, as the
  engine refuses it. A linear manifest has this choice too. The example factory has all
  three, so every optimizer solves a mixed-integer program on it. Its yes-or-no choices
  are whole only in the first period of the program; in every later period they may take
  any value from 0 to 1.
- An optimizer rounds the decisions of the period down to their decimal places and
  checks them with `POST /api/v1/runs/{id}/checks` of its run. A decision the check
  rejects for lack of input, space or credit is fitted to what is available, one at a
  time from the first, and the decisions are checked again after each fit, so that a
  decision rejected only because an earlier one was rejected keeps its quantity. The
  check names one missing input at a time, so a production that lacks several inputs is
  fitted to each in turn and keeps the most that every input allows. The inputs of a
  production leave stock rounded up at each quantity, so a production fitted for space
  can still lack space; it is fitted again until it fits. The check of a buy decision
  reads its space before its credit, so a buy decision fitted for space can still lack
  credit; it is fitted for its credit too. The optimizer submits the decisions the last
  check accepts.
- A solve stops when its solution is at most 0.01 below the bound of its program, in
  money, or after 1000 nodes of HiGHS, whichever comes first, and plays the best
  solution found. HiGHS reads the profit without the part that no decision changes,
  such as the starting cash or the profit of earlier periods, so that part never moves
  where a solve stops. `time_limit`, 600 seconds by default, is one budget per solve, a
  safety net: a run with a solve stopped there depends on the speed of the computer.
- A solve that stops at a limit without a solution leaves its period without
  decisions, and the run goes on. A program HiGHS finds infeasible, or unbounded or
  infeasible, runs once more without presolve, within the same budget. A program still
  infeasible, or unbounded, stops the optimizer with an error that names the period.
- A limited optimizer counts a range at its `cut_mean`, the mean of its distribution
  cut to `min` and `max`, which the description gives. A price drawn every period
  counts at the price of the observation in its period and at its `cut_mean` later. A
  buy arrives after its lead time. Hidden groups use the assumptions below.
- Stock at the end of a window that ends before the run does, up to its expected use,
  is worth the terminal value factor times what it costs to buy or make: 1.2 for the
  buffered rolling optimizer and 1.01 for the others. Stock above that is worth its
  salvage value. On the example factory a period of storage costs 0.41 to 0.51 percent
  of that cost, so a unit held pays for about 2 periods at 1.01 and about 40 at 1.2:
  the factor sets the stock a window keeps.
- The expected use of an item counts the expected demand of the periods after the
  window, as many as the longest chain of lead times from a buy to a sale and none
  after the last period of the run. In each of these periods the demand of every
  customer and product is its mean base demand times its demand shapes and visible
  demand shocks; components and materials count what the default recipes need for
  it. Demand that a shape ends before these periods gives an expected use of 0.

The limited optimizers use these assumptions for hidden groups:

| Hidden group | Assumption |
| --- | --- |
| `customers.products.demand` | Mean of the demand of that customer and product over the periods observed whose factor of known demand shapes and visible demand shocks is above 0, with that factor divided out. A period without an order counts as 0, and an order counts in the period it arrives in. Without such a period the mean is 0. |
| `suppliers.catalogue.punctuality` | Every delivery arrives on time. |
| `suppliers.catalogue.delay` | Ignored; every delivery is planned on time. |
| `suppliers.catalogue.completeness` | The whole open quantity arrives. |
| `suppliers.catalogue.acceptance` | Every arrived unit passes inspection. |
| `lines.items.yield` | Yield is 1. |
| `lines.breakdown_chance` | Breakdown chance is 0. |
| `lines.breakdown_loss` | Breakdown loss is 0. |
| `disruptions.duration` | The disruption is planned through the end of the run. |

The informed optimizer uses the same assumptions. It gets the `cut_mean` values of a
twin run and never a value drawn for a period. Like the limited optimizers, it ignores
punctuality and delay, visible or hidden, so it plans every delivery on time.

- The program never cancels a supplier order.
- The program runs the transfers of a period in the order of its routes, by the name
  of the source, then of the destination, and the optimizer submits them in that
  order. A transfer out of a warehouse frees its space for a transfer into it later in
  that order. A unit that a transfer brings into a warehouse is not sent on in the
  same period.
- The program counts the changeovers of a period for one order of its productions: on
  each line the item it is set for first, the item it is set for at the close last,
  and the productions of one item together. The optimizer submits that order when
  each production fits the space its warehouse has left before it. Otherwise it
  submits an order in which each production fits, with as few changeovers as it
  finds. Such an order can pay more changeovers than the program counts, and their
  hours; the check then rejects a production that lacks those hours.
- Every optimizer keeps `solves`, the report of every integer solve: its period, whether
  it found a solution, whether it stopped at the node limit or the time limit, its
  `value`, `bound` and `gap` in money, its seconds, the changeovers its decisions pay
  (`changeovers`) and those its program counts (`planned_changeovers`). The `gap` is the
  bound less the value, at least 0: the most by which the solution can be below the best
  solution of its program. It also keeps `dropped`, the decisions its last check
  rejected; `fitted`, the decisions the fit changed; and `relaxed_program_value`, the
  value of the relaxed program of its first period.
- `reference_optimizer(check, customer_orders, world)` is given the world of the
  finished run of no decisions with the same scenario and seed, and the customer
  orders of every period of that run, from `customer_orders_of(read_periods(...))` of
  the module `reference.py`. Customer orders do not depend on decisions.
- `reference_optimizer(check, customer_orders, world, exact=True)` is the exact
  control: its yes-or-no choices are whole in every period of its program. A program
  of more than 100 yes-or-no choices raises `ValueError`, so it serves small worlds,
  such as a test of the reference. It is no agent of the stress test.
- `informed_optimizer(check, terminal_value_factor, shown_description)` is given the
  description of a twin run from `create_shown_description`, made with the seed of its
  run. It plans from that description and the observations of its own run, so it
  counts every hidden range at its `cut_mean` and never sees a value drawn for a
  period. A hidden duration of a disruption it plans as the limited optimizers do: to
  the end of the run.

The calibration of the scenario library is in [Stress test](stress-test.md#calibration).

This program plays the rolling optimizer on `steady-market` with seed 0:

```python
from functools import partial

import httpx2 as httpx

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer

with httpx.Client(base_url="http://127.0.0.1:8000/api/v1") as client:
    name = "Electronics factory with economies of scale"
    manifest_id = benchmark.find_manifest(client, name)
    scenario_id = benchmark.find_scenario(client, manifest_id, "steady-market")
    run = benchmark.start_run(client, scenario_id, 0)
    optimizer = rolling_optimizer(partial(benchmark.create_check, client, run["id"]))
    result = benchmark.play_run(client, run, optimizer)
    print(result["profit"], len(optimizer.solves))
```

It prints `1007491.89663264 52`. Start the server for it as in
[Quick start](../start/quick-start.md), with `--timeout-keep-alive 30` added to the
`uvicorn` command: the server then keeps an idle connection longer than the client,
which drops it after 5 seconds, while the optimizer solves.

## Purchase limit

An optimizer has a purchase limit, `purchase_budget_cap`, `None` by default. With a
limit, its program keeps the cost of the buy decisions of each period of its window at
or below the limit, at the price of their discount tier and with the express price. The
relaxed program has the same limit. The engine has no purchase limit, and cash,
acceptance and payment keep their rules. A harness can set a new limit every period and
refuse a submission whose buy decisions cost more.
