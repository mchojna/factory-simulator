# Larger manifests

Groups, discounts, templates and generated manifests make larger factories.

## Smallest example

A group gives default values to its members, so a number shared by many objects is
written once. Here the group `asia` gives its suppliers a lead time and a punctuality,
and `chip-maker` writes neither:

```json
{
  "groups": {
    "asia": {
      "kind": "region",
      "defaults": {
        "catalogue": {"lead_time": {"min": 2, "max": 4}, "punctuality": 0.85}
      }
    }
  },
  "suppliers": {
    "chip-maker": {
      "groups": ["asia"],
      "catalogue": {
        "chip": {"price": 2, "max_quantity": 1000, "delay": 1, "completeness": 1, "acceptance": 1}
      }
    }
  }
}
```

- A group has a `kind`, a free word such as `region`, and optional `defaults`. A member
  lists its groups under `groups`, at most one of each kind.
- `defaults` has one key per type of parameter: `items`, `catalogue`, `line_items`,
  `customer_products`, `customers` and `lines`. A group gives defaults only under the
  keys its members use.
- A value written in the object wins. Then come the groups in the order the object
  lists them, then the built-in default. A catalogue entry asks the groups of the
  supplier first, then those of the material. A required key with no value from any of
  them is refused at the key of the member.
- A range given by a group is drawn separately for every member.
- A group has members of one type, at least one member, and an identifier that is not
  `materials`, `components`, `products`, `all`, `written` or `default`.

See [Groups](../rules/groups.md) for every rule of groups.

## Linear and economies-of-scale manifests

A manifest is linear when no catalogue entry names a minimum quantity or discounts and
no line item names a changeover time or cost. Its program is linear in every rule but
the credit check of a buy, which adds one yes-or-no choice in every period with a buy.
A manifest with a minimum quantity or discounts, or a changeover time or cost, is an
economies-of-scale manifest, and its program has more yes-or-no choices.
The answer of `POST /api/v1/manifests` and `GET /api/v1/manifests/{id}` gives `linear`:
`true` or `false`.

This catalogue entry of `chip` makes the smallest manifest an economies-of-scale
manifest:

```json
{
  "price": 2,
  "lead_time": 2,
  "max_quantity": 1000,
  "punctuality": 0.9,
  "delay": 1,
  "completeness": 1,
  "acceptance": 1,
  "min_quantity": 200,
  "discounts": [
    {"from": 500, "price": 1.9},
    {"from": 800, "price": 1.8}
  ]
}
```

- A catalogue entry with `min_quantity`, even 0, or with at least one discount makes
  `linear` false.
- A line item with `changeover_time` or `changeover_cost`, even 0, such as
  `"changeover_time": 2, "changeover_cost": 300`, does the same.
- The program of an optimizer has yes-or-no choices for whether a period buys, a
  minimum quantity above 0, a discount, and a changeover time or cost above 0. With
  every such key at 0 its only yes-or-no choices are whether each period buys.
- The example factory is an economies-of-scale manifest:
  `Electronics factory with economies of scale` has minimum quantities, discounts and
  changeovers. See [Example factory](../library/example-factory.md).

## The templates

The package holds two templates: a manifest that uses every key of a manifest at least
once, and a scenario for it that uses every key of a scenario. They use every kind of
range, of disruption and of demand shape. Their numbers are placeholders.

- In a copy of the repository they are
  `src/factory_simulator/api/examples/templates/manifest.json` and `scenario.json` in
  the same folder.
- In an installed package they are files of `factory_simulator`:

```python
from importlib.resources import files

templates = files("factory_simulator") / "api" / "examples" / "templates"
manifest = (templates / "manifest.json").read_text()
scenario = (templates / "scenario.json").read_text()
```

- No route of the HTTP interface serves them, and the server does not load them when it
  starts. `POST /api/v1/manifests` accepts the template manifest, and the template
  scenario is accepted for it.
- The template manifest is an economies-of-scale manifest.

## A generated manifest

`POST /api/v1/manifests/generated` writes a manifest from counts of objects and a seed,
checks it and stores it, like `POST /api/v1/manifests`:

```json
{
  "counts": {
    "materials": 4,
    "components": 3,
    "products": 2,
    "suppliers": 2,
    "customers": 2,
    "lines": 2
  },
  "seed": 0
}
```

- The counts are whole numbers, as JSON numbers or as text: `materials` 1 to 200,
  `components` 1 to 100, `products`, `suppliers` and `customers` 1 to 50, `lines` 1 to
  20 and at most `components` + `products`.
- The seed is a whole number from 0 to 2 to the power 128, minus 1. It decides only the
  manifest. The seed of a run is a separate number.
- The same counts and seed give the same manifest, byte for byte, on every computer.
- The objects are named by kind and number: `material-1`, `component-2`, `line-1`.
  There is one warehouse, `plant`, which accepts every item.
- Each component has one recipe, `standard`, of 1 to 4 materials; each product one of
  1 to 4 components. Every material has one or two suppliers, every component and
  product one line, and every customer buys at least one product.
- Most numbers are drawn from the smallest to the largest value of the same parameter
  in the example factory. A parameter that the example writes as a range, such
  as `demand` or `yield`, is a range here too.
- Some numbers follow from the others: the capacity of a line, the largest quantity of
  a catalogue entry, storage costs, salvage values, the capacity of `plant` and the
  credit limit. The capacity of a line is the hours that the middle of demand needs,
  divided by 0.85. The three interest rates are those of the example factory.
- A generated manifest is linear. It has no group, no route and no optional key beyond
  those above. Its `name` is `Generated factory`, and its `description` names the
  counts and the seed.

The answer is the stored manifest, with 201 or 200 as for `POST /api/v1/manifests`. A
scenario is written for it like for any manifest.

## The economy of a generated manifest

The key `economy` of the body sets how the price of each customer product is drawn, such
as `"economy": "matched"` beside `counts` and `seed`.

- `unrestricted`, the default: the price is drawn from 108.0000 to 199.5000, the
  prices of the example factory, whatever the product costs. A product made of many
  materials can cost more than any customer pays for it.
- `matched`: the price is the lowest cost of the product times a ratio drawn from
  1.8124 to 2.4250, the lowest and highest ratio of a price to the cost of its product
  in the example factory, rounded to 4 places. Every customer product then earns a
  margin, at every count.
- Both economies read the same draw for a price, so every other number is the same in
  both but the credit limit, which follows the prices. The `description` of a matched
  manifest ends `and matched prices.`, and it is stored under its own identifier.

## The economic profile

`build_economic_profile` of `factory_simulator.engine` reads a generated manifest as
JSON and gives its economics before any run:

```python
from factory_simulator.engine import build_economic_profile, generate_manifest

counts = {
    "materials": 4,
    "components": 4,
    "products": 1,
    "suppliers": 1,
    "customers": 1,
    "lines": 1,
}
profile = build_economic_profile(generate_manifest(counts, 2))
print(profile.economic_class)  # unproductive
```

- The lowest cost of a material is its lowest price over its catalogue entries. The
  lowest cost of a made item is the sum of the lowest costs of its inputs and the cost
  of its line item, at yield 1, with no storage, interest or loss.
- For every customer product it gives the lowest cost of the product, the best margin,
  the price less the transport cost and the lowest cost, the service value, the price
  less the transport cost plus the lost-sale penalty and patience times the late
  penalty, and the middle of demand.
- The useful demand coverage is the share of the middle demand in customer products
  whose service value is above their lowest cost. The margin share is the best margins
  over the prices, each weighted by the middle demand.
- The class is `profitable` when a best margin is above 0, `penalty-driven` when none
  is but a service value is above its lowest cost, and `unproductive` otherwise.
- In the example the product costs at least 213.1738 a unit and a unit shipped on time
  is worth at most 179.6824, so the class is `unproductive` and the coverage 0: no unit
  made from bought inputs pays for itself, even with every penalty avoided.
- Every manifest of the matched economy is `profitable` with a coverage of 1. The
  profile refuses nothing: a manifest of every class passes the checks.

## Errors

A manifest that breaks a rule gets the response 422 with the place of the first
problem, as in [Writing a manifest](writing-a-manifest.md#errors). A body of
`POST /api/v1/manifests/generated` is refused in the same way, at its key:

| Problem | Response |
| --- | --- |
| A count outside its values. | `counts.materials: Input should be greater than or equal to 1` |
| More lines than components and products. | `counts.lines: is above components + products` |
| An economy other than `unrestricted` and `matched`. | `economy: Input should be 'unrestricted' or 'matched'` |
