# Scenario library

The library holds 23 scenarios of 52 periods for the example factory. Each scenario
exercises a named mechanism. Agents with the same seed face the same world.

## Common start

The factory starts with no cash, about three periods of materials and components and one
quarter of a period of finished products. The credit limit is 80000.
`distribution-centre` holds 22.500 `industrial-controller`, 23.750 `smart-monitor` and
20.000 `sensor-gateway`. There are no starting supplier orders. `cash-squeeze` changes
cash, `full-warehouse` changes the stock mix at `main-plant`, and `product-life-cycle`
removes `sensor-module` and `sensor-gateway`.

Each named measure is compared with `steady-market` at the same seed. The expected
direction is a calibration target. One seed does not establish it. Measures of lost
sales are read without the reference. The run description hides the scenario name and
its written disruptions. Disruptions become visible from their notice. See
[Information](../rules/information.md).

## The steady market

### `steady-market`

Demand stays at its usual level for 52 periods, with no disruption or demand shape. The
factory starts with three periods of materials and components, one quarter of a period
of finished products and no cash.

## Demand

### `seasonal-demand`

Demand follows four seasons of 13 periods at 0.2, 0.6, 6 and 0.4 times its usual level.
The peak needs stock built during the preceding low seasons.

Watch: `units_transferred.routes.main-plant/distribution-centre` rises.

### `growth`

Demand of every product grows by 5 percent per period, reaching about 12 times its
initial level in period 52.

Watch: `units_lost.total` rises.

### `decline`

Demand of every product falls by 12 percent per period, reaching about 0.15 percent of
its initial level in period 52. Buy decisions and production must stop before stock
becomes stranded.

Watch: `units_lost.total` falls.

### `demand-surge`

Demand of `smart-monitor` rises without notice to eight times its usual level in periods
14 to 41.

Watch: `units_lost.total` rises.

### `demand-step`

Demand of every product rises to six times its usual level from period 11 to the end.

Watch: `units_lost.total` rises.

### `product-life-cycle`

`sensor-gateway` launches without stock of `sensor-module` or of finished products.
Demand rises steeply to three times its usual level around period 6 and ends abruptly in
period 20. The steepness of the s-curve is 1.4.

Watch: `units_lost.products.sensor-gateway` falls.

## Suppliers

### `supplier-outage`

In periods 10 to 41 `apac-chips` delivers nothing and `emea-electronic-parts` cannot
sell `microchip-b`. Both chip sources stop without notice.

Watch: `units_arrived.suppliers.apac-chips/microchip` falls.

### `transport-delays`

Every first supplier delivery due in periods 12 to 41 arrives 16 periods later.
Backfills keep their own schedule.

Watch: `units_arrived_late` rises.

### `quality-crisis`

Acceptance of `emea-electronic-parts` is multiplied by 0.001 in periods 9 to 40. It is
the only source of `pcb-blank` and `connector-pins`.

Watch: `units_lost.total` rises.

### `material-shortage`

The maximum order of `microchip` and `microchip-b` is zero in periods 10 to 41. Neither
source accepts a chip purchase during the shortage.

Watch: `units_lost.total` rises.

### `price-change`

`microchip` costs four times its usual price for purchases placed in periods 8 to 39,
without notice. The second chip, `microchip-b`, keeps its price, and only the
alternative recipe of `control-board` uses it; `sensor-module` has no other recipe.
Chips bought ahead compete for credit.

Watch: `material_payment.total` rises.

## Lines

### `line-breakdown`

`final-assembly-line` loses all its condition in period 18 and has no regular or
overtime hours in periods 22 to 37.

Watch: `units_lost.total` rises.

### `frequent-breakdowns`

`final-assembly-line` has an 80 percent chance per period of losing 60 to 90 percent of
its condition, in addition to its own breakdowns. It has no hours in periods 34 to 41.

Watch: `units_lost.total` rises.

### `capacity-cut`

`smt-line` has no regular or overtime hours in periods 18 to 41. `power-module` can move
to `module-assembly-line`; `control-board` and `sensor-module` have no other line.

Watch: `units_started.lines.smt-line` falls.

### `yield-drop`

Production started on `smt-line` in periods 7 to 40 yields 95 percent fewer good units.
A base yield of 0.975 becomes 0.04875.

Watch: `units_scrap.lines.smt-line` rises.

## Cash and space

### `cash-squeeze`

The factory starts with cash of -120000, which is 40000 below -80000, minus its credit
limit, and one quarter of a period of finished products. Purchases are refused until
payments for the stock it sells bring cash, less open commitments, back within the
credit limit.

Watch: `units_lost.total` rises.

### `full-warehouse`

`main-plant` is full, with the usual starting stock value concentrated in `enclosure`,
`lcd-panel`, `connector-pins` and `copper-wire`. It has no other materials or
components. Production of `cable-harness` can release space for missing input items.
Stock is 6347.380 `enclosure`, 820.615 `lcd-panel`, 1554 `connector-pins` and 2823
`copper-wire`.

Watch: `units_shipped_late.total` rises.

## Information

`forecasts` and `hidden-groups` change more than one key against `steady-market`:
`forecasts` hides demand and gives forecasts, and `hidden-groups` also multiplies
demand. Their named measures compare whole scenarios. The stress test measures each
information treatment alone, against a control that differs in that treatment only; see
[Stress test](../benchmark/stress-test.md).

### `forecasts`

Customer base demand is hidden. Forecasts cover the next six periods, with error up to
20 percent one period ahead and an additional increment up to 4 percent at each further
distance. The error bound six periods ahead is 40 percent.

Watch: `units_lost.total` of the rolling optimizer falls.

### `notice`

Both chip sources stop in periods 10 to 41, exactly as in `supplier-outage`. Both
restrictions are visible from period 6, four periods before they start.

Watch: `units_arrived.suppliers.apac-chips/microchip` falls.

Watch also: `units_lost.total` of the rolling optimizer falls against `supplier-outage`.

### `hidden-groups`

Demand is multiplied by 2.5 from period 1. Base demand, supplier delivery and inspection
parameters, line yield and breakdown parameters are hidden.

Watch: `profit_so_far.total` of the rolling optimizer falls.

## Two changes at once

### `regional-crisis`

Suppliers of the region `apac` lose all deliveries that arrive in periods 16 to 41.
First deliveries due during the crisis arrive 16 periods later.

Watch: `units_lost.total` rises.

### `surge-and-breakdown`

Demand of `smart-monitor` rises to eight times its usual level in periods 14 to 41, and
`smt-line` loses all its condition in period 16.

Watch: `units_lost.total` rises.

## Results

A diagnostic on one seed checks these definitions. Results:
[Stress test](../benchmark/stress-test.md).
