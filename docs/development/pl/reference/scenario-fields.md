# Pola scenariusza

Te tabele opisują każde pole scenariusza. Najpierw przeczytaj
[Jak czytać tabele](manifest-fields.md#jak-czytać-tabele) i
[Zakresy](manifest-fields.md#zakresy).

## Scenariusz

Każda liczba scenariusza to stała liczba, poza czasem trwania i działaniem zakłócenia
losowego.

### Najwyższy poziom

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | tekst | | | brak | Nazwa scenariusza. Nigdy niepokazywana agentowi. | |
| `description` | tekst | | | brak | Opis scenariusza. Nigdy niepokazywany agentowi. | |
| `horizon` | okresy | 0 | od 1 do 520; każdy materiał użyty w recepturze może dotrzeć przed jego końcem albo jest pod ręką | wymagany | Liczba okresów przebiegu. | każdy przepływ |
| `start` | obiekt | | | pusty | Stan fabryki przed okresem 1. | |
| `demand_shapes` | lista kształtów popytu | | | `[]` | Czynniki popytu bazowego w czasie. | `units_ordered` |
| `forecasts` | lista wpisów prognozy | | najwyżej jeden wpis na parę klienta i produktu | `[]` | Prognozy popytu w każdej obserwacji. | `forecasts` obserwacji |
| `disruptions` | lista zakłóceń zapisanych | | | `[]` | Zakłócenia w zapisanych okresach, o numerach `disruption-1`, `disruption-2` i tak dalej, w kolejności `start - notice`, a potem listy. | miara każdego rodzaju |
| `random_disruptions` | lista reguł zakłóceń losowych | | nazwy jedyne w scenariuszu | `[]` | Reguły, które losują zakłócenia z ziarna. | miara każdego rodzaju |
| `hidden` | lista nazw ukrytych grup parametrów | | dziewięć nazw poniżej, każda raz | `[]` | Parametry ukryte przed agentem. | opis i obserwacje |

### Start

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- |
| `start.cash` | pieniądze | 4 | może być poniżej 0 | 0 | Gotówka przed okresem 1. | `cash` |
| `start.stock` | mapa identyfikatora magazynu na mapę identyfikatora pozycji na ilość | 3 | co najmniej 0; pozycje, które magazyn przyjmuje; razem z początkowymi zamówieniami u dostawców do magazynu mieści się w jego pojemności | `{}`: 0 każdej pozycji | Zapas przed okresem 1. | `stock` |
| `start.condition` | mapa identyfikatora linii na część | 4 | od 0 do 1 | `{}`: 1 dla każdej linii | Stan przed okresem 1. | `condition` |
| `start.set_for` | mapa identyfikatora linii na identyfikator pozycji | | pozycja, którą linia wytwarza | `{}`: żadna pozycja | Pozycja, na którą ustawiona jest każda linia. Przy przezbrojeniach pierwsza produkcja linii nieustawionej na żadną pozycję płaci jedno przezbrojenie. | `changeovers` |
| `start.customer_orders` | lista zamówień klientów | | | `[]` | Zamówienia klientów otwarte na starcie. Każde wpłynęło w okresie 0 i ma cenę, cierpliwość i kary swojej pary. | `units_ordered` |
| `start.customer_orders.*.customer` | identyfikator klienta | | klient | wymagany | Klient zamówienia. | |
| `start.customer_orders.*.product` | identyfikator produktu | | produkt, który klient kupuje | wymagany | Produkt zamówienia. | |
| `start.customer_orders.*.quantity` | ilość | 3 | powyżej 0 | wymagany | Zamówione sztuki. | `units_ordered` |
| `start.customer_orders.*.due` | okresy | 0 | od 1 do `horizon` | wymagany | Okres terminu zamówienia. | `units_shipped_late` |
| `start.supplier_orders` | lista zamówień u dostawców | | | `[]` | Zamówienia u dostawców w drodze na starcie. Każde zostało złożone w okresie 0 po wylosowanej cenie, bez rabatu i nie jako ekspresowe; gdy cena jest losowana w każdym okresie, jest to cena okresu 1. Dociera w całości i przyjęte. Można je anulować. | `units_arrived` |
| `start.supplier_orders.*.supplier` | identyfikator dostawcy | | dostawca | wymagany | Dostawca zamówienia. | |
| `start.supplier_orders.*.material` | identyfikator materiału | | materiał z katalogu dostawcy | wymagany | Materiał zamówienia. | |
| `start.supplier_orders.*.quantity` | ilość | 3 | powyżej 0 | wymagany | Zamówione sztuki. | `units_arrived` |
| `start.supplier_orders.*.arrival` | okresy | 0 | od 1 do `horizon` | wymagany | Okres, w którym zamówienie dociera. | `units_arrived` |
| `start.supplier_orders.*.warehouse` | identyfikator magazynu | | magazyn, który przyjmuje materiał | jedyny magazyn; wymagany przy kilku | Magazyn, do którego idzie zamówienie. | `stock` |

### Kształty popytu

Każdy klucz kształtu popytu zmienia `units_ordered`. W okresie t popyt pary to jej
popyt bazowy razy czynnik każdego kształtu, którego celem jest ta para.

| Ścieżka klucza | Typ | Miejsca | Granice | Rodzaje | Skutek |
| --- | --- | --- | --- | --- | --- |
| `demand_shapes.*.kind` | `trend`, `season`, `step`, `ramp` lub `s_curve` | | wymagany | wszystkie | Postać czynnika. |
| `demand_shapes.*.target` | `"all"`, obiekt z `customer`, `product` lub oboma, albo grupa `{"<kind>": "<group>"}` | | wymagany; para, którą ma manifest; grupa klientów lub produktów, której rodzaj się zgadza | wszystkie | Pary klienta i produktu, które kształt mnoży. |
| `demand_shapes.*.target.customer` | identyfikator klienta | | klient | wszystkie | Jeden klient; każdy klient, gdy pominięty. |
| `demand_shapes.*.target.product` | identyfikator produktu | | produkt | wszystkie | Jeden produkt; każdy produkt, gdy pominięty. |
| `demand_shapes.*.rate` | stopa | 4 | powyżej -1 | `trend` | Czynnik `(1 + rate) ** (t - 1)`. |
| `demand_shapes.*.factors` | lista czynników | 4 | co najmniej jeden; każdy co najmniej 0 | `season` | Czynnik `factors[((t - 1) // period_length) % len(factors)]`. |
| `demand_shapes.*.period_length` | okresy | 0 | co najmniej 1 | `season` | Okresy, przez które trwa każdy czynnik. |
| `demand_shapes.*.period` | okresy | 0 | dowolna liczba całkowita | `step` | Pierwszy okres `factor`. Przed nim czynnik to 1. |
| `demand_shapes.*.factor` | czynnik | 4 | co najmniej 0 | `step` | Czynnik od `period`. |
| `demand_shapes.*.first` | okresy | 0 | dowolna liczba całkowita | `ramp` | Ostatni okres `from_factor`. |
| `demand_shapes.*.last` | okresy | 0 | po `first` | `ramp` | Pierwszy okres `to_factor`. Między `first` a `last` czynnik zmienia się po linii prostej. |
| `demand_shapes.*.middle` | okresy | 0 | dowolna liczba całkowita | `s_curve` | Okres w połowie drogi między dwoma czynnikami. |
| `demand_shapes.*.steepness` | stopa | 4 | powyżej 0 | `s_curve` | Szybkość zmiany: czynnik `from_factor + (to_factor - from_factor) / (1 + exp(-steepness * (t - middle)))`. |
| `demand_shapes.*.from_factor` | czynnik | 4 | co najmniej 0 | `ramp`, `s_curve` | Czynnik przed zmianą. |
| `demand_shapes.*.to_factor` | czynnik | 4 | co najmniej 0 | `ramp`, `s_curve` | Czynnik po zmianie. |

### Prognozy

Każdy klucz wpisu prognozy zmienia `forecasts` obserwacji.

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Skutek |
| --- | --- | --- | --- | --- | --- |
| `forecasts.*.target` | jak `demand_shapes.*.target` | | para jest celem najwyżej jednego wpisu | wymagany | Pary, które dostają prognozę. |
| `forecasts.*.target.customer` | identyfikator klienta | | klient | każdy klient | Jeden klient. |
| `forecasts.*.target.product` | identyfikator produktu | | produkt | każdy produkt | Jeden produkt. |
| `forecasts.*.periods_ahead` | okresy | 0 | od 1 do `horizon` | wymagany | Na ile okresów naprzód patrzy każda prognoza. |
| `forecasts.*.noise` | część | 4 | od 0 do 1 | wymagany | Szerokość błędu na jeden okres naprzód. |
| `forecasts.*.noise_growth` | część | 4 | od 0 do 1 | wymagany | Szerokość każdego kolejnego przyrostu. Błąd e prognozy na k okresów naprzód to suma k przyrostów, z których każdy jest losowany z równą szansą w swoim zakresie: jeden od `-noise` do `noise` i k - 1 od `-noise_growth` do `noise_growth`. Leży od -(`noise` + `noise_growth` x (k - 1)) do tej samej wartości powyżej 0. |

### Zakłócenia zapisane

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- |
| `disruptions.*.kind` | jeden z dziewięciu rodzajów poniżej | | | wymagany | Na co działa zakłócenie i jak. | |
| `disruptions.*.target` | lista identyfikatorów, `"all"` albo grupa `{"<kind>": "<group>"}` | | obiekty rodzaju, na który działa zakłócenie, albo ich grupa, która ma członków; lista niepusta i bez powtórzonego identyfikatora | wymagany | Obiekty, na które działa zakłócenie. | |
| `disruptions.*.start` | okresy | 0 | od 1 do `horizon` | wymagany | Pierwszy okres działania. | miara rodzaju zakłócenia |
| `disruptions.*.duration` | okresy | 0 | co najmniej 1; niedozwolony dla `line_breakdown` | wymagany | Okresy działania. | miara rodzaju zakłócenia |
| `disruptions.*.notice` | okresy | 0 | co najmniej 0; `start - notice` co najmniej 1 | 0 | Okresy przed `start`, od których zakłócenie jest widoczne. | `disruptions` obserwacji |
| `disruptions.*.strength` | część | 4 | od 0 do 1 | wymagany dla jego rodzajów | Działanie `supplier_outage`, `quality_drop`, `material_shortage`, `capacity_cut` i `yield_drop`. | miara rodzaju zakłócenia |
| `disruptions.*.delay` | okresy | 0 | co najmniej 1 | wymagany dla jego rodzaju | Działanie `transport_delay`. | `units_arrived_late` |
| `disruptions.*.factor` | czynnik | 4 | powyżej 0; zmiany ceny utrzymują najniższą cenę materiału na poziomie jego wartości odzysku i jego opłat za anulowanie lub wyżej | wymagany dla jego rodzajów | Działanie `demand_shock` i `price_change`. | miara rodzaju zakłócenia |
| `disruptions.*.loss` | część | 4 | od 0 do 1 | wymagany dla jego rodzaju | Działanie `line_breakdown`. | `condition` |

| `kind` | Cel | Klucz działania | Działanie w czasie trwania | Zmienia |
| --- | --- | --- | --- | --- |
| `supplier_outage` | dostawcy | `strength` | Ilość docierająca od dostawcy razy (1 - strength). | `units_arrived` |
| `quality_drop` | dostawcy | `strength` | Przyjęcie dostaw od dostawcy razy (1 - strength). | `units_rejected_at_inspection` |
| `transport_delay` | dostawcy | `delay` | Dostawa, która ma dotrzeć w okresie działania, dociera `delay` okresów później. | `units_arrived_late` |
| `material_shortage` | materiały | `strength` | `max_quantity` materiału u każdego dostawcy razy (1 - strength). | `decisions_rejected` |
| `price_change` | materiały | `factor` | Cena materiału u każdego dostawcy razy `factor`, dla zamówień złożonych w czasie działania. | `material_payment` |
| `demand_shock` | produkty | `factor` | Popyt na produkt od każdego klienta razy `factor`. | `units_ordered` |
| `line_breakdown` | linie | `loss` | Stan razy (1 - loss), raz, w okresie początku. | `condition` |
| `capacity_cut` | linie | `strength` | Zdolność i godziny nadgodzin razy (1 - strength). | `units_started` |
| `yield_drop` | linie | `strength` | Uzysk produkcji rozpoczętej w czasie działania razy (1 - strength). | `units_scrap` |

Dwa zakłócenia tego samego rodzaju na tym samym celu mnożą swoje działania. Wyjątkiem
jest `delay`, które się dodaje.

### Zakłócenia losowe

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek |
| --- | --- | --- | --- | --- | --- | --- |
| `random_disruptions.*.name` | identyfikator | | jedyny w scenariuszu | wymagany | | Nazwa reguły. Od niej zależy strumień losowań reguły. |
| `random_disruptions.*.kind` | jeden z dziewięciu rodzajów | | | wymagany | | Jak w zakłóceniu zapisanym. |
| `random_disruptions.*.target` | jak `disruptions.*.target` | | jak w zakłóceniu zapisanym | wymagany | | Obiekty, w które reguła może trafić. Każde wylosowane zakłócenie trafia w jeden. |
| `random_disruptions.*.chance` | szansa | 4 | od 0 do 1 | wymagany bez `start`; odrzucany z nim | fixed | Szansa, że zakłócenie zacznie się w okresie: na każdym celu albo raz, z `choose`. |
| `random_disruptions.*.choose` | `"one"` | | odrzucany z `start` | brak | | Z `"one"` w okresie zaczyna się najwyżej jedno zakłócenie, na celu z najmniejszym losowaniem. |
| `random_disruptions.*.start` | okresy | 0 | od `notice + 1` do `horizon` | brak | fixed | Jedyny okres, w którym reguła zaczyna swoje jedno zakłócenie, na jednym celu wylosowanym z `target`. |
| `random_disruptions.*.notice` | okresy | 0 | co najmniej 0 | 0 | fixed | Okresy przed początkiem, od których zakłócenie jest widoczne, najwcześniej od okresu 1. Reguła zachowuje każdy wylosowany początek. |
| `random_disruptions.*.duration` | okresy | 0 | co najmniej 1; stała liczba albo zakres jednostajny; niedozwolony dla `line_breakdown` | wymagany | event | Okresy działania każdego zakłócenia. |
| `random_disruptions.*.strength` | część | 4 | od 0 do 1 | wymagany dla jego rodzajów | event | Działanie, jak w zakłóceniu zapisanym. |
| `random_disruptions.*.delay` | okresy | 0 | co najmniej 1; stała liczba albo zakres jednostajny | wymagany dla jego rodzaju | event | Działanie `transport_delay`. |
| `random_disruptions.*.factor` | czynnik | 4 | powyżej 0; zmiana ceny liczy się ze swoim najmniejszym czynnikiem względem wartości odzysku i opłat za anulowanie | wymagany dla jego rodzajów | event | Działanie `demand_shock` i `price_change`. |
| `random_disruptions.*.loss` | część | 4 | od 0 do 1 | wymagany dla jego rodzaju | event | Działanie `line_breakdown`. |
| `random_disruptions.*.raises` | obiekt | | | brak | | Kaskada: po każdym początku zakłócenia tej reguły szansa innej reguły rośnie. |
| `random_disruptions.*.raises.rule` | nazwa reguły | | inna reguła scenariusza, z `chance`, bez `start` i bez `raises` | wymagany | | Reguła, której szansa rośnie. |
| `random_disruptions.*.raises.factor` | czynnik | 4 | powyżej 1 | wymagany | fixed | Szansa wskazanej reguły jest mnożona przez ten czynnik, najwyżej do 1. |
| `random_disruptions.*.raises.periods` | okresy | 0 | co najmniej 1 | wymagany | fixed | Początek w okresie s podnosi szansę w okresach od s + 1 do s + `periods`. Gdy okna się nakładają, liczy się raz największy czynnik. |

Zakłócenie losowe zmienia miarę swojego rodzaju, tak jak zakłócenie zapisane. Czas
trwania i działanie wylosowanego zakłócenia to wartości wylosowane w jego okresie
początku.

### Ukryte grupy parametrów

Nazwy, które może wymienić `hidden`:

| Nazwa | Co ukrywa |
| --- | --- |
| `customers.products.demand` | Popyt każdego klienta i produktu, jego trwałość i część wspólną każdego produktu. |
| `suppliers.catalogue.punctuality` | Szansę, że dostawa jest na czas. |
| `suppliers.catalogue.delay` | Dodatkowe okresy spóźnionej dostawy. |
| `suppliers.catalogue.completeness` | Część otwartej ilości, która dociera. |
| `suppliers.catalogue.acceptance` | Część dostarczonej ilości, która przechodzi kontrolę. |
| `lines.items.yield` | Część rozpoczętych sztuk, które wychodzą dobre. |
| `lines.breakdown_chance` | Szansę awarii linii. |
| `lines.breakdown_loss` | Część stanu, którą zabiera awaria. |
| `disruptions.duration` | Czas trwania każdego zakłócenia i każdej reguły; żadna prognoza nie zawiera szoku popytu. |

Ukryta grupa jest pominięta w opisie i w każdej obserwacji, razem z wartościami
domyślnymi grup. Zobacz [Informacje](../rules/information.md#ukryte-grupy-parametrów).
