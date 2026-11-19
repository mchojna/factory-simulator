# Writing a manifest

A manifest is one JSON document that describes the factory: its items, partners,
lines, warehouses, groups and cash. Every key is listed in
[Manifest fields](../reference/manifest-fields.md).

`POST /api/v1/manifests` takes a manifest and answers:

- 201 and the stored manifest when it is new;
- 200 and the stored manifest when a manifest with the same content is already stored;
- 422 and the place of the first problem when the manifest breaks a rule.

## Smallest example

This manifest buys one material, makes one component and one product on one line,
stores everything in one warehouse and sells the product to one customer.

```json
{
  "materials": {
    "chip": {"space": 0.01, "storage_cost": 0.01, "salvage_value": 1}
  },
  "components": {
    "board": {
      "space": 0.05,
      "storage_cost": 0.05,
      "salvage_value": 4,
      "recipes": {"standard": {"chip": 4}}
    }
  },
  "products": {
    "monitor": {
      "space": 1,
      "storage_cost": 0.2,
      "salvage_value": 5,
      "recipes": {"standard": {"board": 1}}
    }
  },
  "suppliers": {
    "chip-maker": {
      "catalogue": {
        "chip": {
          "price": 2,
          "lead_time": 2,
          "max_quantity": 1000,
          "punctuality": 0.9,
          "delay": 1,
          "completeness": 1,
          "acceptance": 1
        }
      }
    }
  },
  "customers": {
    "distributor": {
      "products": {
        "monitor": {
          "price": 60,
          "transport_cost": 1,
          "demand": 10,
          "lead_time": 1,
          "patience": 2,
          "late_penalty": 2,
          "lost_sale_penalty": 10
        }
      }
    }
  },
  "lines": {
    "assembly": {
      "capacity": 40,
      "wear_per_period": 0.01,
      "wear_per_hour": 0.001,
      "breakdown_chance": 0.02,
      "breakdown_loss": 0.2,
      "repair_cost": 100,
      "repair_time": 4,
      "repair_limit": 0.5,
      "items": {
        "board": {"time": 0.5, "cost": 1, "yield": 0.95},
        "monitor": {"time": 1, "cost": 3, "yield": 0.98}
      }
    }
  },
  "warehouses": {
    "main": {"capacity": 500}
  },
  "cash": {
    "credit_limit": 1000,
    "credit_interest": 0.0005,
    "debit_interest": 0.004,
    "overdraft_interest": 0.02
  }
}
```

- The seven maps `materials`, `components`, `products`, `suppliers`, `customers`,
  `lines` and `warehouses`, and the object `cash`, are required. `routes` and `groups`
  are optional.
- Every key written here is required. Every other key has a built-in default or is
  optional.
- Every material is in a catalogue, every component and product is made by a line,
  and every product is bought by a customer.
- A salvage value is at most what the item costs: 1 for `chip` against its price of 2;
  4 for `board` against 4 x 1 + 1 = 5, its input at its salvage value plus the cost of
  making it.

Save it as `manifest.json` and send it to a running server:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/manifests \
  -H "Content-Type: application/json" --data @manifest.json
```

The answer holds `id`, the identifier of the manifest; `content`, the manifest as it
was sent; and `linear`, true for this manifest. The identifier is computed from the
content, so the same content always has the same identifier. A scenario is then written
for it: see [Writing a scenario](writing-a-scenario.md).

## Objects by identifier

- Every object is written once, as a key of its map: the material `chip` is
  `materials.chip`.
- An identifier is lower case letters, digits and single hyphens. It starts with a
  letter and has at most 40 characters: `chip-maker` is an identifier, `Chip`,
  `2nd-line` and `chip--maker` are not.
- Materials, components and products share one set of identifiers: no material and
  product have the same identifier. Suppliers, customers, lines, warehouses and groups
  each have their own set.
- An object names another by its identifier: a catalogue by materials, a customer by
  products, a line by the components and products it makes and by its warehouse, a
  recipe by its inputs, a route by two warehouses. An identifier that names nothing,
  or an object of the wrong kind, is refused.
- A key the format does not have is refused, and so is a key written twice in one
  object.

## Fixed values and ranges

### Numbers

- A number is a JSON number or JSON text of the same form: `0.01` and `"0.01"` are the
  same. The form is plain: no `+`, no exponent such as `1e-2`, no leading zero such as
  `010`, no `NaN`.
- Each number has the decimal places of its kind:

| Kind | Places | Examples |
| --- | --- | --- |
| quantity, space, hours | 3 | `demand`, `space`, `capacity` of a line |
| money | 4 | `price`, `storage_cost`, `credit_limit` |
| share, chance, rate, factor | 4 | `yield`, `breakdown_chance`, `debit_interest`, `storage_factor` |
| periods | whole number | `lead_time`, `delay`, `patience` |

- A number with more places than its kind is refused. A number with fewer places is
  padded with zeros: `0.01` as a space is 0.010.
- Each number has its bounds, such as at least 0, above 0, or from 0 to 1. The field
  reference gives the bounds of every key.

### Ranges

A numeric parameter is a fixed number or a range. A range has `min`, `max` and a
`distribution`; the simulator draws its value from the seed of the run. These are the
terms of `monitor` for `distributor`, with each kind of range:

```json
{
  "price": 60,
  "transport_cost": {"min": 0.8, "max": 1.2},
  "demand": {"min": 4, "max": 30, "distribution": "lognormal", "median": 10, "spread": 0.4},
  "lead_time": {"min": 1, "max": 2},
  "patience": 2,
  "late_penalty": {"min": 1, "max": 3, "distribution": "triangular", "mode": 2},
  "lost_sale_penalty": {"min": 8, "max": 12, "distribution": "normal", "mean": 10, "sd": 1}
}
```

- `distribution` is `uniform` when left out. `triangular` needs `mode`, `normal` needs
  `mean` and `sd`, `lognormal` needs `median` and `spread`. A key of another
  distribution is refused.
- `min` is at most `max`. A triangular, normal or lognormal range needs `min` below
  `max`, and a lognormal range needs `min` above 0.
- A range of periods, such as `lead_time` above, is uniform only.
- Some parameters are fixed numbers only: `space`, recipes, `common_share`,
  `demand_persistence`, the `from` of a discount, every key of a warehouse and of
  `cash`.
- A rule that compares a range with another number uses the bound of the range that is
  worst for the rule. A range of `salvage_value` from 0.5 to 2 is refused against a
  price of 1.8, because 2 is above 1.8.
- Each parameter is drawn once per run, once per period or once per event. The field
  reference gives the moment of each, and
  [Randomness and fairness](../rules/randomness-and-fairness.md) gives how a draw works.

The range of a catalogue `price` takes one more key, `drawn`. `run`, the default, draws
the price once per run. `period` draws a new price for every period:

```json
{"price": {"min": 1.8, "max": 2.2, "drawn": "period"}}
```

`drawn` on any other range is refused. See [Suppliers](../rules/suppliers.md#prices).

## Descriptive fields

`name`, `description` and `unit` of an object, and `name`, `description` and
`period_name` of the manifest, are text. They help a person read the manifest. The
agent sees them in the description of a run, and they never change a run.

```json
{
  "name": "Monitor factory",
  "description": "A factory that makes monitors from boards.",
  "period_name": "week"
}
```

## Errors

A manifest that breaks a rule is answered 422 with the place and the problem:

```json
{"detail": "materials.chip.salvage_value: is above its lowest price"}
```

- The place is a path of keys joined by dots. A position in a list counts from 0:
  `suppliers.chip-maker.catalogue.chip.discounts.1.from` is the `from` of the second
  discount.
- Only the first problem is answered. The JSON is read first, then each key on its own,
  then the rules that join two or more keys or objects.
- A problem of a value given by a group, such as a number below its bound, names the
  key in the group. A rule that joins values names the key in the member.

| Problem | Answer |
| --- | --- |
| A required key is missing. | `lines.assembly.capacity: Field required` |
| A key the format does not have. | `materials.chip.color: Extra inputs are not permitted` |
| A key written twice. | `materials.chip.space: duplicate key` |
| A number in another form, such as `"1e-2"`. | `materials.chip.space: is not a plain decimal number` |
| A number with too many places. | `materials.chip.space: has more than 3 places` |
| A number below its bound. | `materials.chip.storage_cost: Input should be greater than or equal to 0` |
| An identifier that breaks the rule. | `materials.Chip: String should match pattern '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'` |
| A range with `min` above `max`. | `materials.chip.storage_cost: min is above max` |
| A key of another distribution in a range. | `materials.chip.storage_cost.median: Extra inputs are not permitted` |
| A range of periods that is not uniform. | `suppliers.chip-maker.catalogue.chip.lead_time: a range of periods is uniform only` |
| A value of a group below its bound. | `groups.asia.defaults.catalogue.punctuality: Input should be less than or equal to 1` |
| Discounts whose `from` does not rise. | `suppliers.chip-maker.catalogue.chip.discounts.1.from: does not rise` |
| A salvage value above the price. | `materials.chip.salvage_value: is above its lowest price` |
| Wear that could take more than the condition left. | `lines.assembly.wear_per_hour: wears more than the condition left` |
| Overtime hours without their cost. | `lines.assembly.overtime_cost: is required` |
| A manifest that sells no product. | `products: is empty` |
| A number of more than 50 digits, its decimal places counted. | `materials.chip.space: has more than 50 digits` |

The bounds and rules of every key are in
[Manifest fields](../reference/manifest-fields.md).
