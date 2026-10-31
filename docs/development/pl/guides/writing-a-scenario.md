# Pisanie scenariusza

Scenariusz to jeden dokument JSON, który opisuje, jak przebieg zmienia się w czasie:
horyzont, stan początkowy, kształty popytu, prognozy, zakłócenia i ukryte grupy
parametrów. Każdy klucz i jego granice opisuje strona
[Pola scenariusza](../reference/scenario-fields.md). Przykłady są napisane dla
najmniejszego manifestu ze strony [Pisanie manifestu](writing-a-manifest.md).

`POST /api/v1/manifests/{id}/scenarios` przyjmuje scenariusz zapisanego manifestu.
Odpowiedź to 201 i zapisany scenariusz, gdy scenariusz jest nowy, 200 i zapisany
scenariusz, gdy manifest już go ma, 404, gdy manifest nie istnieje, oraz 422 z miejscem
pierwszego problemu, gdy scenariusz łamie regułę. Jeden scenariusz działa z wieloma
ziarnami.

## Najmniejszy przykład

```json
{"horizon": 12}
```

- `horizon` to jedyny wymagany klucz: liczba okresów, od 1 do 520.
- Każdy inny klucz ma wartość domyślną: gotówka 0, brak zapasu, każda linia o stanie 1 i
  nieustawiona na żadną pozycję, brak otwartych zamówień, kształtów popytu, prognoz i
  zakłóceń, nic ukrytego.
- Horyzont zostawia czas na zakup: materiał użyty w recepturze musi móc dotrzeć przed
  jego końcem. W najmniejszym manifeście `chip` ma czas realizacji 2, więc horyzont 2
  jest odrzucany.
- `name` i `description` to tekst dla człowieka; agent nigdy go nie widzi.

## Start

`start` to stan fabryki przed okresem 1:

```json
{
  "horizon": 12,
  "start": {
    "cash": 5000,
    "stock": {"main": {"chip": 400, "monitor": 10}},
    "condition": {"assembly": 0.9},
    "set_for": {"assembly": "board"},
    "customer_orders": [
      {"customer": "distributor", "product": "monitor", "quantity": 5, "due": 1}
    ],
    "supplier_orders": [
      {"supplier": "chip-maker", "material": "chip", "quantity": 500, "arrival": 2}
    ]
  }
}
```

- `cash` może być poniżej 0.
- `stock` to ilość każdej pozycji w każdym magazynie; brakująca pozycja zaczyna od 0.
  Magazyn przyjmuje pozycję. Zapas razem z początkowymi zamówieniami u dostawców do tego
  magazynu mieści się w jego pojemności.
- `condition` to stan każdej linii, od 0 do 1; brakująca linia zaczyna od 1.
- `set_for` to pozycja, na którą ustawiona jest każda linia; musi to być pozycja, którą
  linia wytwarza. Brakująca linia jest nieustawiona na żadną pozycję. Przy
  przezbrojeniach pierwsza produkcja linii nieustawionej na żadną pozycję płaci jedno
  przezbrojenie.
- Początkowe zamówienie klienta wskazuje klienta i produkt, który on kupuje, ilość
  powyżej 0 i okres terminu od 1 do horyzontu. Wpłynęło w okresie 0. Ma cierpliwość,
  cenę i kary swojej pary.
- Początkowe zamówienie u dostawcy wskazuje dostawcę, materiał z jego katalogu, ilość
  powyżej 0 i okres przybycia od 1 do horyzontu. Przy kilku magazynach wskazuje też
  `warehouse`, który przyjmuje ten materiał. Zostało złożone w okresie 0 po wylosowanej
  cenie, bez rabatu i nie jako ekspresowe. Gdy cena jest losowana w każdym okresie, jest
  to cena okresu 1. Dociera w całości i zostaje przyjęte w swoim okresie przybycia.
  Żadne zakłócenie na nie nie działa. Można je anulować jak każde otwarte zamówienie.
- Należności, produkcje, plany i przesunięcia są na starcie puste.

## Kształty popytu

Kształt popytu to czynnik w czasie, który mnoży popyt bazowy:

```json
{
  "horizon": 12,
  "demand_shapes": [
    {"kind": "trend", "target": "all", "rate": 0.01},
    {"kind": "season", "target": {"customer": "distributor"}, "factors": [0.9, 1.1], "period_length": 4},
    {"kind": "step", "target": {"product": "monitor"}, "period": 6, "factor": 1.2},
    {"kind": "ramp", "target": {"customer": "distributor", "product": "monitor"}, "first": 2, "last": 8, "from_factor": 1, "to_factor": 1.5},
    {"kind": "s_curve", "target": "all", "middle": 6, "steepness": 0.5, "from_factor": 0.5, "to_factor": 1}
  ]
}
```

| `kind` | Klucze | Granice |
| --- | --- | --- |
| `trend` | `rate` | `rate` powyżej -1. |
| `season` | `factors`, `period_length` | Co najmniej jeden czynnik, każdy co najmniej 0; `period_length` co najmniej 1. |
| `step` | `period`, `factor` | `factor` co najmniej 0. |
| `ramp` | `first`, `last`, `from_factor`, `to_factor` | `last` po `first`; czynniki co najmniej 0. |
| `s_curve` | `middle`, `steepness`, `from_factor`, `to_factor` | `steepness` powyżej 0; czynniki co najmniej 0. |

- `period`, `first`, `last` i `middle` to liczby całkowite. Mogą leżeć poza horyzontem.
  Stopy i czynniki mają 4 miejsca po przecinku.
- `target` to `"all"`; jeden klient, `{"customer": "distributor"}`; jeden produkt,
  `{"product": "monitor"}`; jedna para,
  `{"customer": "distributor", "product": "monitor"}`, którą ma manifest; albo grupa
  klientów lub produktów, zapisana `{"<kind>": "<group>"}`, na przykład
  `{"segment": "new-devices"}`, której rodzaj zgadza się z grupą.
- Popyt pary to jej popyt bazowy razy czynnik każdego kształtu, którego celem jest ta
  para.

Czynnik każdego rodzaju w każdym okresie podaje strona
[Klienci i popyt](../rules/customers-and-demand.md#kształty-popytu).

## Zakłócenia zapisane

Zakłócenie zapisane ma rodzaj, cel, początek, czas trwania i jeden klucz skutku:

```json
{
  "horizon": 12,
  "disruptions": [
    {"kind": "supplier_outage", "target": ["chip-maker"], "start": 4, "duration": 3, "notice": 2, "strength": 0.8},
    {"kind": "line_breakdown", "target": "all", "start": 7, "loss": 0.4}
  ]
}
```

| `kind` | Cel | Klucz skutku | Granice skutku |
| --- | --- | --- | --- |
| `supplier_outage` | dostawcy | `strength` | od 0 do 1 |
| `quality_drop` | dostawcy | `strength` | od 0 do 1 |
| `transport_delay` | dostawcy | `delay` | liczba całkowita, co najmniej 1 |
| `material_shortage` | materiały | `strength` | od 0 do 1 |
| `price_change` | materiały | `factor` | powyżej 0 |
| `demand_shock` | produkty | `factor` | powyżej 0 |
| `line_breakdown` | linie | `loss` | od 0 do 1 |
| `capacity_cut` | linie | `strength` | od 0 do 1 |
| `yield_drop` | linie | `strength` | od 0 do 1 |

- `target` to lista identyfikatorów obiektów tego rodzaju, na który działa zakłócenie,
  `"all"` albo grupa tego rodzaju, zapisana `{"<kind>": "<group>"}`, na przykład
  `{"region": "asia"}`. Lista nie jest pusta i nie wskazuje żadnego obiektu dwa razy.
- `start` to okres od 1 do horyzontu.
- `duration` to co najmniej 1. `line_breakdown` nie ma czasu trwania: działa raz, w
  swoim okresie początku.
- `notice` to domyślnie 0. Zakłócenie jest widoczne od okresu `start - notice`, który
  jest co najmniej 1. Przerwa w dostawach powyżej jest widoczna od okresu 2 i działa w
  okresach 4, 5 i 6.
- Każdy klucz to stała liczba.
- Zakłócenia mają numery `disruption-1`, `disruption-2` i tak dalej, w kolejności
  `start - notice`, czyli pierwszego okresu, w którym każde jest widoczne, a potem w
  kolejności listy. Lista zachowuje swoją kolejność. Opis przebiegu nigdy ich nie
  pokazuje.

Co robi każdy rodzaj, podaje strona [Zakłócenia](../rules/disruptions.md).

## Zakłócenia losowe

Zakłócenie losowe to nazwana reguła, która losuje zakłócenia z ziarna:

```json
{
  "horizon": 12,
  "random_disruptions": [
    {"name": "outages", "kind": "supplier_outage", "target": "all", "chance": 0.05,
     "notice": 1, "duration": {"min": 1, "max": 3},
     "strength": {"min": 0.2, "max": 0.8, "distribution": "triangular", "mode": 0.5}},
    {"name": "breakdowns", "kind": "line_breakdown", "target": ["assembly"],
     "chance": 0.1, "choose": "one", "loss": {"min": 0.1, "max": 0.5}}
  ]
}
```

- `name` to identyfikator, jedyny taki w scenariuszu. Od niego zależy strumień losowań
  reguły. Dlatego dodanie lub usunięcie reguły nie zmienia żadnego losowania innych
  reguł.
- `kind`, `target` i klucz skutku są takie jak w zakłóceniu zapisanym. `line_breakdown`
  nie ma `duration`; każdy inny rodzaj go wymaga.
- `chance` to szansa od 0 do 1, że zakłócenie zacznie się w okresie.
- Bez `choose` każdy cel reguły może w każdym okresie zacząć własne zakłócenie. Z
  `choose: "one"` w okresie zaczyna się najwyżej jedno zakłócenie, na celu z
  najmniejszym losowaniem.
- `duration` to stała liczba albo zakres jednostajny, co najmniej 1. Skutek to stała
  liczba albo zakres dowolnego rozkładu; `delay` w `transport_delay` może być tylko
  jednostajny. Każdy z nich jest losowany w okresie początku zakłócenia.
- `notice` to domyślnie 0. Reguła zachowuje każdy wylosowany początek; początek w
  okresie do `notice` włącznie jest widoczny od okresu 1.
- Opis przebiegu pokazuje reguły, ale nie zakłócenia, które one losują.

## Zapisany początek i kaskada

Reguła może zacząć swoje jedno zakłócenie w zapisanym okresie. Reguła może też podnieść
szansę innej reguły:

```json
{
  "horizon": 12,
  "random_disruptions": [
    {"name": "boom", "kind": "demand_shock", "target": "all", "start": 6, "notice": 2,
     "duration": 2, "factor": {"min": 1.2, "max": 2}},
    {"name": "outages", "kind": "supplier_outage", "target": "all", "chance": 0.05,
     "duration": 2, "strength": 0.5,
     "raises": {"rule": "delays", "factor": 3, "periods": 2}},
    {"name": "delays", "kind": "transport_delay", "target": "all", "chance": 0.05,
     "duration": 1, "delay": {"min": 1, "max": 2}}
  ]
}
```

- Reguła z `start` zaczyna dokładnie jedno zakłócenie, w tym okresie, na jednym celu
  wylosowanym ze swojego `target`. Nie ma `chance` ani `choose`. Jej `start` leży od
  `notice + 1` do horyzontu.
- `raises` wskazuje w `rule` inną regułę scenariusza, podaje `factor` powyżej 1 i liczbę
  okresów `periods`, co najmniej 1. Początek zakłócenia reguły w okresie s mnoży szansę
  wskazanej reguły przez ten czynnik, najwyżej do 1, w okresach od s + 1 do s +
  `periods`. Tutaj przerwa w dostawach w okresie 5 podnosi szansę opóźnienia transportu
  do 0.15 w okresach 6 i 7.
- Kaskada ma jeden poziom. Wskazana reguła ma `chance`, nie ma `start` ani własnego
  `raises`. Żadna reguła nie wskazuje samej siebie.

Nakładające się okna opisuje strona [Zakłócenia](../rules/disruptions.md#kaskady).

## Prognozy

Wpis prognozy daje agentowi oszacowanie popytu nadchodzących okresów dla par, które są
jego celem:

```json
{
  "horizon": 12,
  "forecasts": [
    {"target": "all", "periods_ahead": 3, "noise": 0.1, "noise_growth": 0.05}
  ]
}
```

- `target` ma te same postacie co cel kształtu popytu. Para jest celem najwyżej jednego
  wpisu. Para bez wpisu nie ma prognozy.
- `periods_ahead` jest od 1 do horyzontu.
- `noise` i `noise_growth` to części od 0 do 1. Błąd e prognozy na k okresów naprzód to
  suma k przyrostów, z których każdy jest losowany z równą szansą w swoim zakresie:
  jeden od `-noise` do `noise` i k - 1 od `-noise_growth` do `noise_growth`. Leży od
  -(`noise` + `noise_growth` x (k - 1)) do tej samej wartości powyżej 0. Tutaj mieści
  się w 0.1 na jeden okres naprzód i w 0.2 na trzy okresy naprzód.

Zobacz [Informacje](../rules/information.md#prognozy).

## Ukryte grupy

`hidden` wymienia grupy parametrów ukryte przed agentem:

```json
{
  "horizon": 12,
  "hidden": ["customers.products.demand", "lines.items.yield"]
}
```

Można wymienić tylko te dziewięć nazw, każdą raz:

- `customers.products.demand`, która ukrywa też trwałość popytu i część wspólną każdego
  produktu;
- `suppliers.catalogue.punctuality`, `suppliers.catalogue.delay`,
  `suppliers.catalogue.completeness` i `suppliers.catalogue.acceptance`;
- `lines.items.yield`, `lines.breakdown_chance` i `lines.breakdown_loss`;
- `disruptions.duration`, która też usuwa szoki popytu z prognoz.

Co ukrywa każda z nich, podaje strona
[Informacje](../rules/information.md#ukryte-grupy-parametrów).

## Błędy

Scenariusz jest czytany razem ze swoim manifestem. Odpowiedź na pierwszy problem to 422
z jego miejscem, tak jak w manifeście:

```json
{"detail": "disruptions.0.start: is not from 1 to the horizon"}
```

Najpierw sprawdzana jest postać każdego klucza: nieznane i brakujące klucze, typy,
miejsca po przecinku i granice. Potem idą reguły, które potrzebują tylko scenariusza, a
potem reguły, które potrzebują manifestu albo łączą horyzont z innymi kluczami:

| Reguła | Przykładowa odpowiedź |
| --- | --- |
| Ukryta grupa to jedna z dziewięciu nazw, wymieniona raz. | `hidden.0: is not a group that may be hidden` |
| Reguła zakłóceń losowych ma unikalną nazwę; ma `chance`, gdy nie ma `start`, i nie ma go, gdy ma `start`; jej `raises` wskazuje inną regułę z szansą. | `random_disruptions.0.raises.rule: names its own rule` |
| Losowany czas trwania, losowane `delay` i `raises.periods` to co najmniej 1. | `random_disruptions.0.duration: is below 1` |
| Każdy identyfikator wskazuje w manifeście obiekt właściwego rodzaju. | `start.stock.main.glass: is not an item` |
| Początkowe zamówienie klienta wskazuje parę, którą ma manifest; początkowe zamówienie u dostawcy materiał z katalogu. | `start.customer_orders.0.product: is not bought by the customer` |
| Cel wskazuje obiekty rodzaju, na który działa zakłócenie, albo grupę tego rodzaju, która ma członków. | `disruptions.0.target: names chip, not one of its kind` |
| Początki, okresy terminu i przybycia leżą od 1 do horyzontu; żadne zakłócenie nie jest widoczne przed okresem 1. | `disruptions.0.notice: is visible before period 1` |
| Zapas początkowy i początkowe zamówienia u dostawców do magazynu mieszczą się w jego pojemności i są pozycjami, które on przyjmuje. | `start.stock.main: takes more space than the warehouse has` |
| Para ma najwyżej jeden wpis prognozy, a `periods_ahead` to najwyżej horyzont. | `forecasts.0.periods_ahead: is above the horizon` |
| Zmiany ceny nigdy nie obniżają najniższej ceny materiału poniżej jego wartości odzysku ani poniżej jego opłaty za anulowanie. Losowa zmiana ceny liczy się ze swoim najmniejszym czynnikiem. | `disruptions.0.factor: takes the price of chip below its salvage value` |
| Każdy materiał użyty w recepturze może dotrzeć przed końcem horyzontu albo jest w zapasie początkowym lub w początkowym zamówieniu u dostawcy. | `horizon: chip cannot arrive within it and is not at hand` |
| Scenariusz jest odrzucany, gdy kwota jego przebiegu może dojść do 10 do potęgi 24, największej liczby, jaką mieści zapis przebiegu: ilości w całym horyzoncie, miejsce, które mogą zająć, największa kwota na sztukę albo pieniądze z obu, w których liczy się do 1000 przezbrojeń na sztukę zapasu i 1000 jednostek naprawy na godzinę linii. | `horizon: a run of this scenario can exceed the numbers the record holds` |

- Materiał może dotrzeć przed końcem horyzontu, gdy czas realizacji jednego z jego
  wpisów katalogu jest mniejszy od horyzontu. Czas realizacji to czas ekspresowy, gdy
  wpis go ma, a dla zakresu jego największa wartość.
- Granica kwot rośnie z horyzontem, ilościami, cenami i stopami odsetek. Każdy
  scenariusz biblioteki mieści się w niej na fabryce przykładowej z horyzontem 520.
