# Questions

Short statements on common points, each with the page that holds its rule.

## A run needs no language model

The simulator uses no language model. An agent is any program, or a person, that
returns decisions. The optimizers of the package solve linear and mixed-integer
programs. See [Optimizers](../benchmark/optimizers.md#the-optimizers).

## The same seed gives the same world

The same manifest, scenario and seed give the same world, digit for digit, on Linux,
macOS and Windows, with the same versions. Every agent then meets the same
demand, deliveries, yields, breakdowns and disruptions. The run also depends on the
decisions: the same decisions in the same world give the same record, apart from the
run identifier and the versions. See
[Randomness and fairness](../rules/randomness-and-fairness.md).

## An agent sees ahead only through forecasts and notice

The agent gets the description once and an observation every period. Neither holds the
seed, the world, or the demand, deliveries, yields and breakdowns of coming periods. It
sees ahead only through the forecasts and the disruptions with notice that a scenario
gives. Any caller of the HTTP interface can read a manifest and a scenario, with their
written disruptions; an agent reads only the description, its observations, the periods
of its run already closed and the outcomes of its checks. See
[Information](../rules/information.md#what-is-never-shown).

## A rejected decision names its reason

A decision is rejected when it breaks a rule of the factory, such as a ship decision
above the stock. Its outcome, in the next observation, gives the reason and, for most
reasons, the numbers `asked` and `available`. The HTTP route
`POST /api/v1/runs/{id}/checks` gives the same outcomes before submitting. A submission
refused with 409 or 422 is another thing: its body breaks the form or names another
period, the whole submission is refused, and the run stays in its period. See
[Decisions](../rules/decisions.md#reasons-of-rejection) and
[HTTP interface](http-interface.md#errors).

## Cash can go below zero

Cash below zero pays interest at the debit rate down to minus the credit limit,
and at the higher overdraft rate below it. Only a buy is refused for cash: when cash,
less what open supplier orders owe, less the cost of the buy, would fall below minus
the credit limit. Costs that are not buys can still take cash below the limit. See
[Cash and profit](../rules/cash-and-profit.md#the-credit-limit-on-buys).

## Two agents compare on the same seeds

Play both on the same manifest, scenario and seeds, so each pair of runs meets the same
world. Compare them seed by seed. Across scenarios, use the normalized score, which
places a profit between no decisions and the reference of its own world. See
[Randomness and fairness](../rules/randomness-and-fairness.md#the-same-world-for-every-agent),
[Normalized score](../benchmark/score.md#worked-example) and
[Limits](limits.md#profits-of-different-worlds).

## A result names its versions

The export of a run holds the version of the package and the versions of numpy and
Python: `package_version`, `numpy_version` and `python_version` in `run.json`. Report
with them the name and identifier of the manifest and of the scenario, the seeds and the
settings of each agent. Runs of different versions are not compared. See
[Measures and the record](measures-and-the-record.md#reporting-the-version) and
[Limits](limits.md#runs-of-different-versions).
