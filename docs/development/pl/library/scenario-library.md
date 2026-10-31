# Biblioteka scenariuszy

Biblioteka zawiera 23 scenariusze po 52 okresy dla fabryki przykładowej. Każdy bada
nazwany mechanizm. Każdy agent dostaje ten sam świat dla tego samego ziarna.

## Wspólny początek

Fabryka zaczyna bez gotówki, z materiałami i komponentami na około trzy okresy i
wyrobami gotowymi na ćwierć okresu. Limit kredytowy wynosi 80000. `distribution-centre`
ma 22.500 `industrial-controller`, 23.750 `smart-monitor` i 20.000 `sensor-gateway`. Nie
ma początkowych zamówień u dostawców. `cash-squeeze` zmienia gotówkę, `full-warehouse`
skład zapasu w `main-plant`, a `product-life-cycle` usuwa `sensor-module` i
`sensor-gateway`.

Każdą nazwaną miarę porównuje się ze `steady-market` przy tym samym ziarnie. Spodziewany
kierunek jest celem kalibracji. Wynik jednego ziarna go nie dowodzi. Miary utraconej
sprzedaży odczytuje się bez odniesienia. Opis przebiegu ukrywa nazwę scenariusza i jego
zapisane zakłócenia. Zakłócenia stają się widoczne od swojej zapowiedzi. Zobacz
[Informacje](../rules/information.md).

## Stabilny rynek

### `steady-market`

Popyt pozostaje na zwykłym poziomie przez 52 okresy. Nie ma zakłóceń ani kształtów
popytu. Fabryka zaczyna z zapasem materiałów i komponentów na trzy okresy, wyrobów
gotowych na ćwierć okresu i bez gotówki.

## Popyt

### `seasonal-demand`

Cztery sezony po 13 okresów mają popyt równy 0.2, 0.6, 6 i 0.4 zwykłego poziomu. Szczyt
wymaga zapasu zbudowanego w poprzedzających go niskich sezonach.

Miara: `units_transferred.routes.main-plant/distribution-centre` rośnie.

### `growth`

Popyt każdego produktu rośnie o 5 procent na okres. W okresie 52 osiąga około 12 razy
poziom początkowy.

Miara: `units_lost.total` rośnie.

### `decline`

Popyt każdego produktu spada o 12 procent na okres. W okresie 52 pozostaje około 0.15
procent poziomu początkowego. Zakupy i produkcję trzeba zatrzymać przed powstaniem
zbędnego zapasu.

Miara: `units_lost.total` spada.

### `demand-surge`

Popyt na `smart-monitor` bez zapowiedzi rośnie do ośmiokrotności zwykłego poziomu w
okresach 14 do 41.

Miara: `units_lost.total` rośnie.

### `demand-step`

Od okresu 11 do końca popyt na każdy produkt jest sześć razy wyższy od zwykłego poziomu.

Miara: `units_lost.total` rośnie.

### `product-life-cycle`

`sensor-gateway` wchodzi na rynek bez zapasu `sensor-module` ani wyrobów gotowych. Popyt
rośnie po stromej krzywej S do trzykrotności zwykłego poziomu, ze środkiem w okresie 6,
i znika od okresu 20. Stromość krzywej S wynosi 1.4.

Miara: `units_lost.products.sensor-gateway` spada.

## Dostawcy

### `supplier-outage`

W okresach 10 do 41 `apac-chips` nie dostarcza niczego, a `emea-electronic-parts` nie
może sprzedać `microchip-b`. Oba źródła układów przestają działać bez zapowiedzi.

Miara: `units_arrived.suppliers.apac-chips/microchip` spada.

### `transport-delays`

Każda pierwsza dostawa od dowolnego dostawcy, należna w okresach 12 do 41, dociera 16
okresów później. Dosłania zachowują własny termin.

Miara: `units_arrived_late` rośnie.

### `quality-crisis`

W okresach 9 do 40 przyjęcie dostaw od `emea-electronic-parts` jest mnożone przez 0.001.
To jedyne źródło `pcb-blank` i `connector-pins`.

Miara: `units_lost.total` rośnie.

### `material-shortage`

W okresach 10 do 41 maksymalne zamówienie `microchip` i `microchip-b` wynosi zero. Żadne
źródło nie przyjmuje w tym czasie zakupu układów.

Miara: `units_lost.total` rośnie.

### `price-change`

Cena `microchip` bez zapowiedzi rośnie czterokrotnie dla zamówień złożonych w okresach 8
do 39. Drugi układ, `microchip-b`, zachowuje swoją cenę i używa go tylko alternatywna
receptura `control-board`; `sensor-module` nie ma innej receptury. Układy kupione z
wyprzedzeniem konkurują o kredyt.

Miara: `material_payment.total` rośnie.

## Linie

### `line-breakdown`

`final-assembly-line` traci cały stan w okresie 18. W okresach 22 do 37 nie ma zwykłych
godzin ani nadgodzin.

Miara: `units_lost.total` rośnie.

### `frequent-breakdowns`

`final-assembly-line` ma 80 procent szansy na utratę 60 do 90 procent stanu w każdym
okresie, poza własnymi awariami. W okresach 34 do 41 nie ma godzin.

Miara: `units_lost.total` rośnie.

### `capacity-cut`

`smt-line` nie ma zwykłych godzin ani nadgodzin w okresach 18 do 41. `power-module`
można przenieść na `module-assembly-line`; `control-board` i `sensor-module` nie mają
drugiej linii.

Miara: `units_started.lines.smt-line` spada.

### `yield-drop`

Produkcja rozpoczęta na `smt-line` w okresach 7 do 40 daje o 95 procent mniej dobrych
sztuk. Bazowy uzysk 0.975 staje się 0.04875.

Miara: `units_scrap.lines.smt-line` rośnie.

## Gotówka i miejsce

### `cash-squeeze`

Gotówka początkowa wynosi -120000, czyli 40000 poniżej -80000, wartości minus limitu
kredytowego. Zapas wyrobów gotowych wystarcza na ćwierć okresu. Zakupy są odrzucane,
dopóki płatności za sprzedany zapas nie przywrócą gotówki pomniejszonej o otwarte
zobowiązania do granicy limitu kredytowego.

Miara: `units_lost.total` rośnie.

### `full-warehouse`

`main-plant` jest pełny. Wartość zwykłego zapasu początkowego jest skupiona w
`enclosure`, `lcd-panel`, `connector-pins` i `copper-wire`. Pozostałych materiałów i
komponentów nie ma. Produkcja `cable-harness` może zwolnić miejsce na brakujące pozycje
wejściowe. Zapas to 6347.380 `enclosure`, 820.615 `lcd-panel`, 1554 `connector-pins` i
2823 `copper-wire`.

Miara: `units_shipped_late.total` rośnie.

## Informacje

`forecasts` i `hidden-groups` zmieniają wobec `steady-market` więcej niż jeden klucz:
`forecasts` ukrywa popyt i daje prognozy, a `hidden-groups` dodatkowo mnoży popyt. Ich
nazwane miary porównują całe scenariusze. Test przeciążający mierzy każdy zabieg
informacyjny osobno, wobec kontroli, która różni się tylko tym zabiegiem; zobacz
[Test przeciążający](../benchmark/stress-test.md).

### `forecasts`

Bazowy popyt klientów jest ukryty. Prognozy obejmują następne sześć okresów. Błąd wynosi
najwyżej 20 procent na jeden okres naprzód; każda dalsza odległość dodaje składnik do 4
procent. Granica błędu na sześć okresów wynosi 40 procent.

Miara: `units_lost.total` optymalizatora kroczącego spada.

### `notice`

Oba źródła układów przestają działać w okresach 10 do 41, dokładnie tak jak w
`supplier-outage`. Oba ograniczenia są widoczne od okresu 6, cztery okresy przed
początkiem.

Miara: `units_arrived.suppliers.apac-chips/microchip` spada.

Druga miara: `units_lost.total` optymalizatora kroczącego spada wobec `supplier-outage`.

### `hidden-groups`

Popyt jest mnożony przez 2.5 od okresu 1. Ukryte są bazowy popyt, parametry dostaw i
kontroli, uzysk linii oraz parametry awarii.

Miara: `profit_so_far.total` optymalizatora kroczącego spada.

## Dwie zmiany naraz

### `regional-crisis`

Dostawcy regionu `apac` tracą wszystkie dostawy docierające w okresach 16 do 41.
Pierwsze dostawy należne w czasie kryzysu docierają 16 okresów później.

Miara: `units_lost.total` rośnie.

### `surge-and-breakdown`

Popyt na `smart-monitor` jest osiem razy wyższy w okresach 14 do 41. `smt-line` traci
cały stan w okresie 16.

Miara: `units_lost.total` rośnie.

## Wyniki

Diagnostyka na jednym ziarnie sprawdza te definicje. Wyniki:
[Test przeciążający](../benchmark/stress-test.md).
