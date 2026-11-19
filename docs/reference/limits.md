# Limits

The simulator plays one factory with linear rules and one credit check, fixed decimal
places and a reference played by an optimizer. Each of these has limits. Each limit
below has three parts: what it is, its consequence for a study, and what to do.

## Processes left out

- What: Some processes of a real factory are not in the simulator: fixed costs per
  order, all-or-nothing shipments, defects that reach customers, lots, first-in
  first-out stock, calendar dates, changes to customer orders or their due periods,
  holding hours or materials for a plan, and time in transit to a customer: a shipment
  reaches its customer in the period it is shipped.
- Consequence for a study: A study cannot ask about these processes, such as the cost
  of ordering often, the recall of bad units or a holiday on a date. A plan holds
  nothing until its start period, so it can be rejected then. Bad units appear only as
  units rejected at inspection and as scrap of production.
- What to do: Keep the question of a study within the processes the simulator has.
  Read the name of a period, such as "week", as a description only, and write seasons
  as demand shapes over periods. Expect a plan to be checked in full in its start
  period. See [Production](../rules/production.md).

## Linear rules

- What: Every rule but the credit check of a buy is linear in continuous quantities.
  12.5 units is a valid quantity. A drawn value enters a rule only as a known number
  times a decision, and no rule multiplies two quantities that depend on decisions.
  Interest is linear too. The credit check refuses a buy that takes cash, less what
  open supplier orders owe, below minus the credit limit, and it never refuses any
  other decision. So the decisions that pass it form no convex set. With cash 1, a
  credit limit of 0, a stopped line whose full repair costs 2 and chips at 1, a repair
  of 1 alone is accepted and leaves cash -1, and a buy of 1 chip alone is accepted.
  Halfway between them, a repair of 0.5 with a buy of 0.5 chip has its buy refused: the
  repair leaves cash 0. A program therefore needs a yes-or-no choice in every period
  with a buy: whether the period buys. Three more mechanisms need a yes-or-no choice:
  minimum quantities, discounts and changeovers. A manifest without any of these three
  is linear; `linear` of the manifest says which it is. `linear` describes the
  catalogue and the lines only; it does not count the credit check.
- Consequence for a study: Units are never whole by rule, so a factory that counts
  whole pieces is not modeled. No manifest has a linear program for its best
  decisions once cash can reach the credit limit. In a linear manifest the program of a
  world known in full is linear in every rule but the credit check, with one yes-or-no
  choice per period with a buy: whether the period buys, as the credit limit allows.
  Splitting an accepted decision into two with the same total gives the same stock,
  orders, condition and cash at the close of the period. Any split of the productions
  of one line and item in one period gives the same good units. Two productions of one
  line, item and recipe in one period can leave the stock of each input 0.001 below
  one production of their total, and cash apart by rounding. Any split of a buy into
  buys of the same supplier, material and warehouse in one period gives the same units
  arrived and accepted. In an economies-of-scale manifest the program has more
  yes-or-no choices, and splitting a decision can change what happens: two buys below
  the minimum quantity are rejected, where one buy of their sum is accepted.
- What to do: Use a linear manifest, such as a generated one, when a study needs a
  program whose only yes-or-no choices are whether each period buys. Give it cash that
  no cost uses up when the study needs a reference whose program is exact: the credit
  limit then never binds. Where the credit limit can bind in a later period, measure
  the policy gap of the reference with the exact control. Use the example factory to
  study minimum quantities, discounts and changeovers, and report the gaps of its
  reference (see
  [The reference: work limits and gap](#the-reference-work-limits-and-gap)). See
  [Concepts](../start/concepts.md#the-run).

## Rounding points

- What: Quantities, space and hours have 3 decimal places; money and shares have 4.
  The simulator rounds at fixed points:
  - every quantity that enters stock or an order, such as units arrived, accepted,
    good or scrap, half to even to 3 places;
  - every input item a production takes from stock, up to 3 places;
  - the unit price of a supplier order, half to even to 4 places, when it is placed;
  - the condition of a line, down to 12 places after each change;
  - the hours a line has left and the buy limit under a material shortage, down to 3
    places;
  - interest, to 4 places against the factory: interest earned down, interest paid up;
  - drawn values to the places of their kind, and base demand, forecasts and the
    quantity of a new customer order half to even to 3 places;
  - ratios and means of measures, half to even to 12 places.

  Every other amount is exact. The record keeps every amount with 12 places.
- Consequence for a study: Rounding is not a linear rule. Decisions computed exactly
  for several periods can leave a later decision 0.001 short and have it rejected. A
  decision computed in binary floating point can carry more places than its kind, and
  then the whole submission is refused. A run repeats digit for digit on every
  computer.
- What to do: Compute decisions in decimals. Round quantities down to 3 places and
  repair amounts down to 4 before sending them. Check the decisions of a period with
  the HTTP route `POST /api/v1/runs/{id}/checks` before submitting them. See
  [HTTP interface](http-interface.md#numbers).

## The reference: work limits and gap

- What: The reference is the profit the reference optimizer reaches when it plays a
  world through the simulator. In every period it solves a program of profit to the end
  of the run, from the real state and with the whole world known. It rounds the
  decisions of the period down, checks them and submits those the check accepts.
  - On a linear manifest the only yes-or-no choice of the program is whether a period
    buys.
  - When a catalogue entry has a minimum quantity above 0 or discounts, or a line item a
    changeover time or cost above 0, the program has more yes-or-no choices. Every
    yes-or-no choice, whether a period buys included, is whole only in the first period
    of the program; in every later period it may take any value from 0 to 1. A solve
    stops when its solution is at most 0.01 below the bound of its program, in money, or
    after 1000 nodes of HiGHS, whichever comes first, and plays the best solution found.
    Both are counts of work, so a solve repeats on every computer. The gap of a solve is
    the bound less the value of its solution, at least 0. HiGHS reads the profit without
    the part that no decision changes, so the starting cash and the profit of earlier
    periods leave the limit at 0.01. A program with amounts above 10 to the power 9
    counts money in a larger unit, and its limit is 0.01 of that unit. A wall-clock
    limit of 600 seconds per solve is a safety net: a run with a solve stopped there
    depends on the speed of the computer, and the stress test marks it not repeatable.
  - A period buys only when its cash, less what open supplier orders owe and the cost
    of its buys, stays at or above minus the credit limit, as the engine checks a buy.
  - The gap of a solve bounds only the program it solves. Later choices from 0 to 1
    let that program value a plan no run can follow, so the reference can earn less
    than the best policy by more than the gap. In a world of 5 periods with one order
    of 4 monitors that needs 16 chips, chips come in orders of at least 20 at 0.5000,
    and at 0.5500 in period 2. The program of period 1 counts 16 chips of period 2 at
    0.55 and is worth 171.2. The reference waits, buys 20 chips in period 2 and earns
    169.4; buying 20 chips in period 1 earns 170.4. No decision is fitted and every
    gap is below 0.01.
  - `reference_optimizer(..., exact=True)` is the exact control: every yes-or-no
    choice is whole in every period of its program. It plays programs of up to 100
    yes-or-no choices, so it serves small worlds only. The policy gap of the reference
    is the profit of the exact control less the profit of the reference: 1.0 in the
    world above. Without the minimum, with cash 10, a credit limit of 0, chips at half
    price in period 2 and one more order of 1 monitor due in period 1, the manifest is
    linear and the policy gap is 212: the reference earns what no decisions earns.
  - The program of period 1 also gives the value of the relaxed program. It is no
    bound: a run can exceed it.
  - A program HiGHS finds infeasible, or unbounded or infeasible, runs once more without
    presolve. A program still infeasible, or unbounded, stops the optimizer with an
    error that names the period. A solve that stops at a limit without a solution
    leaves its period without decisions, and the run goes on.
  - HiGHS solves the program in binary floating point, with its money in a unit: the
    smallest power of ten, at least 1, that brings every amount of money of the program
    to at most 10 to the power 9. The decisions keep their units, and the value of the
    program is in units of 1. Before any solve, the optimizer stops with
    `UnsupportedScaleError`, an error that names the period, when the program lies
    outside this scale: a number of units, hours or space is above 10 to the power 9, or
    a cost falls to 10 to the power -9 or below in the unit of money, where HiGHS drops
    it. In one period with one monitor in stock and an order for it at a price of 10 to
    the power 18, a ship decision earns 999999999999999999.0001: the unit is 10 to the
    power 9, the cost 0.0005 of a buy of 0.001 chip falls below 10 to the power -9, and
    the reference stops in period 1. At a price of 10 to the power 15 with chips up to 1
    a period, the unit is 10 to the power 7 and the reference earns
    999999999999999.0001.
  - A run of the reference on `steady-market` of the example factory takes about 83
    minutes when 14 worlds play at once on 14 logical CPUs.
- Consequence for a study: On the example factory the reference is a good set of
  decisions, not one proven best. An agent can make more profit than the reference; its
  normalized score is then above 1. A world in which the reference makes no more profit
  than no decisions has no normalized score; the stress test counts it, leaves it out of
  every score and lists it with the profits of its runs. The reference never cancels a
  supplier order and runs the transfers of a period in the order of its routes, so a
  cancellation or another order of transfers can earn more in such a world. The HTTP
  interface accepts amounts up to 10 to the power 24, so a world it accepts can lie
  outside the scale of the program. Such a world has no reference and no normalized
  score; the stress test lists it among its violations with its scenario, seed and
  error.
- What to do: Report with every result the gaps of the solves: `gap` of each solve in
  `solves` of the optimizer, in money, for a solve that stops at the gap limit and for
  one that stops at the node limit alike. Report the policy gap apart from them,
  measured with the exact control on small worlds. Check that the reference makes more
  profit than no decisions in every world before using the normalized score. Keep the
  units, hours and space of a world at most 10 to the power 9 and its amounts of money
  within 10 to the power 18 times its smallest price, cost or value per unit; a study of
  large prices counts money in thousands or millions. See
  [Normalized score](../benchmark/score.md#worked-example).

## Runs of different versions

- What: Every change of the factory rules, of the observation or of the measures raises
  the version of the package. Such a change may change a run with the same manifest,
  scenario, seed and decisions. A run replays only with the versions that wrote it:
  the same package and numpy, and Python with the same first two parts of its version.
- Consequence for a study: Two runs of different versions can differ by the rules, not
  only by the decisions. A study that compares them cannot tell the two apart.
- What to do: Play every run of one study with one version of the package. Report the
  version with every result. To compare with a run of an earlier version, play that
  agent again with the version of the study. See
  [Randomness and fairness](../rules/randomness-and-fairness.md#versions-and-replay).

## Profits of different worlds

- What: A world is fixed by the manifest, the scenario and the seed. One seed draws more
  demand than another, and one scenario cuts supply where another does not.
- Consequence for a study: Profits of different worlds do not compare as they are. A
  mean of profits over scenarios follows the scenario with the largest numbers. An
  agent played on seed 1 against another played on seed 2 is compared on luck as much
  as on decisions.
- What to do: Compare agents within one world, seed by seed. Across worlds, use the
  normalized score, which places a profit between no decisions and the reference of
  its own world. See [Normalized score](../benchmark/score.md#worked-example).

## The economy of a generated manifest

- What: In the default economy a generated manifest draws the price of every customer
  product within the prices of the example factory, whatever its product costs. A
  recipe holds up to 4 inputs at each level, so a product can cost more than any
  customer pays. With 4 materials, 4 components and 1 of each other kind, seed 2, the
  product costs at least 213.1738 a unit and a unit shipped is worth at most 179.6824;
  from cash 0 and no stock, no decisions and the reference earn the same and the world
  has no normalized score.
- Consequence for a study: In the default economy the counts change the economics as
  well as the size: with more objects a larger share of the customer products earns no
  margin. A difference between two sizes then mixes size with whether production pays.
- What to do: For a study of scale, generate the manifests with `"economy": "matched"`,
  report the economic profile of every manifest beside its results, and keep every
  world that has no normalized score in the results with its profits. See
  [Larger manifests](../guides/larger-manifests.md#the-economy-of-a-generated-manifest).

## The calibration of the scenario library

- What: The scenario library is calibrated with the stress test on three targets: every
  scenario is scorable, hard enough, and moves its named measure in its expected
  direction; see [Stress test](../benchmark/stress-test.md#calibration).
- Consequence for a study: A scenario that is not hard enough widens the gap of the
  buffered rolling optimizer to the reference less than the target asks. A scenario
  whose loss only a policy that knows a disruption before it starts avoids has no
  verdict. A study on other seeds, on another manifest or on a scenario of its own is
  not calibrated.
- What to do: Run the stress test on the scenarios and seeds of the study and read its
  `## Calibration` table. See
  [Stress test](../benchmark/stress-test.md#smallest-example).

## The numbers of the example factory

- What: The numbers of the example factory are estimates, each with a written reason,
  such as a market price or a shift of 8 hours. They are not measured in a real
  factory, and no study or document is cited for each one.
- Consequence for a study: A result holds for this factory. It does not show how an
  agent does in a real factory or in a factory of other proportions.
- What to do: Name the factory with every result. To test whether a result holds beyond
  it, repeat the study on manifests generated from counts, or on scenarios with other
  numbers. See
  [Example plant and cash](../library/example-plant-and-cash.md#sources-of-the-numbers).

## The limited optimizers

- What: The limited optimizers know only what an agent knows. They count every range
  at one value: a uniform range at the middle of `min` and `max`, a triangular range at
  the mean of `min`, `mode` and `max`, and a normal and a lognormal range at the mean of
  the distribution cut to `min` and `max`, which the description of the run gives as
  `cut_mean`. Hidden parameters use the assumptions in the
  [optimizer table](../benchmark/optimizers.md#the-optimizers). They keep no stock
  against bad luck beyond the terminal value at the end of their window.
- Consequence for a study: They plan for the expected world only. A lognormal demand,
  with its long tail above the median, is planned at its `cut_mean`.
- What to do: Read them as points of comparison that plan with expected values, not as
  the best an agent with the same knowledge can do. See
  [Optimizers](../benchmark/optimizers.md#the-optimizers).

## Lost and rejected units

- What: A unit lost on the way or rejected at inspection costs the buyer nothing: the
  supplier bears its rejects, the same for every supplier.
- Consequence for a study: A buyer can order more to make up for an outage or a quality
  drop, up to the largest order of the supplier and its cash.
- What to do: Read `units_lost_in_delivery` and `units_rejected_at_inspection` of each
  supplier beside profit.

## Cancelling a supplier order

- What: The part of a supplier order that has not arrived can be cancelled until it
  arrives, late or not. The cancellation fee per unit is the price of that option.
- Consequence for a study: An agent can buy early and cancel what it no longer needs,
  at the fee. A study of buying ahead counts the fees as part of its cost.
- What to do: Read `cancellation_fee` and `units_cancelled` of each supplier beside
  profit.

## Profit so far and salvage

- What: `profit_so_far` leaves out the salvage value of stock; only the result holds
  it.
- Consequence for a study: `profit_so_far` of the last period differs from the profit
  of the run by the salvage value of the stock at the end.
- What to do: Score a run by `profit` of its result.
