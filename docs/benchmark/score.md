# Normalized score

A normalized score compares an agent with the reference on the same world.

## Meaning of a score

- A normalized score is the share of the way from no decisions to the reference in one
  world. It ranks agents within that world.
- The reference is a heuristic policy, and its solves bound only their own programs
  (see [Limits](../reference/limits.md#the-reference-work-limits-and-gap)). A score
  above 1 is an agent that earns more than the reference. 1 minus a score is not the
  share of the best profit that the agent misses.
- An unscorable world is a world where the reference gains nothing over no decisions;
  a better policy can still exist there. In a world of 5 periods from cash 10 with a
  credit limit of 0, an order of 1 monitor lost in period 1 takes the cash, and the
  chips for an order of 4 monitors cost half in period 2. The reference waits for that
  price and then may not buy: it earns -50, as no decisions does. Buying in period 1
  earns 162.
- The reference never cancels a supplier order. In a world of 3 periods with no
  demand, a starting order of 10 chips at 0.5000 arrives in period 2, and a chip is
  worth 0.1000 at the end. No decisions and the reference keep the chips and earn -4,
  so the world is unscorable. Cancelling the order in period 1 costs only its
  cancellation fee: without a fee it earns 0.
- The reference runs the transfers of a period in the order of its routes, by the name
  of the source, then of the destination. In a world of 1 period with no demand, a
  full warehouse `main` of capacity 0.020 holds 2 chips of space 0.010, and a full
  warehouse `annex` holds 1 board of space 0.020, which costs 100 a period to store
  there and 1 in `main`. Free routes of lead time 0 go from `annex` to `main` and from
  `main` to an empty `buffer` of capacity 0.020. The route from `annex` runs first,
  into a full `main`, so the reference keeps the board in `annex` and earns -99.3, as
  no decisions does. Sending the chips to the buffer first and the board after earns
  -0.3.
- The reference counts the changeovers of a period for one order of its productions.
  In a world of 3 periods a full warehouse of capacity 1 holds 60 chips of space
  0.010 and 4 boards of space 0.100. A line of 3 hours, set for boards, makes 2 boards
  and 1 monitor of space 0.020 in period 1, 1 hour a unit, with a changeover cost of
  0.1000 to either item. The program counts 1 changeover, for the boards first. The
  2 boards add 0.16 and the monitor frees 0.18, so the reference makes the monitor
  first, pays 2 changeovers and earns 144.3. With a changeover of 0.5 hours to boards
  the boards then need 2.5 of the 2 hours left, the check rejects them, and the
  reference earns 89.9.

## Worked example

Profits of different worlds do not compare: one seed draws more demand than another.
The normalized score places a profit between two runs of the same world, that is the
same manifest, scenario and seed:

```text
normalized score = (profit - profit of no decisions)
                   / (profit of the reference - profit of no decisions)
```

- No decisions has a normalized score of 0 and the reference of 1. A normalized score
  below 0 means less profit than deciding nothing; a score above 1 means more profit
  than the reference.
- The normalized score is a `Decimal`, rounded half to even to 12 decimal places.
- A world in which the reference makes no more profit than no decisions has no
  normalized score: it is unscorable.
- In the calibration of the scenario library over seeds 0 to 4, the reference makes
  more profit than no decisions in every world.
- The reference plays its decisions through the engine. Its optimizer also keeps the
  value of the relaxed program of period 1, in `relaxed_program_value`: the program
  with every yes-or-no choice allowed any value from 0 to 1. It is no bound: a run can
  make more profit.

In a run of `steady-market` on the example factory with seed 0, no decisions makes
-675663.4617, the reference 1144661.93211454 and the rolling optimizer 1007491.89663264.
The normalized score of the rolling optimizer is:

```text
(1007491.89663264 + 675663.4617) / (1144661.93211454 + 675663.4617)
= 1683155.35833264 / 1820325.39381454
= 0.924645321134
```
