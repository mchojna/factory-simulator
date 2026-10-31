# Glossary

Every page uses these words with these meanings. A word in the last column means the
same thing in other tools or papers; the documentation does not use it.

## Runs and inputs

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Run | One agent planning one world from the first period to the last. | episode, game, session, simulation |
| Period | One step of time in a run, numbered from 1. It has no calendar date. | week, tick, round, turn |
| Horizon | The number of periods in a run. | length, duration |
| Manifest | The document that describes the factory: its items, partners, lines, warehouses, groups and their parameters. | config, world config, factory config |
| Scenario | The document that describes how a run goes over time: horizon, starting state, demand shapes, forecasts, disruptions and hidden parameter groups. | case, setting |
| Seed | The whole number given at the start of a run. Every random value of the world is drawn from it. | random state, world seed, run seed |
| World | Every value drawn from the seed for a run, fixed before the first period. | tape, realization, sample |
| Parameter | A number in the manifest or the scenario that changes what happens in a run. It is a fixed number or a range. | setting, knob, constant |
| Range | A lowest and a highest value, with a distribution between them, from which a parameter is drawn. | interval, spread, bounds |
| Descriptive field | A name, unit or description that helps a person read a manifest or a scenario. It does not change a run. | label, metadata, comment |
| Group | A set of objects of one type that share default values, can be the target of a disruption and have their own measures, such as a region of suppliers or a segment of products. | tag, label, class, cluster |
| Linear manifest | A manifest in which no catalogue entry names a minimum quantity or discounts and no line item names a changeover time or cost. The name describes the catalogue and the lines only: its program still has a credit choice in every period with a buy. | LP mode, simple manifest |
| Economies-of-scale manifest | A manifest in which a catalogue entry names a minimum quantity or discounts, or a line item names a changeover time or cost. Its program has yes-or-no choices for them, beside the credit choices. A value of 0 adds no integer variable. | nonlinear manifest, integer manifest, MILP mode, complex manifest |
| Generated manifest | A manifest made by the simulator from counts of objects and a seed. The same counts and seed give the same manifest. | random manifest, synthetic factory |
| Matched economy | The economy of a generated manifest in which the price of every customer product is the lowest cost of its product times a ratio from 1.8124 to 2.4250, so every customer product earns a margin at every count. The default economy, `unrestricted`, draws prices within those of the example factory. | productive mode, balanced economy |
| Economic profile | What the text of a generated manifest says of its economics before any run: the lowest cost, best margin and service value of every customer product, the useful demand coverage, the margin share and the class `profitable`, `penalty-driven` or `unproductive`. | economic controls, economic qualification |
| Hidden parameter group | A parameter, in every object that has it, whose value or range the scenario keeps from the agent. | secret, masked field |
| Key path | The keys from the top of a manifest or a scenario to one value, joined by dots, such as `materials.*.space`. | JSON path, pointer |

## Items and recipes

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Item | Anything the factory stores: a material, a component or a product. | SKU, part, good, stock keeping unit |
| Material | An item bought from a supplier. | raw material, input, commodity |
| Component | An item made on a line from materials. | part, subassembly, intermediate |
| Product | An item made on a line from components and sold to customers. | finished good, SKU, article |
| Recipe | A named list of input items and their quantities needed to make one unit of a component or a product. An item may have several recipes. | bill of materials, BOM, formula |

## Partners

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Supplier | A company that sells materials to the factory. | vendor, source |
| Catalogue | The materials one supplier sells, each with its price and delivery parameters. | offer, price list |
| Catalogue entry | One material in the catalogue of a supplier, with its price and delivery parameters. | offer line, SKU |
| Customer | A company that buys products from the factory. | client, buyer, account |
| Customer product | One product a customer buys, with its price, demand and penalties. Its measures sit under the key `pairs.<customer>/<product>`. | account product, pair |

## Factory

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Line | A production line that makes components or products at one warehouse. | machine, workstation, resource |
| Line item | One item a line makes, with its hours, cost and yield per unit. | routing, operation |
| Capacity | The production hours a line has in one period; for a warehouse, the space it has. | throughput, availability |
| Hours available | The regular hours of a line in a period: its capacity times the cut times its condition. | uptime, free hours |
| Utilisation | The regular production and changeover hours of a line over its capacity. | load, occupancy, efficiency |
| Condition | The state of a line, from 0 to 1. A line can use its capacity times its condition for production; at 0 it makes nothing. | health, quality, wear level |
| Wear | The loss of condition in a period, from passing time and from production hours. | degradation, ageing |
| Breakdown | A sudden loss of a share of the condition of a line. | failure, fault |
| Repair | The restoration of condition of a line, chosen by the agent. | maintenance, fix |
| Overtime | Extra production hours of a line in a period, at a cost per hour. | extra shift, overload |
| Changeover | The hours and cost of setting a line for an item, from another item or from no item. | setup, switch, retooling |
| Production | A quantity of an item started on a line in one period, until it enters stock. | run, job, work in progress |
| Batch | The productions of one line and item started in one period. Their good units are rounded once, together. | lot, production run |
| Input use | The units of an item a production takes from stock as its inputs. | consumption, usage |
| Plan | A production decided in one period to start in a later period. | schedule, booking |
| Yield | The share of started units that come out good. | quality, efficiency |
| Scrap | Started units that come out bad. Their input items are lost. | waste, defects, rejects |
| Lead time | The number of periods something takes: from placing a supplier order to its delivery, from a customer order to its due period, from starting production to stock, or along a route. | latency, cycle time |

## Storage

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Warehouse | A store with a capacity of space that holds the items it accepts. | inventory, storage, stock room, location |
| Space | The room an item takes in a warehouse, and the room a warehouse has. | volume, size |
| Stock | The quantity of an item in a warehouse. | inventory, on hand |
| Route | A one-way connection between two warehouses with a cost per unit and a lead time. | lane, link, path |
| Storage factor | The factor of a warehouse on the storage cost of the stock it holds. | storage multiplier |
| Transport factor | The factor of a warehouse on the transport cost of the shipments that leave it. | transport multiplier |
| Transfer | A quantity of an item moved along a route from one warehouse to another. | move, shipment, relocation |

## Orders and flows

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Supplier order | An order for a material placed with a supplier. | purchase order, PO, procurement |
| Express order | A supplier order with a shorter lead time for an extra price per unit. Its delivery values are drawn apart from those of the normal orders of the same period. | rush order, expedite |
| Minimum quantity | The smallest quantity a supplier accepts in one order of a material. | MOQ, minimum order |
| Discount | A lower price per unit for every unit of an order that reaches a given quantity. | rebate, volume price, price break |
| Discount tier | A quantity from which an order of a material pays a lower price for every unit. | price break, bracket |
| Delivery | A supplier order, or its missing part, reaching its warehouse. | receipt, shipment |
| Punctuality | The chance that a delivery arrives on time. | reliability, on-time rate |
| Completeness | The share of the open quantity of a supplier order that arrives. | fill share |
| Acceptance | The share of the arrived quantity of a delivery that passes inspection; only accepted units are stored and paid. | pass rate, quality rate |
| Delay | The extra periods a late delivery takes after its lead time. | lag, slip |
| Backfill | The later delivery of the part of a supplier order that completeness held back. | back order, redelivery |
| Delivery batch | The normal or the express supplier orders of one supplier, material and warehouse placed in one period that arrive in one period, or their backfills. Their units sent, arrived and accepted are rounded once, together. | shipment, consignment |
| Cancellation | The end of a plan, or of the part of a supplier order that has not arrived, the latter for a fee per unit. | withdrawal, abort |
| Base demand | The quantity a customer would order of a product in a period, before demand shapes and disruptions. | mean demand, baseline |
| Demand shape | A factor over time that multiplies base demand: trend, season, step, ramp or s-curve. | pattern, profile, curve |
| Persistence | The share of the base demand of the previous period that carries into the next. | autocorrelation, memory, inertia |
| Common share | For one product, the share of the variation of demand that all its customers share in a period, from 0 to 1, at the same total variation. At 0 the demand of each customer varies on its own. | correlation, common factor, shared shock |
| Customer order | An order for a product placed by a customer. | sales order, demand, request |
| Due period | The period by which a customer order should be shipped. | deadline, due date, promise date |
| Patience | The number of periods after the due period that a customer waits before the rest of the order is lost. | grace period, tolerance |
| Shipment | Units of a product sent from a warehouse to a customer for one customer order. A shipment reaches its customer in the period it is shipped; there is no time in transit to a customer. | delivery, dispatch, fulfilment |
| Lost sale | The part of a customer order that is never shipped, because the patience ran out or the run ended in or after its due period. | cancellation, backlog, stockout |

## Deciding

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Agent | Whoever chooses the decisions of a run: a program or a person that plays over HTTP, or an optimizer of the benchmark. It gets the description and the observations, and may check decisions of the current period. | player, policy, controller, user |
| Harness | A study program that starts a run, gives an agent its description and observations, and submits its decisions. | runner, driver, wrapper |
| Decision | One instruction from the agent: ship, cancel, transfer, repair, produce or buy. | action, command, move |
| Submission | The decisions of one period, sent by the harness in one request with the number of the period. | batch, action list, turn |
| Check | A request that tells the outcome each decision of a submission would have now, without changing the run. | dry run, preview |
| Outcome | What became of one decision of a submission: accepted with the identifier of what it created, or rejected with a reason and the numbers behind it. | response, feedback, verdict |
| Event | Something that happened in a run, reported with its step and the identifier of the object it concerns, such as a delivery, a breakdown or a penalty. | log entry, message, notification |
| State | Everything the simulator knows about a run after a step, including what the agent may not see. | status, snapshot |
| Observation | What the agent sees in one period before deciding. | view, prompt |
| Description | What the agent receives once at the start of a run: the manifest and the scenario, and whether the manifest is linear. It leaves out the hidden parameter groups, the written disruptions and the name and description of the scenario. | world view, briefing |
| Notice | The number of periods before its start from which a disruption is visible. | warning, announcement lead |
| Forecast | An estimate of the demand of a coming period given to the agent, with a noise set in the scenario. | prediction, outlook, projection |
| Disruption | An event that changes part of the factory or its partners for some periods, written in the scenario or drawn from the seed. | incident, perturbation |
| Written disruption | A disruption written in the scenario with its kind, target, start and duration. | scripted disruption, fixed disruption |
| Random disruption | A disruption drawn from the seed by a named rule of the scenario, either with a chance per period and target or at a start written in the rule. Each disruption hits one target. | stochastic event, random event |
| Cascade | A raise of the chance of one rule of random disruptions, by a factor for some periods, after a disruption of another rule starts. A raised rule raises no further rule. | chain reaction, knock-on effect, contagion |
| Target | The objects a disruption acts on: a list of identifiers, all objects of one kind, or a group. | scope, subject |

## Money and results

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Cash | The money the factory holds. It may be below zero and then pays interest. | balance, budget, funds |
| Credit limit | The amount L such that cash below -L pays the higher overdraft rate of interest. A purchase may not take cash below -L once open supplier orders are counted. | budget, spending limit |
| Interaction | A check of decisions, or a refused submission, kept apart from the run in the record. | probe, attempt, request log |
| Reference | The profit the reference optimizer reaches in a world when it plays through the simulator; the number agents are compared with. | optimum, upper bound |
| Receivable | Money a customer owes for a shipment and has not paid yet. | invoice, debt |
| Salvage value | The money an item in stock is worth at the end of a run. | residual value, scrap value |
| Terminal value | The money an optimizer with a window counts for stock at the end of its window, before the end of the run. | end value, closing value |
| Profit | The one number that scores a run: revenue, paid or not, minus costs and penalties, plus the salvage value of stock at the end. | score, reward, objective |
| Result | What the record holds about a finished run as a whole: the seed, the number of periods, profit and its terms, cash at the start and at the end, receivables and the measures of the whole run. | summary, totals |
| Measure | A number recorded about a run besides profit, such as the share of units shipped on time. | metric, KPI, statistic |
| Record | Everything the simulator stores about a run: what it did in every period, the world, readable once the run ends, and the result. | log, telemetry, trace, output |
| Ledger | The list of every movement of cash in a run. | journal, account, cash book |
| Revenue | The price times the units of a shipment, earned when it is shipped. | sales, income |
| Penalty | Money a customer order costs when it is late (late penalty, per unit and period) or lost (lost-sale penalty, per unit). | fine, charge |
| Interest | Money earned on cash above 0, or paid on cash below 0, at the close of every period. | financing cost |
| Fill rate | The units shipped over the units ordered, in the whole run or up to a period. | service level |
| Value of the relaxed program | The value of the program of period 1 with every yes-or-no choice allowed to take any value from 0 to 1. It is no bound on the profit of a run. | upper bound, ceiling |
| Normalized score | The profit of a run as a share of the way from the profit of no decisions to the reference in the same world. A world in which the reference makes no more profit than no decisions has none; it is unscorable. | relative score, regret |

## Service and study

| Term | Meaning | Also called elsewhere |
| --- | --- | --- |
| Fork | A new run that repeats a finished run up to a chosen period with the same submissions and continues from there with other decisions. | branch, copy |
| Export | The one file of a finished run that holds its record, its manifest, its scenario and the facts of the run. | dump, backup, archive |
| Restart | A new start of the simulator; an unfinished run then continues from its record. | reload, recovery |
| Example manifest | The one manifest, of an electronics factory with economies of scale, that comes with the simulator. | sample factory, default manifest |
| Scenario library | The scenarios that come with the simulator for the example manifest, each exercising one mechanism, and a few combining several. | test suite, scenario set |
| Steady market | The scenario of the library without disruptions or demand shapes. Every other scenario names a measure that differs from it in an expected direction. | baseline scenario, control, base case |
| Benchmark | The part of the package that plays runs over HTTP: the client and the optimizers. | study package, test bench |
| Optimizer | An agent that solves a program of profit over coming periods from what it knows and submits the decisions of the current period. | planner, LP model |
| Reference optimizer | The optimizer that is given the whole world of a run, plans to the end of the run with a linear or mixed-integer program and plays its decisions through the simulator; the instrument of scoring. | oracle, solver |
| Exact control | The reference optimizer with every yes-or-no choice whole in every period of its program, for small worlds only. It measures the policy gap of the reference. | exact reference, oracle, optimum |
| Policy gap | The profit of the exact control less the profit of the reference in the same world. | optimality gap, regret |
| Credit choice | The yes-or-no choice of a program in a period with a buy: the period buys within the credit limit, or places no buy. The credit check refuses only a buy, so the decisions that pass it form no convex set, and every manifest needs the choice. | credit binary, solvency flag |
| Limited optimizer | An optimizer that knows only what an agent knows and solves its program again every period over a window: the full-horizon, rolling, buffered rolling, aligned and myopic optimizers. | receding-horizon planner |
| Full-horizon optimizer | The limited optimizer whose window runs to the horizon of the run. | |
| Rolling optimizer | The limited optimizer whose window is the longest chain of lead times from a buy to a sale plus 2 periods, with a terminal value of stock at the terminal value factor 1.01; it plans again every period. | |
| Buffered rolling optimizer | The rolling optimizer with the terminal value factor 1.2 in place of 1.01, so it ends each window with more stock. | safety-stock optimizer |
| Aligned optimizer | The limited optimizer over the window of the rolling optimizer whose demand is only the open customer orders and forecasts it sees. | |
| Informed optimizer | The rolling optimizer, at the terminal value factor 1.01 or 1.2, that also knows the range of every hidden parameter group but the duration of disruptions, as the description of a twin run with nothing hidden shows it. It never sees a value drawn for a period. A diagnostic, not a limited optimizer. | oracle |
| Disclosure effect | In a scenario that hides a parameter group other than the duration of disruptions, the mean over seeds of the normalized score of the informed optimizer at the terminal value factor 1.2 in a world less that of the buffered rolling optimizer in the same world, with its standard error and the lower and upper bound of its 95 percent interval, the Student interval with the correction for skew of Hall (1992). It is the response of this policy to ranges disclosed before the run, a diagnostic, and it can be negative. | value of learning, value of information |
| Information treatment | One key of a scenario that sets what the agent is told and changes no draw: its forecasts, its hidden groups or the notice of its disruptions. | information level |
| Information control | A scenario without one information treatment of a scenario of the library, the same in every other key, played on the same manifest and seeds. | baseline |
| Effect of a treatment | The mean over seeds of the normalized score of the buffered rolling optimizer in a scenario less its normalized score in the information control of the same seed, with its standard error and the lower and upper bound of its 95 percent interval, the Student interval with the correction for skew of Hall (1992). | value of information |
| Compound scenario | A scenario of the library that differs from the steady market in more than one key, such as `forecasts` or `hidden-groups`. Its difference against the steady market is no effect of a treatment. | mixed scenario |
| Myopic optimizer | The limited optimizer whose window is the current period only, with a terminal value of stock and of orders on the way. | greedy optimizer |
| No decisions | The agent that submits an empty list of decisions every period. Its profit is the floor of the normalized score. | do nothing, null agent |
| Window | The coming periods an optimizer plans over: to the horizon, the longest chain of lead times from a buy to a sale plus 2 periods, or the current period only. | lookahead |
| Order book | The open customer orders of a run in a period. | backlog |
| Expected use | The quantity of an item an optimizer expects to use in the periods after its window, as many as the longest chain of lead times and none after the end of the run, from the mean base demand times the demand shapes and visible demand shocks of each period. It bounds the terminal value. | forecast use |
| Replacement cost | What one unit of an item costs to get: the lowest catalogue price of a material, or for a made item the cost of its inputs and of its line over its yield. | unit cost |
| Integer solve | One solve of a mixed-integer program, with the limit it stopped at, if any, the value of its solution, the bound of its program and its gap. | MILP call |
| Gap of a solve | The bound of the program of an integer solve less the value of its solution, in money, at least 0: the most by which its solution may be below the best solution of that program. | MIP gap, relative gap |
| Gap limit | The gap at which an integer solve stops: 0.01 in the unit of money of its program, whatever part of the profit no decision changes. | tolerance |
| Dropped decision | A decision of a plan that the last check rejected and the optimizer did not submit. | skipped decision |
| Fitted decision | A decision of a plan whose quantity the fit changed after a check rejected it. | adjusted decision |
| Frozen run | A run whose decisions and the hashes of its responses and rows are stored, to replay on later versions. | reference run, golden run |
| Stress test | The test, started by hand, that plays no decisions and the benchmark agents across the library scenarios over many seeds, checks every run and reports scores and calibration verdicts. | load test, benchmark run |
| Calibration | The measurement that tells, per scenario of the library, whether it is scorable, hard enough and moves its named measure in its expected direction. Hard enough is decided for a scenario whose reading holds no foresight. | tuning |
| Best limited score | The highest normalized score of the five limited optimizers in one world. The decision value averages it over seeds. | envelope |
| Calibration score | In one world, 1 less the gap of the buffered rolling optimizer, the profit of the reference less its profit, over the denominator of the steady market in the same seed. A scenario is hard enough when it lowers the calibration score by at least 0.03 against the steady market. | rescaled score |
| Denominator | The profit of the reference less that of no decisions in one world; the normalized score divides by it. | range, spread |
| Decision value | What the decisions of a scenario can still change: the absolute outcomes of its worlds beside its normalized scores, and its reading, which names what a policy can still do and the loss no policy avoids. | difficulty, severity |
| Development seed | A seed below 1000. Every run of the stress test without `--stress-evaluation` plays development seeds. | training seed, tuning seed |
| Evaluation seed | One of the seeds 1000 to 1019, played only by the confirmatory evaluation. | test seed, holdout seed |
| Confirmatory evaluation | The one run of the stress test with `--stress-evaluation`: every library scenario and its built information controls on the evaluation seeds, 520 worlds, under the definitions frozen in `tests/stress/protocol.py`. | validation run, final calibration |
| Report | The document with tables and a chart that the stress test writes about its runs. | dashboard, summary, output |
| Template | A manifest or a scenario that shows every key once, with placeholder numbers. | skeleton, sample |
