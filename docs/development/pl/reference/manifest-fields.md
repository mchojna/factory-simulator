# Pola manifestu

Te tabele opisują każde pole manifestu. Najpierw przeczytaj
[Jak czytać tabele](#jak-czytać-tabele) i [Zakresy](#zakresy).

## Jak czytać tabele

- Ścieżka klucza łączy klucze kropkami. Klucz mapy, taki jak identyfikator, i pozycję
  na liście zapisuje jako `*`: `materials.*.space` to `space` każdego materiału.
- Typ to rodzaj liczby albo tekst, identyfikator, lista, mapa lub obiekt.
- Miejsca to liczba miejsc po przecinku liczby: 3 dla ilości, miejsca i godzin; 4 dla
  pieniędzy, części, szansy, stopy i czynnika; 0 dla okresów, które są liczbami
  całkowitymi. Liczba z większą liczbą miejsc jest odrzucana; liczba z mniejszą jest
  uzupełniana zerami.
- Wartość domyślna to wartość klucza, który pominięto. "wymagany" oznacza klucz bez
  wartości domyślnej. W manifeście wymagany parametr może pochodzić z grupy.
- Losowanie to moment, w którym zakres jest losowany z ziarna: `run` raz na przebieg,
  `period` raz na okres, `event` raz na dostawę, awarię lub wylosowane zakłócenie.
  `fixed` oznacza liczbę, która nigdy nie jest zakresem. Liczba z innym momentem może
  być stałą liczbą albo zakresem.
- Reguła, która porównuje zakres z inną liczbą, bierze tę granicę zakresu, która jest
  najgorsza dla reguły.
- Zmienia podaje miarę, którą zmienia klucz. Zobacz
  [Miary i zapis przebiegu](measures-and-the-record.md).

## Zakresy

Zakres to obiekt w miejscu stałej liczby. Jego klucze stoją pod kluczem parametru, na
przykład `materials.*.storage_cost.min`.

| Klucz | Typ | Reguła |
| --- | --- | --- |
| `min`, `max` | liczby rodzaju parametru | Wymagane. `min` jest co najwyżej `max`; poniżej `max` dla zakresu trójkątnego, normalnego lub logarytmicznie normalnego. |
| `distribution` | `uniform`, `triangular`, `normal` lub `lognormal` | Domyślnie `uniform`. Zakres okresów może być tylko jednostajny. |
| `mode` | liczba rodzaju parametru | Tylko trójkątny, wymagany. Od `min` do `max`; najbardziej prawdopodobna wartość. |
| `mean`, `sd` | liczby rodzaju parametru | Tylko normalny, wymagane. `mean` jest od `min` do `max`, a `sd` powyżej 0. Rozkład normalny jest obcięty do przedziału od `min` do `max`. |
| `median` | liczba rodzaju parametru | Tylko logarytmicznie normalny, wymagany. Od `min` do `max`; `min` jest powyżej 0. |
| `spread` | liczba z 4 miejscami | Tylko logarytmicznie normalny, wymagany. Powyżej 0 i najwyżej 10. Logarytm naturalny wartości ma rozkład normalny ze średnią równą logarytmowi `median` i odchyleniem standardowym `spread`, obcięty do przedziału od `min` do `max`. |
| `drawn` | `run` lub `period` | Tylko w zakresie `price` w katalogu, we wpisie albo w wartościach domyślnych grupy. Domyślnie `run`: losowany raz na przebieg. `period`: losowany dla każdego okresu przed okresem 1; zamówienie zachowuje cenę okresu, w którym zostało złożone. |

Klucz innego rozkładu albo `drawn` w każdym innym zakresie jest odrzucany.

Opis przebiegu dodaje do każdego zakresu `cut_mean`: średnią jego rozkładu obciętego do
`min` i `max`, zaokrągloną połówkowo do parzystej do 6 miejsc po przecinku. Zakres
normalny zachowuje własne `mean`, średnią bez obcięcia. Popyt logarytmicznie normalny z
medianą 35 i rozrzutem 0.4, obcięty do 14 do 70, ma `cut_mean` 36.222159. Manifest lub
scenariusz, który zapisuje `cut_mean`, jest odrzucany.

## Manifest

### Najwyższy poziom

| Ścieżka klucza | Typ | Wartość domyślna | Skutek |
| --- | --- | --- | --- |
| `name` | tekst | brak | Nazwa fabryki. Pokazywana agentowi; nie zmienia żadnego przebiegu. |
| `description` | tekst | brak | Opis fabryki. Tylko pokazywany. |
| `period_name` | tekst | brak | Nazwa jednego okresu, na przykład "week". Tylko pokazywana. |
| `materials` | mapa identyfikatora na materiał | wymagany | Pozycje kupowane od dostawców. |
| `components` | mapa identyfikatora na komponent | wymagany | Pozycje wytwarzane z materiałów. |
| `products` | mapa identyfikatora na produkt | wymagany | Pozycje wytwarzane z komponentów i sprzedawane. |
| `suppliers` | mapa identyfikatora na dostawcę | wymagany | Firmy, które sprzedają materiały. |
| `customers` | mapa identyfikatora na klienta | wymagany | Firmy, które kupują produkty. |
| `lines` | mapa identyfikatora na linię | wymagany | Linie produkcyjne. |
| `warehouses` | mapa identyfikatora na magazyn | wymagany | Miejsca składowania pozycji. |
| `cash` | obiekt | wymagany | Limit kredytowy i stopy odsetek. |
| `routes` | mapa magazynu na mapę magazynu na trasę | `{}` | Jednokierunkowe trasy między magazynami. |
| `groups` | mapa identyfikatora na grupę | `{}` | Wartości domyślne, cele i miary wspólne dla członków. |

Identyfikator składa się z małych liter, cyfr i pojedynczych myślników, zaczyna się od
litery i ma najwyżej 40 znaków. Materiały, komponenty i produkty mają jeden wspólny
zbiór identyfikatorów; dostawcy, klienci, linie, magazyny i grupy mają każdy własny.

### Pozycje

Klucze materiałów, komponentów i produktów.

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `materials.*.name`, `materials.*.description`, `materials.*.unit`, `components.*.name`, `components.*.description`, `components.*.unit`, `products.*.name`, `products.*.description`, `products.*.unit` | tekst | | | brak | | Pokazywane agentowi; nie zmieniają żadnego przebiegu. | |
| `materials.*.space`, `components.*.space`, `products.*.space` | miejsce | 3 | powyżej 0 | wymagany | fixed | Miejsce, jakie jedna sztuka zajmuje w magazynie. | `space_used` |
| `materials.*.storage_cost`, `components.*.storage_cost`, `products.*.storage_cost` | pieniądze | 4 | co najmniej 0 | wymagany | run | Koszt przechowania jednej sztuki przez jeden okres, razy `storage_factor` jej magazynu. | `storage_cost` |
| `materials.*.salvage_value`, `components.*.salvage_value`, `products.*.salvage_value` | pieniądze | 4 | co najmniej 0; dla materiału najwyżej jego najniższa cena u dowolnego dostawcy, z rabatami; dla komponentu lub produktu najwyżej najmniejsza, po jego recepturach i liniach, suma jego wejść po ich wartościach odzysku i `cost` wpisu linii | wymagany | run | Wartość jednej sztuki w zapasie na końcu przebiegu. | `stock_salvage_value` |
| `materials.*.groups`, `components.*.groups`, `products.*.groups` | lista identyfikatorów grup | | grupy, które istnieją; najwyżej jedna z każdego rodzaju | `[]` | | Grupy, których wartości domyślne pozycja przyjmuje, w tej kolejności. | |
| `components.*.recipes`, `products.*.recipes` | mapa nazwy receptury na mapę identyfikatora wejścia na ilość | 3 | co najmniej jedna receptura, każda z co najmniej jednym wejściem; ilości powyżej 0; wejścia komponentu to materiały, wejścia produktu to komponenty | wymagany | fixed | Sztuki każdego wejścia zużyte na jedną rozpoczętą sztukę. | `stock` |
| `components.*.default_recipe`, `products.*.default_recipe` | nazwa receptury | | jedna z `recipes` | jedyna receptura, także gdy zapisano null; wymagany przy kilku | fixed | Receptura decyzji produkcji, która nie podaje żadnej. | `stock` |
| `products.*.common_share` | część | 4 | od 0 do 1; powyżej 0 tylko wtedy, gdy produkt kupuje dwóch lub więcej klientów z zakresem `demand` | 0 | fixed | Część zmienności popytu, którą klienci produktu mają wspólną. Przy 0 popyt każdego klienta zmienia się osobno. | `units_ordered` |

### Dostawcy

| Ścieżka klucza | Typ | Granice | Wartość domyślna | Skutek |
| --- | --- | --- | --- | --- |
| `suppliers.*.name`, `suppliers.*.description` | tekst | | brak | Tylko pokazywane. |
| `suppliers.*.catalogue` | mapa identyfikatora materiału na wpis katalogu | niepusta; każdy klucz to materiał | wymagany | Materiały, które dostawca sprzedaje, z ich warunkami. |
| `suppliers.*.groups` | lista identyfikatorów grup | grupy, które istnieją; najwyżej jedna z każdego rodzaju | `[]` | Grupy, których wartości domyślne przyjmują wpisy dostawcy, przed grupami materiału. |

### Wpisy katalogu

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `suppliers.*.catalogue.*.price` | pieniądze | 4 | co najmniej 0 | wymagany | run, albo period z `drawn: period` | Cena jednej przyjętej sztuki. | `material_payment` |
| `suppliers.*.catalogue.*.lead_time` | okresy | 0 | co najmniej 1 | wymagany | run | Okresy od złożenia zamówienia do jego przybycia, gdy jest na czas. | `units_arrived` |
| `suppliers.*.catalogue.*.max_quantity` | ilość | 3 | powyżej 0 | wymagany | run | Największa ilość materiału zamówiona u tego dostawcy w jednym okresie. | `decisions_rejected` |
| `suppliers.*.catalogue.*.punctuality` | szansa | 4 | od 0 do 1 | wymagany | run | Szansa, że dostawa jest na czas. | `units_arrived_late` |
| `suppliers.*.catalogue.*.delay` | okresy | 0 | co najmniej 1 | wymagany | event | Dodatkowe okresy spóźnionej dostawy. | `units_arrived` |
| `suppliers.*.catalogue.*.completeness` | część | 4 | od 0 do 1 | wymagany | event | Część otwartej ilości, która dociera. | `units_arrived` |
| `suppliers.*.catalogue.*.acceptance` | część | 4 | od 0 do 1 | wymagany | event | Część dostarczonej ilości, która przechodzi kontrolę i jest opłacana. | `units_accepted` |
| `suppliers.*.catalogue.*.cancellation_fee` | pieniądze | 4 | co najmniej 0; najwyżej najniższa cena, z rabatami | 0 | run | Opłata za anulowaną sztukę. | `cancellation_fee` |
| `suppliers.*.catalogue.*.backfill_delay` | okresy | 0 | co najmniej 0 | 0 | run | Okresy po dostawie, po których dociera część wstrzymana przez kompletność; przy 0 ta część przepada. | `units_lost_in_delivery` |
| `suppliers.*.catalogue.*.express_lead_time` | okresy | 0 | co najmniej 1; poniżej `lead_time` | brak: bez zamówień ekspresowych | run | Czas realizacji zamówienia ekspresowego. | `units_arrived` |
| `suppliers.*.catalogue.*.express_cost` | pieniądze | 4 | co najmniej 0 | wymagany z `express_lead_time`, odrzucany bez niego | run | Dodatkowa cena za sztukę zamówienia ekspresowego. | `material_payment` |
| `suppliers.*.catalogue.*.min_quantity` | ilość | 3 | co najmniej 0; najwyżej `max_quantity` | brak: bez minimum | run | Najmniejsza ilość jednego zamówienia. Daje `linear` równe false i robi z manifestu manifest z korzyściami skali; wartość 0 nie dodaje do programu zmiennej całkowitoliczbowej. | `decisions_rejected` |
| `suppliers.*.catalogue.*.discounts` | lista progów rabatu | | `from` rośnie, a `price` maleje z każdym kolejnym progiem | `[]` | | Zamówienie dostaje dla każdej sztuki cenę najwyższego progu, który osiąga jego ilość. Robi z manifestu manifest z korzyściami skali. | `material_payment` |
| `suppliers.*.catalogue.*.discounts.*.from` | ilość | 3 | od `min_quantity`, albo od 0 bez niego, do `max_quantity` | wymagany | fixed | Najmniejsza ilość zamówienia po cenie progu. | `material_payment` |
| `suppliers.*.catalogue.*.discounts.*.price` | pieniądze | 4 | co najmniej 0; pierwszy próg poniżej `price` | wymagany | run | Cena każdej sztuki zamówienia, które osiąga próg. | `material_payment` |

### Klienci

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `customers.*.name`, `customers.*.description` | tekst | | | brak | | Tylko pokazywane. | |
| `customers.*.products` | mapa identyfikatora produktu na produkt klienta | | niepusta; każdy klucz to produkt | wymagany | | Produkty, które klient kupuje, z ich warunkami. | |
| `customers.*.payment_terms` | okresy | 0 | co najmniej 0 | 0 | run | Okresy od wysyłki do jej zapłaty; przy 0 klient płaci od razu. | `receivables` |
| `customers.*.groups` | lista identyfikatorów grup | | grupy, które istnieją; najwyżej jedna z każdego rodzaju | `[]` | | Grupy, których wartości domyślne klient przyjmuje, przed grupami produktu. | |

### Produkty klientów

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `customers.*.products.*.price` | pieniądze | 4 | co najmniej 0 | wymagany | run | Cena jednej wysłanej sztuki. | `revenue` |
| `customers.*.products.*.transport_cost` | pieniądze | 4 | co najmniej 0 | wymagany | run | Koszt wysłania jednej sztuki, razy `transport_factor` magazynu, z którego wychodzi. | `transport_cost` |
| `customers.*.products.*.demand` | ilość | 3 | co najmniej 0 | wymagany | period | Popyt bazowy na okres, przed kształtami popytu i zakłóceniami. | `units_ordered` |
| `customers.*.products.*.demand_persistence` | część | 4 | od 0 do 1; tylko z zakresem `demand` | 0 | fixed | Część p popytu bazowego okresu, która przechodzi na następny: `base(t) = p * base(t - 1) + (1 - p) * draw(t)`. | `units_ordered` |
| `customers.*.products.*.lead_time` | okresy | 0 | co najmniej 0 | wymagany | run | Okresy od wpłynięcia zamówienia klienta do jego okresu terminu; przy 0 termin jest od razu. | `units_shipped_late` |
| `customers.*.products.*.patience` | okresy | 0 | co najmniej 0 | wymagany | run | Okresy po okresie terminu, zanim reszta zamówienia przepadnie. | `units_lost` |
| `customers.*.products.*.late_penalty` | pieniądze | 4 | co najmniej 0 | wymagany | run | Kara za sztukę niewysłaną do zamknięcia każdego okresu od okresu terminu, poza okresem, w którym zamówienie przepada. | `late_penalty` |
| `customers.*.products.*.lost_sale_penalty` | pieniądze | 4 | co najmniej 0 | wymagany | run | Kara za utraconą sztukę. | `lost_sale_penalty` |

### Linie

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lines.*.name`, `lines.*.description` | tekst | | | brak | | Tylko pokazywane. | |
| `lines.*.warehouse` | identyfikator magazynu | | przyjmuje każde wejście i wyjście linii; każde wejście może do niego dotrzeć trasami | jedyny magazyn; wymagany przy kilku | fixed | Magazyn, z którego linia bierze wejścia i do którego oddaje to, co wytworzy. | `stock` |
| `lines.*.capacity` | godziny | 3 | powyżej 0 | wymagany | run | Godziny produkcji na okres przy stanie 1. | `units_started` |
| `lines.*.wear_per_period` | część | 4 | od 0 do 1 | wymagany | run | Część stanu tracona w każdym okresie. | `condition` |
| `lines.*.wear_per_hour` | stopa | 4 | co najmniej 0; `wear_per_hour * (capacity + overtime_hours)` najwyżej `1 - wear_per_period`, każda przy swojej największej wartości | wymagany | run | Stan tracony na godzinę produkcji. | `condition` |
| `lines.*.breakdown_chance` | szansa | 4 | od 0 do 1 | wymagany | run | Szansa awarii w okresie. | `breakdowns` |
| `lines.*.breakdown_loss` | część | 4 | od 0 do 1 | wymagany | event | Część stanu tracona przy awarii. | `condition` |
| `lines.*.repair_cost` | pieniądze | 4 | co najmniej 0 | wymagany | run | Koszt przywrócenia stanu o 1. | `repair_cost` |
| `lines.*.repair_time` | godziny | 3 | powyżej 0 | wymagany | run | Godziny zużyte na przywrócenie stanu o 1. | `units_started` |
| `lines.*.repair_limit` | część | 4 | powyżej 0, najwyżej 1 | wymagany | run | Największy stan przywrócony w jednym okresie. | `condition` |
| `lines.*.overtime_hours` | godziny | 3 | co najmniej 0 | 0 | run | Dodatkowe godziny produkcji na okres przy stanie 1. | `units_started` |
| `lines.*.overtime_cost` | pieniądze | 4 | co najmniej 0 | wymagany, gdy `overtime_hours` może być powyżej 0, odrzucany, gdy `overtime_hours` pominięto albo ustalono na stałe 0 | run | Koszt jednej godziny nadgodzin. | `overtime_cost` |
| `lines.*.items` | mapa identyfikatora komponentu lub produktu na wpis linii | | niepusta | wymagany | | Pozycje, które linia wytwarza, i sposób ich wytwarzania. | |
| `lines.*.groups` | lista identyfikatorów grup | | grupy, które istnieją; najwyżej jedna z każdego rodzaju | `[]` | | Grupy, których wartości domyślne linia przyjmuje, przed grupami pozycji. | |

### Wpisy linii

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `lines.*.items.*.time` | godziny | 3 | powyżej 0 | wymagany | run | Godziny na rozpoczętą sztukę. | `units_started` |
| `lines.*.items.*.cost` | pieniądze | 4 | co najmniej 0 | wymagany | run | Koszt na rozpoczętą sztukę. | `production_cost` |
| `lines.*.items.*.yield` | część | 4 | od 0 do 1 | wymagany | period | Część rozpoczętych sztuk, które wychodzą dobre. | `units_scrap` |
| `lines.*.items.*.lead_time` | okresy | 0 | co najmniej 1 | 1 | run | Produkcja rozpoczęta w okresie t trafia do zapasu przy zamknięciu okresu t + `lead_time` - 1. | `stock` |
| `lines.*.items.*.changeover_time` | godziny | 3 | co najmniej 0 | brak | run | Zwykłe godziny potrzebne, aby ustawić linię na tę pozycję. Daje `linear` równe false i robi z manifestu manifest z korzyściami skali; wartość 0 nie dodaje do programu zmiennej całkowitoliczbowej. | `units_started` |
| `lines.*.items.*.changeover_cost` | pieniądze | 4 | co najmniej 0 | brak | run | Koszt ustawienia linii na tę pozycję. Daje `linear` równe false i robi z manifestu manifest z korzyściami skali; wartość 0 nie dodaje do programu zmiennej całkowitoliczbowej. | `changeover_cost` |

### Magazyny

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `warehouses.*.name`, `warehouses.*.description` | tekst | | | brak | | Tylko pokazywane. | |
| `warehouses.*.capacity` | miejsce | 3 | powyżej 0 | wymagany | fixed | Miejsce, jakie ma magazyn. | `decisions_rejected` |
| `warehouses.*.storage_factor` | czynnik | 4 | powyżej 0 | 1 | fixed | Czynnik kosztu składowania pozycji w tym magazynie. | `storage_cost` |
| `warehouses.*.transport_factor` | czynnik | 4 | powyżej 0 | 1 | fixed | Czynnik kosztu transportu wysyłek z tego magazynu. | `transport_cost` |
| `warehouses.*.accepts` | lista z `"materials"`, `"components"`, `"products"` i grup pozycji | | niepusta; żaden wpis dwa razy; każdy materiał przyjmuje jakiś magazyn | wszystkie trzy rodzaje | fixed | Co magazyn może przechowywać. | `decisions_rejected` |
| `warehouses.*.accepts.*.group` | identyfikator grupy | | grupa materiałów, komponentów lub produktów | wymagany we wpisie grupy | fixed | Grupa pozycji, którą magazyn przyjmuje, zapisana `{"group": "<identifier>"}`. | `decisions_rejected` |

### Trasy

W `routes.*.*` pierwsza `*` to magazyn, z którego trasa wychodzi, a druga to magazyn,
do którego dochodzi. Trasa łączy dwa różne magazyny, w jedną stronę.

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `routes.*.*.cost` | pieniądze | 4 | co najmniej 0 | wymagany | run | Koszt na przesuniętą sztukę. | `transfer_cost` |
| `routes.*.*.lead_time` | okresy | 0 | co najmniej 0 | wymagany | run | Okresy, jakie trwa przesunięcie; przy 0 dociera od razu. | `stock` |

### Grupy

| Ścieżka klucza | Typ | Granice | Wartość domyślna | Skutek |
| --- | --- | --- | --- | --- |
| `groups.*.kind` | identyfikator | nie `customer` ani `product` | wymagany | Dowolne słowo, takie jak `region`; obiekt jest najwyżej w jednej grupie każdego rodzaju. |
| `groups.*.defaults` | obiekt | tylko klucze, których używają jej członkowie | brak | Wartości, jakie grupa daje swoim członkom. |

| Ścieżka klucza | Członkowie, którzy jej używają | Klucze, które może dać |
| --- | --- | --- |
| `groups.*.defaults.items` | materiały, komponenty, produkty | `groups.*.defaults.items.space`, `groups.*.defaults.items.storage_cost`, `groups.*.defaults.items.salvage_value`, `groups.*.defaults.items.common_share` (tylko produkty) |
| `groups.*.defaults.catalogue` | materiały, dostawcy | `groups.*.defaults.catalogue.price`, `groups.*.defaults.catalogue.lead_time`, `groups.*.defaults.catalogue.max_quantity`, `groups.*.defaults.catalogue.punctuality`, `groups.*.defaults.catalogue.delay`, `groups.*.defaults.catalogue.completeness`, `groups.*.defaults.catalogue.acceptance`, `groups.*.defaults.catalogue.cancellation_fee`, `groups.*.defaults.catalogue.backfill_delay`, `groups.*.defaults.catalogue.express_lead_time`, `groups.*.defaults.catalogue.express_cost`, `groups.*.defaults.catalogue.min_quantity` |
| `groups.*.defaults.line_items` | komponenty, produkty, linie | `groups.*.defaults.line_items.time`, `groups.*.defaults.line_items.cost`, `groups.*.defaults.line_items.yield`, `groups.*.defaults.line_items.lead_time`, `groups.*.defaults.line_items.changeover_time`, `groups.*.defaults.line_items.changeover_cost` |
| `groups.*.defaults.customer_products` | produkty, klienci | `groups.*.defaults.customer_products.price`, `groups.*.defaults.customer_products.transport_cost`, `groups.*.defaults.customer_products.demand`, `groups.*.defaults.customer_products.demand_persistence`, `groups.*.defaults.customer_products.lead_time`, `groups.*.defaults.customer_products.patience`, `groups.*.defaults.customer_products.late_penalty`, `groups.*.defaults.customer_products.lost_sale_penalty` |
| `groups.*.defaults.customers` | klienci | `groups.*.defaults.customers.payment_terms` |
| `groups.*.defaults.lines` | linie | `groups.*.defaults.lines.capacity`, `groups.*.defaults.lines.wear_per_period`, `groups.*.defaults.lines.wear_per_hour`, `groups.*.defaults.lines.breakdown_chance`, `groups.*.defaults.lines.breakdown_loss`, `groups.*.defaults.lines.repair_cost`, `groups.*.defaults.lines.repair_time`, `groups.*.defaults.lines.repair_limit`, `groups.*.defaults.lines.overtime_hours`, `groups.*.defaults.lines.overtime_cost` |

- Klucz `defaults` ma typ, miejsca, granice i moment losowania klucza o tej samej
  nazwie w członku: `groups.*.defaults.catalogue.price` jest jak
  `suppliers.*.catalogue.*.price`, razem z `drawn`. Klucz stały można podać tylko jako
  stałą liczbę. Grupa nigdy nie daje rabatów.
- Członek bierze wartość w tej kolejności: wartość zapisana w nim; wartości domyślne
  jego grup, w kolejności, w jakiej je wymienia; wbudowana wartość domyślna. Wpis
  katalogu pyta grupy dostawcy, a potem grupy materiału; produkt klienta grupy
  klienta, a potem grupy produktu; wpis linii grupy linii, a potem grupy pozycji.
- Zakres dany przez grupę jest losowany osobno dla każdego członka.
- Grupa ma co najmniej jednego członka, a jej członkowie są jednego typu. Materiały,
  komponenty i produkty to trzy typy.
- Identyfikator grupy jest inny niż `materials`, `components`, `products`, `all`,
  `written` i `default`.

### Gotówka

| Ścieżka klucza | Typ | Miejsca | Granice | Wartość domyślna | Losowanie | Skutek | Zmienia |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cash.credit_limit` | pieniądze | 4 | co najmniej 0 | wymagany | fixed | Kwota L. Gotówka poniżej -L płaci odsetki od przekroczenia limitu, a zakup nie może zabrać gotówki, pomniejszonej o to, co są winne otwarte zamówienia u dostawców, poniżej -L. | `interest_paid`, `decisions_rejected` |
| `cash.credit_interest` | stopa | 4 | od 0 do 1 | wymagany | fixed | Część gotówki równej 0 lub większej zarabiana w okresie. | `interest_earned` |
| `cash.debit_interest` | stopa | 4 | od 0 do 1; co najmniej `credit_interest` | wymagany | fixed | Część gotówki poniżej 0, do -L, płacona w okresie. | `interest_paid` |
| `cash.overdraft_interest` | stopa | 4 | od 0 do 1; co najmniej `debit_interest` | wymagany | fixed | Część gotówki poniżej -L płacona w okresie. | `interest_paid` |
