# Randomness and fairness

Every random value of a run comes from one whole number, the seed, and is fixed before
the first period.

## The seed

- The seed is a whole number from 0 to 2 to the power 128, minus 1. The harness gives it
  when it starts a run.
- A study draws its seeds at random from many possible values, so that no one can guess
  them.
- The seed is stored with the run when it starts. No response of the HTTP interface
  during the run shows it; it can be read once the run ends.
- One manifest serves many scenarios, and one scenario runs with many seeds.

## The world is drawn once

Before period 1 the simulator draws the whole world from the manifest, the scenario and
the seed:

- every parameter given as a range and drawn once per run;
- the prices drawn every period;
- the base demand of every customer and product in every period;
- the error of every forecast;
- the outcome of every delivery: on time or late, the delay, the completeness and the
  acceptance;
- the yield of every line and item in every period;
- the breakdowns of every line and their losses;
- the random disruptions.

The world is written to the record when the run starts. It stays hidden during the run.
Once the run ends, `GET /api/v1/runs/{id}/world` returns it. For every parameter it
shows the value, where the value came from (written, a group, or the built-in default)
and whether it was drawn.

## Ranges and their four distributions

A parameter is a fixed number or a range. A range has a lowest value `min`, a highest
value `max` and a distribution between them.

| `distribution` | Extra keys | Drawn value |
| --- | --- | --- |
| `uniform` (the default) | none | Every value from `min` to `max` has the same chance. |
| `triangular` | `mode` | Most likely near `mode`, less likely towards `min` and `max`. |
| `normal` | `mean`, `sd` | A normal distribution with mean `mean` and standard deviation `sd`, cut to the range. |
| `lognormal` | `median`, `spread` | Its natural logarithm is normal, with mean the logarithm of `median` and standard deviation `spread`, cut to the range. |

Rules of a range:

- `min` is at most `max`. A triangular, normal or lognormal range needs `min` below
  `max`.
- `mode`, `mean` and `median` lie within the range. `sd` and `spread` are above 0;
  `spread` is at most 10.
- A lognormal range needs `min` above 0. It gives rare high values: a long tail above
  the median.
- A whole number of periods, such as a lead time or a delay, is drawn only with equal
  chance. A range of periods from 3 to 5 gives 3, 4 or 5, each with chance 1/3.
- A drawn value is rounded to the decimal places of its kind: 3 for quantities, 4 for
  money and shares.
- A drawn value never leaves its range.

How a draw works:

- Each draw takes one chance number from 0 to 1, with equal chance.
- A uniform range turns it into `min` + (`max` - `min`) x chance number.
- A normal or lognormal range is cut to the range: the chance number is mapped onto
  the part of the distribution that lies from `min` to `max`. The draw never needs a
  second number, and values outside the range never occur.
- A normal or lognormal range much narrower than its `sd` or `spread` draws almost
  evenly over the range. A normal range from 1 to 9 with mean 5 and `sd` 10 to the power
  20 draws 1.08 at the chance number 0.01 and 8.92 at 0.99, and its `cut_mean` is 5.
- A normal or lognormal draw is computed in the binary floating point of the computer.
  Near a bound more than 6 standard deviations from the mean, or 6 spreads from the
  median in the logarithm, it loses digits and can differ between computers: 80 in a
  normal range from 40 to 80 with mean 40 and `sd` 5 is such a bound. Every other draw
  is the same on Linux, macOS and Windows.
- A chance, such as the chance of a breakdown, happens when its chance number is below
  it.

Draws from ranges of the example factory, for chance numbers 0.1, 0.5 and 0.9:

| Parameter | Range | 0.1 | 0.5 | 0.9 |
| --- | --- | --- | --- | --- |
| yield of `control-board` on `smt-line` | uniform 0.96 to 0.99 | 0.963 | 0.975 | 0.987 |
| price of `microchip` from `apac-chips` | triangular 6.0 to 7.5, `mode` 6.5 | 6.2739 | 6.634 | 7.1127 |
| demand of `industrial-controller` from `tier1-distributor` | normal 27 to 63, `mean` 45, `sd` 5.4 | 38.09 | 45 | 51.91 |
| demand of `smart-monitor` from `tier1-distributor` | lognormal 14 to 70, `median` 35, `spread` 0.4 | 21.233 | 34.468 | 54.281 |

The lognormal draw at 0.5 is below the median of 35, because the range cuts off more of
the distribution above the median than below it.

Every range in the description carries `cut_mean`, the mean of its distribution cut to
`min` and `max`, rounded half to even to 6 decimal places. A normal range keeps its own
`mean`, the uncut mean. A lognormal demand of `median` 35 and `spread` 0.4, cut to 14 to
70, has the `cut_mean` 36.222159.

## When a value is drawn

Each parameter has one moment of drawing:

| Moment | Parameters |
| --- | --- |
| Once per run | Most parameters: costs, prices, lead times, punctuality, capacities, wear, the chance of a breakdown, the times and costs of production, penalties, patience. |
| Every period | Base demand, yield, and the price of a material whose range has `drawn: period`. |
| Per event | Per delivery: delay, completeness and acceptance. Per breakdown: its loss. |

Some parameters cannot be ranges: space, recipes, persistence, the common share, the
capacity and factors of a warehouse, and the rates and credit limit of cash.

- A price is drawn once per run unless its range has `drawn: period`. A price drawn
  every period is drawn for every period before period 1 (see
  [Suppliers](suppliers.md)).
- A value drawn per event is drawn for every period in advance. A delivery outcome
  belongs to a supplier, a material, the period the order is placed and the kind of
  order. All normal orders of that material placed with that supplier in that period
  share one outcome, and all express orders share another. The outcome of a period
  with no order is drawn too, and not used.
- A breakdown draw and a loss are drawn for every line in every period.
- A rule of random disruptions draws, in every period and for every target, a number
  that decides its start or its target, a duration and an effect.
- With a common share above 0, the customers of a product share part of the chance
  number behind their demand. Each customer keeps its own range (see
  [Customers and demand](customers-and-demand.md)).

## Each stream draws on its own

Every kind of random value has its own stream of chance numbers, named by what it
draws: one parameter of one object, the demand of one customer and product, the
normal deliveries of one supplier and material, its express deliveries, the yield of
one line and item, the breakdowns of one line, one rule of random disruptions on one
target.

- A stream draws the same count of numbers whatever happens in the run.
- Adding a supplier, a customer, a line or a rule of random disruptions changes no
  other drawn value.
- Turning a fixed parameter into a range, or a uniform range into a lognormal one,
  changes no other drawn value.
- Adding a target to a rule with `choose: one` changes the choice only in the periods
  the new target wins.
- With the same versions, the same manifest, scenario and seed give the same world,
  digit for digit, on Linux, macOS and Windows, but for the draws near a bound far in a
  tail (see
  [Ranges and their four distributions](#ranges-and-their-four-distributions)).

## The same world for every agent

- No random value depends on a decision. An agent cannot change its luck.
- Two agents given the same manifest, scenario and seed face the same demand,
  deliveries, yields, breakdowns and disruptions. Their profits differ only by their
  decisions.
- A breakdown is not more likely on a line that works hard. Heavy use lowers the
  condition through wear, which is a fixed rule (see [Production](production.md)).
- The world is fixed before period 1. The reference optimizer knows the whole world and
  plans to the end of the run. Its profit is the reference that agents are compared
  with.

## Forecasts are the same for everyone

- A forecast made in period t for period t + k is the demand of period t + k times
  (1 + e), rounded to 3 decimal places and never below 0.
- The demand in a forecast leaves out the disruptions not yet visible in period t.
- The error e of a forecast k periods ahead is the sum of k increments, each drawn with
  equal chance over its range and rounded to 4 decimal places: one from `-noise` to
  `noise` and k - 1 from `-noise_growth` to `noise_growth`. It lies from -(`noise` +
  `noise_growth` x (k - 1)) to the same value above 0.
- The increments of a period are drawn once; a forecast made one period later drops
  the increment of the farthest distance.
- Every error is part of the world. So every agent with the same seed sees the
  same forecasts, whatever it decides.

See [Information](information.md) for the forecasts a scenario gives.

## Versions and replay

- Each run stores the versions of the package, of numpy and of Python that wrote it.
- The version of numpy that draws the world is fixed by the package.
- Every change of the factory rules, the observation, the measures or the record raises
  the version of the package and adds an entry to the changelog. Such a change may
  change a run with the same inputs and seed.
- Every other change leaves every response of the HTTP interface and every row of the
  record the same for the same manifest, scenario, seed and decisions, apart from the
  run identifier and the versions. Frozen runs in the test suite check this.
- After a restart of the server, an unfinished run continues from its record: the
  simulator draws the world again, checks it against the stored world, and replays the
  stored submissions. A fork replays them in the same way up to its period.
- A run is replayed only with the versions that wrote it: the same package and numpy,
  and Python with the same first two parts of its version. Other versions refuse it.
  Records of earlier versions are kept.
- The example manifest and the scenario library are frozen for a version. A change to
  them is a new version.

## Worked example

A run of `steady-market` on the example factory with seed 0 draws the yield of
`control-board` on `smt-line` once per period. Its range is uniform from 0.96 to 0.99,
so the yield is 0.96 + 0.03 x chance number. The yield is a share, so each value is
rounded half to even to 4 decimal places. The chance numbers below are shown to 4
decimal places.

- Period 1: the chance number is 0.3144, so the yield is 0.96 + 0.03 x 0.3144 =
  0.969432, rounded to 0.9694.
- Period 2: the chance number is 0.0491, so the yield is 0.96 + 0.03 x 0.0491 =
  0.961473, rounded to 0.9615.
- Period 3: the chance number is 0.9299, so the yield is 0.96 + 0.03 x 0.9299 =
  0.987897, rounded to 0.9879. A production of 400 control boards started in period 3
  gives 400 x 0.9879 = 395.16 good units, as in the worked example of
  [Period](period.md).
- A run with seed 0 and no decisions holds the same 3 yields in its world as the run of
  [Period](period.md) with its buy and produce decisions.
- With seed 1 the same stream gives the chance numbers 0.6771, 0.6156 and 0.6439, so the
  yields are 0.9803, 0.9785 and 0.9793.
