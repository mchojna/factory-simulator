# Pisanie manifestu

Manifest to jeden dokument JSON, który opisuje fabrykę: jej pozycje, partnerów, linie,
magazyny, grupy i gotówkę. Każdy klucz opisuje strona
[Pola manifestu](../reference/manifest-fields.md).

`POST /api/v1/manifests` przyjmuje manifest i odpowiada:

- 201 i zapisanym manifestem, gdy manifest jest nowy;
- 200 i zapisanym manifestem, gdy manifest o tej samej treści jest już zapisany;
- 422 i miejscem pierwszego problemu, gdy manifest łamie regułę.

## Najmniejszy przykład

Ten manifest kupuje jeden materiał, wytwarza jeden komponent i jeden produkt na jednej
linii, przechowuje wszystko w jednym magazynie i sprzedaje produkt jednemu klientowi.

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

- Siedem map `materials`, `components`, `products`, `suppliers`, `customers`, `lines`
  i `warehouses` oraz obiekt `cash` są wymagane. `routes` i `groups` są opcjonalne.
- Każdy klucz zapisany tutaj jest wymagany. Każdy inny klucz ma wbudowaną wartość
  domyślną albo jest opcjonalny.
- Każdy materiał jest w jakimś katalogu. Każdy komponent i produkt wytwarza jakaś
  linia. Każdy produkt kupuje jakiś klient.
- Wartość odzysku jest co najwyżej tym, ile pozycja kosztuje: 1 dla `chip` przy jego
  cenie 2; 4 dla `board` przy 4 x 1 + 1 = 5, czyli jego pozycjach wejściowych po ich
  wartości odzysku plus koszcie wytworzenia.

Zapisz go jako `manifest.json` i wyślij do działającego serwera:

```sh
curl -X POST http://127.0.0.1:8000/api/v1/manifests \
  -H "Content-Type: application/json" --data @manifest.json
```

Odpowiedź zawiera `id`, identyfikator manifestu; `content`, manifest taki, jaki został
wysłany; oraz `linear`, dla tego manifestu true. Identyfikator jest liczony z treści,
więc ta sama treść ma zawsze ten sam identyfikator. Potem pisze się do niego
scenariusz: zobacz [Pisanie scenariusza](writing-a-scenario.md).

## Obiekty według identyfikatora

- Każdy obiekt jest zapisany raz, jako klucz swojej mapy: materiał `chip` to
  `materials.chip`.
- Identyfikator składa się z małych liter, cyfr i pojedynczych łączników. Zaczyna się
  od litery i ma najwyżej 40 znaków: `chip-maker` jest identyfikatorem, a `Chip`,
  `2nd-line` i `chip--maker` nie są.
- Materiały, komponenty i produkty mają jeden wspólny zbiór identyfikatorów: materiał
  i produkt nie mogą mieć tego samego identyfikatora. Dostawcy, klienci, linie,
  magazyny i grupy mają każdy własny zbiór.
- Obiekt wskazuje inny obiekt jego identyfikatorem: katalog wskazuje materiały, klient
  produkty, linia komponenty i produkty, które wytwarza, oraz swój magazyn, receptura
  swoje pozycje wejściowe, a trasa dwa magazyny. Identyfikator, który nic nie wskazuje
  albo wskazuje obiekt złego rodzaju, jest odrzucany.
- Klucz, którego format nie zna, jest odrzucany. Odrzucany jest też klucz zapisany
  dwa razy w jednym obiekcie.

## Wartości stałe i zakresy

### Liczby

- Liczba to liczba JSON albo tekst JSON tej samej postaci: `0.01` i `"0.01"` znaczą to
  samo. Postać jest prosta: bez `+`, bez wykładnika takiego jak `1e-2`, bez zera na
  początku takiego jak `010`, bez `NaN`.
- Każda liczba ma liczbę miejsc po przecinku swojego rodzaju:

| Rodzaj | Miejsca | Przykłady |
| --- | --- | --- |
| ilość, miejsce, godziny | 3 | `demand`, `space`, `capacity` linii |
| pieniądze | 4 | `price`, `storage_cost`, `credit_limit` |
| część, szansa, stopa, czynnik | 4 | `yield`, `breakdown_chance`, `debit_interest`, `storage_factor` |
| okresy | liczba całkowita | `lead_time`, `delay`, `patience` |

- Liczba z większą liczbą miejsc niż jej rodzaj jest odrzucana. Liczba z mniejszą
  liczbą miejsc jest uzupełniana zerami: `0.01` jako miejsce to 0.010.
- Każda liczba ma swoje granice, na przykład co najmniej 0, powyżej 0 albo od 0 do 1.
  Dokumentacja pól podaje granice każdego klucza.

### Zakresy

Parametr liczbowy to stała liczba albo zakres. Zakres ma `min`, `max` i `distribution`;
symulator losuje jego wartość z ziarna przebiegu. Oto warunki `monitor` dla
`distributor`, z każdym rodzajem zakresu:

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

- Bez `distribution` rozkład to `uniform`. `triangular` wymaga `mode`, `normal` wymaga
  `mean` i `sd`, `lognormal` wymaga `median` i `spread`. Klucz innego rozkładu jest
  odrzucany.
- `min` jest co najwyżej `max`. Zakres trójkątny, normalny lub logarytmiczno-normalny
  wymaga `min` poniżej `max`. Zakres logarytmiczno-normalny wymaga `min` powyżej 0.
- Zakres okresów, taki jak `lead_time` powyżej, może być tylko jednostajny.
- Niektóre parametry mogą być tylko stałymi liczbami: `space`, receptury,
  `common_share`, `demand_persistence`, `from` rabatu, każdy klucz magazynu i każdy
  klucz `cash`.
- Reguła, która porównuje zakres z inną liczbą, bierze tę granicę zakresu, która jest
  najgorsza dla reguły. Zakres `salvage_value` od 0.5 do 2 jest odrzucany przy cenie
  1.8, bo 2 jest powyżej 1.8.
- Każdy parametr jest losowany raz na przebieg, raz na okres albo raz na zdarzenie.
  Dokumentacja pól podaje moment losowania każdego z nich, a
  [Losowość i uczciwość](../rules/randomness-and-fairness.md) opisuje, jak działa
  losowanie.

Zakres `price` w katalogu ma jeden klucz więcej: `drawn`. `run`, wartość domyślna,
losuje cenę raz na przebieg. `period` losuje nową cenę w każdym okresie:

```json
{"price": {"min": 1.8, "max": 2.2, "drawn": "period"}}
```

`drawn` w każdym innym zakresie jest odrzucany. Zobacz
[Dostawcy](../rules/suppliers.md#ceny).

## Pola opisowe

`name`, `description` i `unit` obiektu oraz `name`, `description` i `period_name`
manifestu to tekst. Pomagają człowiekowi czytać manifest. Agent widzi je w opisie
przebiegu. Nigdy nie zmieniają przebiegu.

```json
{
  "name": "Monitor factory",
  "description": "A factory that makes monitors from boards.",
  "period_name": "week"
}
```

## Błędy

Manifest, który łamie regułę, dostaje odpowiedź 422 z miejscem i problemem:

```json
{"detail": "materials.chip.salvage_value: is above its lowest price"}
```

- Miejsce to ścieżka kluczy połączonych kropkami. Pozycja na liście jest liczona od 0:
  `suppliers.chip-maker.catalogue.chip.discounts.1.from` to `from` drugiego rabatu.
- Odpowiedź podaje tylko pierwszy problem. Najpierw czytany jest JSON, potem każdy
  klucz osobno, a potem reguły, które łączą dwa lub więcej kluczy lub obiektów.
- Problem wartości danej przez grupę, na przykład liczba poniżej swojej granicy,
  wskazuje klucz w grupie. Reguła, która łączy wartości, wskazuje klucz w członku.

| Problem | Odpowiedź |
| --- | --- |
| Brakuje wymaganego klucza. | `lines.assembly.capacity: Field required` |
| Klucz, którego format nie zna. | `materials.chip.color: Extra inputs are not permitted` |
| Klucz zapisany dwa razy. | `materials.chip.space: duplicate key` |
| Liczba w innej postaci, taka jak `"1e-2"`. | `materials.chip.space: is not a plain decimal number` |
| Liczba ze zbyt wieloma miejscami. | `materials.chip.space: has more than 3 places` |
| Liczba poniżej swojej granicy. | `materials.chip.storage_cost: Input should be greater than or equal to 0` |
| Identyfikator, który łamie regułę. | `materials.Chip: String should match pattern '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'` |
| Zakres z `min` powyżej `max`. | `materials.chip.storage_cost: min is above max` |
| Klucz innego rozkładu w zakresie. | `materials.chip.storage_cost.median: Extra inputs are not permitted` |
| Zakres okresów, który nie jest jednostajny. | `suppliers.chip-maker.catalogue.chip.lead_time: a range of periods is uniform only` |
| Wartość grupy poniżej swojej granicy. | `groups.asia.defaults.catalogue.punctuality: Input should be less than or equal to 1` |
| Rabaty, których `from` nie rośnie. | `suppliers.chip-maker.catalogue.chip.discounts.1.from: does not rise` |
| Wartość odzysku powyżej ceny. | `materials.chip.salvage_value: is above its lowest price` |
| Zużycie, które mogłoby zabrać więcej niż pozostały stan. | `lines.assembly.wear_per_hour: wears more than the condition left` |
| Nadgodziny bez ich kosztu. | `lines.assembly.overtime_cost: is required` |
| Manifest, który nie sprzedaje żadnego produktu. | `products: is empty` |
| Liczba z więcej niż 50 cyframi, licząc miejsca po przecinku. | `materials.chip.space: has more than 50 digits` |

Granice i reguły każdego klucza opisuje strona
[Pola manifestu](../reference/manifest-fields.md).
