# HTTP interface

The simulator is a service over HTTP. A harness creates or picks a manifest and a
scenario, starts a run with a seed, reads the observation of each period and submits
decisions. Every route lives under `/api/v1`, reads JSON and answers JSON, apart from
the export, which answers a ZIP file.

## Every route

`{manifest_id}`, `{scenario_id}` and `{run_id}` stand for identifiers. A dash means the
route takes no body or answers no error of its own.

| Route | Body | Answer | Errors |
| --- | --- | --- | --- |
| `POST /api/v1/manifests` | A manifest. | 201 and the new manifest; 200 and the stored one when the same manifest is already stored. | 422 |
| `POST /api/v1/manifests/generated` | `{"counts": {...}, "seed": n, "economy": "unrestricted"}` | 201 and the manifest generated from the counts, the seed and the economy; 200 when it is already stored. | 422 |
| `GET /api/v1/manifests` | - | 200 and `{"manifests": [...]}`: the `id`, `name` and `description` of each stored manifest, in the order of the `id`. | - |
| `GET /api/v1/manifests/{manifest_id}` | - | 200 and `{"id", "content", "linear"}`. | 404 |
| `POST /api/v1/manifests/{manifest_id}/scenarios` | A scenario. | 201 and the new scenario; 200 and the stored one when the same scenario is already stored. | 404, 422 |
| `GET /api/v1/manifests/{manifest_id}/scenarios` | - | 200 and `{"scenarios": [...]}`: the `id`, `name` and `description` of each scenario of the manifest, in the order of the `id`. | 404 |
| `GET /api/v1/scenarios/{scenario_id}` | - | 200 and `{"id", "content"}`. | 404 |
| `POST /api/v1/runs` | `{"scenario_id", "seed"}` | 201 and the run, in period 1. | 404, 422 |
| `GET /api/v1/runs/{run_id}` | - | 200 and the run. | 404, 409 |
| `GET /api/v1/runs/{run_id}/observation` | - | 200 and the observation of the current period. | 404, 409 |
| `POST /api/v1/runs/{run_id}/decisions` | `{"period", "decisions"}` | 200 and the observation of the next period, or the run with `finished: true` after the last period. | 404, 409, 422 |
| `POST /api/v1/runs/{run_id}/checks` | `{"period", "decisions"}` | 200 and `{"outcomes": [...]}`: the outcome each decision would have now. The run does not change. | 404, 409, 422 |
| `POST /api/v1/runs/{run_id}/forks` | `{"period"}` | 201 and the new run, in that period. | 404, 409, 422 |
| `GET /api/v1/runs/{run_id}/periods` | - | 200 and `{"periods": [...]}`: every closed period. | 404, 409 |
| `GET /api/v1/runs/{run_id}/result` | - | 200 and the result of the finished run. | 404, 409 |
| `GET /api/v1/runs/{run_id}/world` | - | 200 and every value drawn from the seed. | 404, 409 |
| `GET /api/v1/runs/{run_id}/export` | - | 200 and the ZIP file `<run id>.zip`. | 404, 409 |

What each route answers during a run and after it is in
[Information](../rules/information.md#who-may-read-what).

## Manifests and scenarios

- The body of `POST /api/v1/manifests` is a manifest as JSON. See
  [Writing a manifest](../guides/writing-a-manifest.md) and the
  [field reference](manifest-fields.md).
- The identifier of a manifest is the SHA-256 of its content, as 64 hexadecimal
  digits. The same content always gives the same identifier.
- `content` of a manifest is the manifest as its author wrote it. Values given by groups
  and built-in defaults are not added. `linear` is true when no catalogue entry names a
  minimum quantity or discounts and no line item names a changeover time or cost.
  `min_quantity`, `changeover_time` or `changeover_cost` written, even as 0, makes
  `linear` false.
- The body of `POST /api/v1/manifests/{manifest_id}/scenarios` is a scenario as JSON. It
  is checked against the manifest. See
  [Writing a scenario](../guides/writing-a-scenario.md).
- The identifier of a scenario is the SHA-256 of its manifest's identifier and its
  content. One scenario stored under two manifests has two identifiers.
- `content` of a scenario holds every key, with its default written where the author
  left it out. Its `name` and `description` are stored with it and are never part of the
  description of a run.
- A manifest or scenario sent twice is stored once. The second answer is 200 with the
  stored one.

## A manifest generated from counts

`POST /api/v1/manifests/generated` writes a manifest from counts of objects and a seed,
then stores it like `POST /api/v1/manifests`:

```json
{
  "counts": {
    "materials": 9,
    "components": 6,
    "products": 3,
    "suppliers": 4,
    "customers": 4,
    "lines": 4
  },
  "seed": 0
}
```

| Key | Allowed values |
| --- | --- |
| `counts.materials` | A whole number from 1 to 200. |
| `counts.components` | A whole number from 1 to 100. |
| `counts.products` | A whole number from 1 to 50. |
| `counts.suppliers` | A whole number from 1 to 50. |
| `counts.customers` | A whole number from 1 to 50. |
| `counts.lines` | A whole number from 1 to 20, and at most `components` plus `products`. |
| `seed` | A whole number from 0 to 2 to the power 128, minus 1. |
| `economy` | `unrestricted`, the default, or `matched`. |

- The six counts are required. Each is a whole number, as a JSON number or as text:
  `9` and `"9"` are the same count.
- The seed decides only the manifest. It is not the seed of any run.
- The same counts and seed give the same manifest, byte for byte, within one version of
  the package. Sent again, they are answered 200 with the stored manifest.
- The manifest passes every check of `POST /api/v1/manifests`. It is linear and has one
  warehouse, `plant`. Its objects are named by kind and number, such as `material-1` and
  `line-3`. Its `name` is `Generated factory`, and its `description` names the counts
  and the seed.
- A count outside its values answers 422 at its key, such as
  `counts.lines: is above components + products`.
- `economy` sets the prices of the customer products: within the prices of the example
  factory, or the lowest cost of the product times a ratio from 1.8124 to 2.4250.
  Another word answers 422 at `economy`. See
  [Larger manifests](../guides/larger-manifests.md#the-economy-of-a-generated-manifest).
- A scenario is written against a generated manifest as against any other.

See [Writing a manifest](../guides/writing-a-manifest.md) for how the generator builds
the factory.

## Runs

- `POST /api/v1/runs` takes `{"scenario_id": ..., "seed": ...}`. The seed is a whole
  number from 0 to 2 to the power 128, minus 1, as a JSON number or as text: `7` and
  `"7"` are the same seed. `7.0`, `-1`, `1.5`, `"1.5"`, 2 to the power 128 and `true`
  are refused at `seed`.
- A run is answered as `{"id", "scenario_id", "description", "period", "finished"}`.
  `description` holds the factory and the scenario as the agent may see them, and
  `linear`. Every range in it carries `cut_mean`, the mean of its distribution cut to
  `min` and `max`, rounded half to even to 6 places: the demand of `smart-monitor` for
  `tier1-distributor`, lognormal with median 35 and spread 0.4 cut to 14 to 70, has the
  `cut_mean` 36.222159. See [Information](../rules/information.md#the-description).
- The run never holds the seed, the world, the state or the result.
- The run starts in period 1. A finished run keeps `period` at the horizon and
  `finished: true`.
- A submission is `{"period": 7, "decisions": [...]}`, with the number of the current
  period. See [Decisions](../rules/decisions.md#the-submission).
- A check takes the same body as a submission and changes nothing but the record of
  interactions. See [Decisions](../rules/decisions.md#checking-without-executing).
- A fork takes `{"period": p}`, with p from 1 to the horizon of the finished run. The
  new run has the same scenario and seed and stands in period p. See
  [Playing a run](../benchmark/playing-a-run.md#forks-for-what-if).
- `GET /api/v1/runs/{run_id}/periods` gives each closed period as `period`, its six
  `steps` in order, each with what the step did, and its `ledger` rows in order, each
  with its `period`, `step`, `kind`, `amount`, `cash_after` and `reference`.
- The result, the world and the export answer once the run is finished. See
  [Measures and the record](measures-and-the-record.md) and
  [Randomness and fairness](../rules/randomness-and-fairness.md).
- Submissions, checks and forks of one run are executed one at a time. Of two
  submissions for one period, one is executed and the other answers 409.
- No route has a time limit. A run waits for its next submission for as long as it
  takes, and a restart of the server continues an unfinished run from its record.

## Errors

Every error answers a JSON object with one key:

```json
{"detail": "decisions.0.quantity: has more than 3 places"}
```

The text is `<key>: <problem>`. The key is the dotted chain of keys to the place of
the problem, with list positions counted from 0, such as
`suppliers.apac-chips.catalogue.microchip.price` or `start.supplier_orders.0.quantity`.
A problem of the body as a whole has the key `body`. Only the first problem is
answered.

| Code | When | Text |
| --- | --- | --- |
| 404 | The manifest does not exist. | `manifest_id: unknown manifest <id>` |
| 404 | The scenario does not exist. | `scenario_id: unknown scenario <id>` |
| 404 | The run does not exist. | `run_id: unknown run <id>` |
| 404 | No route has the path of the request. | `route: not found` |
| 405 | The route of the path takes another method, such as `DELETE /api/v1/manifests`. | `route: method not allowed` |
| 409 | A finished run gets a submission or a check, or its observation is read. | `run: the run is finished` |
| 409 | A run that is not finished is asked for its result, world or export, or is forked. | `run: the run is not finished` |
| 409 | A submission or check names another period than the current one. | `period: is 2, the run is in period 1` |
| 409 | A run to continue after a restart, or to fork, was written by other versions or does not replay to its record. | The difference, such as `runs.package_version: recorded 0.2.0, running 0.3.0`, `world: does not match the record` or `periods.3: replayed period differs from the record` |
| 422 | The body is not UTF-8. | `body: is not UTF-8` |
| 422 | The body is not JSON. | `body: is not JSON` |
| 422 | The body is nested deeper than the reader can read, such as 5000 lists inside each other. | `body: is nested too deeply` |
| 422 | A text or a key is not valid Unicode, such as the escape `"\ud800"`, half of an emoji. | `<key>: is not valid text`, `<key>: holds a key that is not valid text` |
| 422 | An object of the body holds a key twice. | `<key>: duplicate key` |
| 422 | A number is not in a plain decimal form, or is `NaN` or `Infinity`. | `<key>: is not a plain decimal number`, `<key>: is not a finite number` |
| 422 | A number has more than 50 digits, its decimal places counted. | `<key>: has more than 50 digits` |
| 422 | A seed sent as text has more than 39 digits. | `seed: is not from 0 to 2 ** 128 - 1` |
| 422 | A body breaks its form: a missing or unknown key, a wrong type, a number outside its values or with too many places. | `<key>: <problem>`, such as `counts.materials: Input should be greater than or equal to 1` |
| 422 | A manifest or scenario fails a check. | `<key>: <problem>`, such as `horizon: material-1 cannot arrive within it and is not at hand` |
| 422 | A fork names a period outside the horizon. | `period: is not from 1 to the horizon` |
| 500 | A defect of the simulator. The answer never holds the text of the defect; the log of the server holds it. | `server: internal error` |
| 503 | No connection of the database is free within 30 seconds. | `database: no connection was free within 30 s` |

- Every route may answer 503 when the server has many requests at once, such as many
  runs coming back after a restart. A harness may send the request again.
- A submission or check is answered in this order: an unknown run 404; a finished run
  409; a body that is not UTF-8 or not JSON 422; a body that breaks its form 422;
  another period 409.
- A submission or check refused with 409 for another period, or with 422, is kept in
  the record as an interaction, apart from the run. A refused submission leaves the run
  in its period.
- A refused submission is not a rejected decision. A well-formed decision that breaks a
  rule of the factory is rejected with a reason in its outcome, and the period closes.
  See [Decisions](../rules/decisions.md#reasons-of-rejection).
- See [Writing a manifest](../guides/writing-a-manifest.md) for how an error names the
  place of a problem in a manifest.

## Numbers

Every quantity, price, share and amount of money is an exact decimal.

- In a body, every number may be a JSON number or text of the same form: `40.5` and
  `"40.5"` are the same number.
- The form is an optional minus, then digits without a leading zero, then optionally a
  point and at least one digit. `-0.25`, `0`, `12` and `12.5` pass. `+5`, `.5`, `5.`,
  `010`, `1e3`, `1_000`, `NaN` and `Infinity` are refused.
- A number has at most 50 digits, its decimal places counted: a quantity has at most
  47 digits before the point.
- Each kind of number has a fixed count of decimal places:

| Kind | Places | Examples |
| --- | --- | --- |
| quantity, space, hours | 3 | the quantity of a decision, the space of an item, the capacity of a line |
| money | 4 | a price, a cost, a penalty, a salvage value, starting cash |
| share, chance, rate, factor | 4 | a yield, punctuality, an interest rate, the amount of a repair |
| periods | 0 | a period, the horizon, a lead time, a seed |

- A number with more places than its kind is refused, such as
  `decisions.0.amount: has more than 4 places`. A number with fewer places is padded:
  `40`, `40.0` and `40.000` are the same quantity.
- A whole number written with a point is refused: `52.0` as a horizon answers
  `horizon: is not a whole number`.
- Answers write every decimal as a JSON number in plain form: no exponent, no trailing
  zeros, and 0 for a negative zero. `40.000` is written `40`. The seed is a JSON number
  too. The keys of every object are sorted.
- Numbers computed during a run, such as profit, can have more places than the
  numbers they come from; the record keeps up to 12.
- Read answers without binary floating point, which loses digits of decimals and of
  seeds above 2 to the power 53. In Python: `json.loads(text, parse_float=Decimal)`.
- Send decimals as text. In Python, `json.dumps(body, default=str)` writes
  `Decimal("12.5")` as `"12.5"`. A float can be written with an exponent, such as
  `1e-05`, which is refused.

See [Playing a run](../benchmark/playing-a-run.md#exact-decimals) for a harness that
follows these rules.

## The OpenAPI schema

- `GET /api/v1/openapi.json` gives the OpenAPI schema of the interface: every route,
  the schema of every body and of every answer. The schema describes, for every route,
  the error answers it gives, each with the body of [Errors](#errors), `ErrorPublic`.
- The schemas of the bodies are `ManifestCreate`, `ManifestGenerate`, `ScenarioCreate`,
  `RunCreate`, `DecisionsCreate` and `ForkCreate`.
- The schema of a body declares a decimal as a JSON number or as text of the form
  above, and a whole number as a JSON whole number or as its text. The schema of an
  answer declares both as JSON numbers.
- The schema of a manifest leaves optional every key that a group can give its
  member, such as `lead_time` of a catalogue entry. A member that leaves such a key out
  takes it from its groups, and a manifest whose groups give no value is refused with
  422. `content` of `GET /api/v1/manifests/{manifest_id}` has the schema of the body,
  `ManifestCreate`.
- `/api/v1/docs` shows the schema as a page in a browser, where each route can be
  tried.
- A tool that reads OpenAPI can make code in another language that calls the
  interface from this schema.

## The server

- The server is started as in [Quick start](../start/quick-start.md). It reads two
  environment variables:

| Variable | Value |
| --- | --- |
| `FACTORY_SIMULATOR_DATABASE_URL` | Required. The database of the record, such as `duckdb:///data/records/runs.duckdb`. |
| `FACTORY_SIMULATOR_LOAD_EXAMPLES` | `true` by default. When true, the server stores the example manifest and its scenario library when it starts, unless they are stored already. |

- Without `FACTORY_SIMULATOR_DATABASE_URL` the server does not start, with
  `FACTORY_SIMULATOR_DATABASE_URL: Field required`.
- `duckdb:///:memory:` is refused: an in-memory database needs a name, such as
  `duckdb:///:memory:runs`. The server then does not start, with
  `FACTORY_SIMULATOR_DATABASE_URL: an in-memory database needs a name, such as duckdb:///:memory:runs`.
- The server runs in one process, the only process that opens the database file.
- It listens on `127.0.0.1`, port 8000, unless uvicorn is told otherwise. It has no
  login.
- A running run keeps its world and state in memory until its last period is submitted
  or the server stops. A restart frees the memory of a run that a harness left; the next
  request to it rebuilds it.
- The server limits no body, no list of decisions and no number of runs. A refused body
  is kept in `interactions` whole.
