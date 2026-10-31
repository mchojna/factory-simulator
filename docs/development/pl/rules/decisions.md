# Decyzje

Agent działa przez sześć rodzajów decyzji. Każda decyzja to jeden obiekt JSON z kluczem
`kind`: wysyłka (`ship`), anulowanie (`cancel`), przesunięcie (`transfer`), naprawa
(`repair`), produkcja (`produce`) albo zakup (`buy`). Program badania wysyła decyzje
jednego okresu razem, w jednym zgłoszeniu. Odrzucona decyzja wraca z powodem i liczbami,
które za nim stoją. Decyzje można najpierw sprawdzić, bez zmiany przebiegu.

## Sześć decyzji

| Decyzja | Co robi |
| --- | --- |
| Wysyłka | Wysyła ilość otwartego zamówienia klienta z magazynu do klienta. |
| Anulowanie | Kończy ilość zamówienia u dostawcy, która nie dotarła, za opłatę za sztukę, albo kończy plan, bez opłaty. |
| Przesunięcie | Przenosi ilość pozycji trasą z jednego magazynu do innego. |
| Naprawa | Przywraca część stanu linii. |
| Produkcja | Rozpoczyna ilość pozycji na linii według receptury, teraz albo w późniejszym okresie, w zwykłych godzinach albo w nadgodzinach. |
| Zakup | Składa zamówienie u dostawcy na ilość materiału, do magazynu, jako zwykłe albo ekspresowe zamówienie. |

Przykłady poniżej używają fabryki przykładowej. Znaczenie każdego powodu jest w części
[Powody odrzucenia](#powody-odrzucenia).

### Wysyłka

```json
{"kind": "ship", "order": "order-1-1", "quantity": 10.000, "warehouse": "distribution-centre"}
```

- `order`: identyfikator otwartego zamówienia klienta.
- `quantity`: liczba sztuk do wysłania. Może być mniejsza niż otwarta ilość. Reszta
  zamówienia zostaje otwarta.
- `warehouse`: magazyn, z którego wychodzą sztuki. Można go pominąć w manifeście z
  jednym magazynem.

Powody, w kolejności sprawdzania: `unknown_order`, `unknown_warehouse`,
`over_open_quantity`, `not_enough_stock`.

Po przyjęciu zapas spada, przychód jest zarobiony, a koszt transportu zapłacony. Klient
płaci od razu albo później, według swoich warunków płatności. Zobacz
[Klienci i popyt](customers-and-demand.md).

### Anulowanie

```json
{"kind": "cancel", "order": "buy-1-6", "quantity": 100.000}
```

- `order`: identyfikator otwartego zamówienia u dostawcy (`buy-...`) albo planu
  (`make-...`).
- `quantity`: sztuki zamówienia u dostawcy do anulowania. Anulowanie planu nie ma
  `quantity`.

Powody, w kolejności sprawdzania: `unknown_order`, `wrong_quantity`,
`over_open_quantity`, `below_min_quantity`, `below_discount_tier`.

- Anulowanie, które zostawia otwartą część zamówienia u dostawcy, musi zostawić
  zamówioną ilość pomniejszoną o wszystkie jej anulowania co najmniej na poziomie
  minimalnej ilości materiału i ilości progu rabatu, według którego wyceniono
  zamówienie. Zamówień ze stanu początkowego nie sprawdza się względem minimalnej
  ilości.
- Zamówienie zachowuje swoją cenę za sztukę.
- Anulowanie zamówienia u dostawcy płaci opłatę za anulowanie z katalogu za każdą
  anulowaną sztukę. Zamówienie bez otwartej ilości zostaje zamknięte.

Zobacz [Dostawcy](suppliers.md). Anulowanie planu opisuje część [Plany](#plany).

### Transfer

```json
{"kind": "transfer", "item": "industrial-controller", "quantity": 30.000, "source": "main-plant", "destination": "distribution-centre"}
```

- `item`: pozycja do przeniesienia.
- `quantity`: sztuki do przeniesienia.
- `source` i `destination`: magazyny na dwóch końcach trasy.

Powody, w kolejności sprawdzania: `unknown_route`, `not_accepted`, `not_enough_stock`,
`transferred_this_period`, `not_enough_space`.

Po przyjęciu zapas w `source` spada od razu, a koszt trasy za sztukę jest zapłacony.
Sztuki docierają do `destination` po czasie realizacji trasy. Z `main-plant` do
`distribution-centre` to 1 okres za 0.8 za sztukę. Zobacz
[Magazyny i trasy](warehouses-and-routes.md).

### Naprawa

```json
{"kind": "repair", "line": "smt-line", "amount": 0.0500}
```

- `line`: linia do naprawy.
- `amount`: stan do przywrócenia, powyżej 0 i z najwyżej 4 miejscami po przecinku.

Powody, w kolejności sprawdzania: `unknown_line`, `over_repair_limit`,
`over_full_condition`, `not_enough_hours`.

Po przyjęciu naprawa wykorzystuje `amount * repair_time` godzin linii w tym okresie i
płaci od razu `amount * repair_cost`. Stan rośnie przy zamknięciu okresu. Na `smt-line`
naprawa o 0.05 wykorzystuje 0.05 x 16 = 0.8 godziny i kosztuje 0.05 x 2500 = 125. Zobacz
[Produkcja](production.md).

### Produkcja

```json
{"kind": "produce", "line": "smt-line", "item": "control-board", "quantity": 200.000, "recipe": "standard", "overtime": false}
```

- `line`: linia, która wytwarza pozycję.
- `item`: komponent lub produkt do wytworzenia.
- `quantity`: sztuki do rozpoczęcia.
- `recipe`: jedna z receptur pozycji. Pominięta, oznacza recepturę domyślną pozycji.
- `overtime`: true, aby wytworzyć sztuki w nadgodzinach. Pominięte, oznacza false.
- `start`: okres, w którym zaczyna się produkcja. Pominięty, oznacza bieżący okres.
  Późniejszy okres tworzy plan; zobacz [Plany](#plany).

Powody, w kolejności sprawdzania: `start_outside_horizon`, `unknown_line`,
`line_cannot_make_item`, `unknown_recipe`, `not_enough_hours`, `not_enough_input`,
`not_enough_space`.

Po przyjęciu pozycje wejściowe od razu opuszczają zapas magazynu linii, godziny są
wykorzystane, a koszt produkcji zapłacony. Linia ustawiona na inną pozycję albo
nieustawiona na żadną najpierw się przezbraja, za godziny i koszt przezbrojenia pozycji.
W przykładzie, w okresie 1 scenariusza `steady-market`, `smt-line` nie jest ustawiona na
żadną pozycję. 400 `microchip`, 200 `pcb-blank` i 200 `passive-kit` opuszczają zapas,
linia wykorzystuje 2 + 200 x 0.14 = 30 godzin, a fabryka płaci 300 + 200 x 4.9 = 1280.
Zobacz [Produkcja](production.md).

### Zakup

```json
{"kind": "buy", "supplier": "apac-chips", "material": "microchip", "quantity": 500.000, "warehouse": "main-plant", "express": true}
```

- `supplier`: dostawca, u którego się zamawia.
- `material`: materiał z katalogu dostawcy.
- `quantity`: sztuki do zamówienia.
- `warehouse`: magazyn, do którego idzie dostawa. Można go pominąć w manifeście z jednym
  magazynem.
- `express`: true dla zamówienia ekspresowego: krótszy czas realizacji za dodatkową cenę
  za sztukę. Pominięte, oznacza false.

Powody, w kolejności sprawdzania: `unknown_supplier`, `not_in_catalogue`,
`unknown_warehouse`, `not_accepted`, `no_express`, `below_min_quantity`,
`over_max_quantity`, `not_enough_space`, `over_credit_limit`.

Po przyjęciu zostaje złożone zamówienie u dostawcy. Jego cena za sztukę jest ustalona w
chwili złożenia. Teraz nic się nie płaci. Za przyjęte sztuki fabryka płaci, gdy
docierają. `apac-chips` dostarcza `microchip` w czasie realizacji wylosowanym od 3 do 5
okresów (4 przy ziarnie 0) albo, jako zamówienie ekspresowe, w 2 okresy za 1.625 więcej
za sztukę. Zobacz [Dostawcy](suppliers.md) oraz [Gotówka i zysk](cash-and-profit.md).

## Zgłoszenie

Program badania wysyła zgłoszenie na `POST /api/v1/runs/{id}/decisions` jako
`{"period": 7, "decisions": [...]}`, z numerem bieżącego okresu.

- Zgłoszenie może zawierać dowolną liczbę decyzji dowolnych rodzajów, w dowolnej
  kolejności. Pusta lista jest poprawna: okres zamyka się bez decyzji.
- Każda decyzja dostaje identyfikator `<period>-<n>`, gdzie n to jej miejsce na liście,
  liczone od 1. To, co tworzy przyjęta decyzja, ma ten sam okres i to samo n:
  `ship-7-1`, `cancel-7-2`, `transfer-7-3`, `repair-7-4`, `make-7-5`, `buy-7-6`.
- Liczba to liczba JSON albo tekst dziesiętny. Ilość jest powyżej 0 i ma najwyżej 3
  miejsca po przecinku.
- Zgłoszenie jest odrzucone w całości, a przebieg zostaje w swoim okresie, gdy podaje
  inny okres niż bieżący, ma nieznany klucz, wartość złego typu, ilość lub wielkość
  naprawy, która nie jest powyżej 0 albo ma za dużo miejsc po przecinku, albo wysyłkę
  lub zakup bez `warehouse` w manifeście z kilkoma magazynami. Zapis przebiegu
  przechowuje każde takie odrzucone zgłoszenie jako interakcję, osobno od przebiegu.
- Zapis przebiegu i wyniki decyzji podają decyzje uzupełnione o wartości domyślne.

## Kolejność wykonania

Decyzje są wykonywane według rodzaju: najpierw wszystkie wysyłki, potem wszystkie
anulowania, przesunięcia, naprawy, produkcje i zakupy. W obrębie jednego rodzaju są
wykonywane w kolejności zgłoszenia. Plany, które zaczynają się w tym okresie, są
wykonywane jako pierwsze spośród decyzji produkcji, według identyfikatora. Każdą decyzję
sprawdza się względem stanu przebiegu, jaki zostawiają decyzje przyjęte przed nią.

Ta kolejność ma takie skutki:

- Wysyłka używa tylko zapasu, który jest na początku wykonywania decyzji. Przesunięcie,
  produkcja ani zakup z tego samego okresu nie dodają niczego, czego mogłaby użyć.
- Przesunięcie używa tylko zapasu, który jest na początku przesunięć.
- Miejsce, które zwalniają anulowania, liczy się dla późniejszych decyzji, a zakup nie
  liczy już tego, ile kosztowałyby anulowane sztuki.
- Godziny napraw są zabierane przed każdą godziną produkcji w okresie.
- Sprawdzenie limitu kredytowego widzi gotówkę po każdej innej decyzji okresu.
- Planu nie można anulować w okresie, w którym powstał.

## Wykonana w całości albo odrzucona w całości

- Decyzja, która przechodzi każde sprawdzenie, jest wykonana w całości.
- Decyzja, która nie przechodzi sprawdzenia, jest odrzucona w całości. Dostaje powód
  pierwszego sprawdzenia, którego nie przechodzi, z liczbami, które za nim stoją, a stan
  się nie zmienia.
- Symulator nigdy nie zmniejsza ilości, aby decyzja się zmieściła.
- Tylko zakup jest odrzucany z braku gotówki. Każda inna decyzja jest wykonana, nawet
  gdy zabiera gotówkę poniżej 0 albo poniżej minus limit kredytowy.

Wyniki decyzji okresu wracają w obserwacji następnego okresu, w kolejności wykonania.
Wynik przyjętej decyzji zawiera `decision_id`, `decision`, `accepted: true` i
`reference`, czyli identyfikator tego, co utworzyła. Wynik odrzuconej decyzji zawiera
`decision_id`, `decision`, `accepted: false`, `reason` oraz, dla większości powodów,
`asked` i `available`. Na przykład zakup 2500 `microchip` od `apac-chips`, który
sprzedaje najwyżej 2000 na okres, jest odrzucony z `over_max_quantity`, `asked` 2500 i
`available` 2000.

## Powody odrzucenia

`asked` i `available` są w jednostce sprawdzenia: w sztukach, godzinach, stanie, miejscu
albo pieniądzach. Myślnik oznacza, że wynik decyzji nie ma takiej liczby.

| Powód | Decyzje | Odrzucona, gdy | `asked` | `available` |
| --- | --- | --- | --- | --- |
| `unknown_order` | wysyłka, anulowanie | Zamówienie klienta lub zamówienie u dostawcy nie istnieje albo jest zamknięte, albo plan nie istnieje lub już został wykonany. | - | - |
| `unknown_warehouse` | wysyłka, zakup | Magazyn nie istnieje. | - | - |
| `unknown_route` | przesunięcie | Żadna trasa nie prowadzi z `source` do `destination`. | - | - |
| `unknown_line` | naprawa, produkcja | Linia nie istnieje. | - | - |
| `unknown_supplier` | zakup | Dostawca nie istnieje. | - | - |
| `unknown_recipe` | produkcja | Receptura nie jest jedną z receptur pozycji. | - | - |
| `not_in_catalogue` | zakup | Materiału nie ma w katalogu dostawcy. | - | - |
| `line_cannot_make_item` | produkcja | Linia nie wytwarza pozycji. | - | - |
| `not_accepted` | przesunięcie, zakup | Pozycja nie istnieje albo magazyn jej nie przyjmuje. Wynik decyzji podaje `item`. | - | - |
| `wrong_quantity` | anulowanie | Plan jest podany z ilością albo zamówienie u dostawcy bez ilości. | - | - |
| `start_outside_horizon` | produkcja | `start` jest przed bieżącym okresem albo po horyzoncie. | - | - |
| `no_express` | zakup | Zamówienie jest ekspresowe, a dostawca nie ma ekspresowego czasu realizacji dla materiału. | - | - |
| `over_open_quantity` | wysyłka, anulowanie | Ilość jest większa niż otwarta ilość zamówienia. | ilość | otwarta ilość |
| `not_enough_stock` | wysyłka, przesunięcie | Ilość jest większa niż zapas pozycji w magazynie. | ilość | zapas |
| `transferred_this_period` | przesunięcie | Ilość jest większa niż zapas pozycji w magazynie źródłowym minus sztuki, które przesunięcia z czasem realizacji 0 wniosły tam w tym okresie. | ilość | zapas minus sztuki wniesione przez przesunięcia z czasem realizacji 0 |
| `over_repair_limit` | naprawa | Wielkość naprawy razem z naprawami linii przyjętymi wcześniej w okresie jest większa niż limit naprawy linii. | wielkość naprawy | limit naprawy minus przyjęte naprawy |
| `over_full_condition` | naprawa | Wielkość naprawy razem z naprawami linii przyjętymi wcześniej w okresie podniosłaby stan powyżej 1. | wielkość naprawy | 1 minus stan minus przyjęte naprawy |
| `not_enough_hours` | naprawa, produkcja | Potrzebne godziny są większe niż godziny, które linii zostały w okresie w ramach ograniczeń z części [Godziny i stan](production.md#godziny-i-stan). Produkcja w nadgodzinach najpierw sprawdza godziny przezbrojenia względem zwykłych godzin, potem godziny produkcji względem nadgodzin. | potrzebne godziny | najmniej godzin, które zostały w ramach obowiązujących ograniczeń |
| `not_enough_input` | produkcja | Brakuje pozycji wejściowej w magazynie linii. Wynik decyzji podaje w `item` pierwszą brakującą pozycję według identyfikatora. | potrzebna ilość wejściowa | jej zapas |
| `not_enough_space` | przesunięcie, produkcja, zakup | Miejsce zajęte w magazynie po decyzji byłoby większe niż jego pojemność; zobacz [Otwarte zamówienia zajmują swoje miejsce](warehouses-and-routes.md#otwarte-zamówienia-zajmują-swoje-miejsce). | miejsce, które dodaje decyzja | pojemność minus miejsce zajęte wcześniej |
| `below_min_quantity` | zakup, anulowanie | Zakup jest poniżej minimalnej ilości albo anulowanie zostawia zamówienie poniżej niej. | ilość albo ilość, która zostaje po anulowaniu | minimalna ilość |
| `below_discount_tier` | anulowanie | Anulowanie zostawia zamówienie poniżej ilości progu rabatu, według którego je wyceniono. | anulowana ilość | ilość, która została przed anulowaniem, minus ilość progu |
| `over_max_quantity` | zakup | Ilość razem z zamówieniami materiału u dostawcy przyjętymi wcześniej w okresie jest większa niż największa ilość, jaką dostawca przyjmuje na okres, obniżona przez aktywny niedobór materiału. | ilość | największa ilość minus zamówienia przyjęte wcześniej |
| `over_credit_limit` | zakup | Gotówka minus to, co otwarte zamówienia u dostawców jeszcze są winne, minus koszt tego zakupu spadłaby poniżej minus limit kredytowy. | ilość razy cena za sztukę | gotówka plus limit kredytowy minus to, co są winne otwarte zamówienia; może być poniżej 0 |

## Sprawdzenie bez wykonania

`POST /api/v1/runs/{id}/checks` przyjmuje tę samą treść co zgłoszenie. Jego odpowiedź to
`{"outcomes": [...]}`: wynik, jaki miałaby każda decyzja, gdyby zgłosić ją teraz.

- Wyniki, w kolejności wykonania, są takie, jakie daje zgłoszenie tych samych decyzji w
  tym samym okresie. Sprawdzenie niczego nie zmienia w przebiegu.
- Sprawdzenie można zrobić w okresie dowolnie wiele razy.
- Zapis przebiegu przechowuje każde sprawdzenie jako interakcję, osobno od przebiegu.
- Sprawdzenie, które podaje inny okres albo łamie formę zgłoszenia, jest odrzucone tak
  jak zgłoszenie. Zakończony przebieg nie przyjmuje sprawdzeń.

## Plany

Plan to decyzja produkcji ze `start` po bieżącym okresie, na przykład
`{"kind": "produce", "line": "smt-line", "item": "control-board", "quantity": 200.000, "start": 3}`.

- Gdy plan powstaje, obowiązują tylko cztery sprawdzenia: `start` mieści się w
  horyzoncie, linia istnieje, linia wytwarza pozycję, a receptura jest jedną z receptur
  pozycji. Plan, który je przechodzi, jest przyjęty z `reference` takim jak `make-1-5`.
- Plan nie zajmuje godzin, pozycji wejściowych ani miejsca, nic nie płaci i nie zmienia
  pozycji, na którą linia jest ustawiona.
- Każda obserwacja podaje każdy nierozpoczęty jeszcze plan z uzupełnionymi wartościami
  domyślnymi.
- Anulowanie bez ilości kończy plan, do jego okresu początkowego włącznie, bez opłaty:
  `{"kind": "cancel", "order": "make-1-5"}`.
- W swoim okresie początkowym plan przechodzi przez każde sprawdzenie produkcji względem
  stanu w tej chwili, tak jak decyzja podjęta w tym okresie. Plan, który nie przechodzi
  sprawdzenia, jest odrzucony ze swoim powodem. Plan, który przechodzi, staje się
  produkcją o tym samym identyfikatorze.
- Jego wynik decyzji przychodzi z wynikami jego okresu początkowego, jako pierwszy na
  liście. Zawiera `decision_id` i `decision` decyzji, która go utworzyła: `1-5` dla
  `make-1-5`.
- Jego okres początkowy jest okresem początkowym produkcji, dla uzysku i dla aktywnego
  spadku uzysku.

## Przykład

Przebieg `steady-market` na fabryce przykładowej z ziarnem 0. W okresie 1 agent zgłasza
sześć decyzji, po jednej każdego rodzaju, w kolejności: zakup, produkcja, naprawa,
przesunięcie, anulowanie i wysyłka. Sprawdzenie tych sześciu decyzji daje te same wyniki
decyzji co zgłoszenie. Symulator wykonuje decyzje według rodzaju, więc wyniki decyzji
wracają w odwrotnej kolejności:

| Decyzja | Wynik decyzji |
| --- | --- |
| `1-6`: wysyłka 22.5 sztuk zamówienia `order-1-1` z `distribution-centre` | Przyjęta jako `ship-1-6`. |
| `1-5`: anulowanie 100 sztuk zamówienia `buy-1-1` | Odrzucona z powodem `unknown_order`: anulowania są wykonywane przed zakupami, więc `buy-1-1` jeszcze nie istnieje. |
| `1-4`: przesunięcie 30 `industrial-controller` z `main-plant` do `distribution-centre` | Odrzucona z powodem `not_enough_stock`, `asked` 30 i `available` 0. |
| `1-3`: naprawa 0.05 stanu `smt-line` | Odrzucona z powodem `over_full_condition`, `asked` 0.05 i `available` 0: stan linii wynosi 1. |
| `1-2`: produkcja 200 `control-board` na `smt-line` | Przyjęta jako `make-1-2`. |
| `1-1`: zakup 500 `microchip` od `apac-chips` do `main-plant` | Przyjęta jako `buy-1-1`. |

- Za wysyłkę fabryka od razu płaci transport 22.5 x 3.84 x 0.85 = 73.44. Przychód z
  niej, 22.5 x 152 = 3420, `equipment-maker` płaci w okresie 7.
- Za produkcję fabryka płaci 300 za przezbrojenie i 200 x 4.9 = 980. Przy zamknięciu
  okresu 1 do zapasu wchodzi 193.88 dobrych sztuk, a 6.12 sztuki to braki.
- Zamówienie u dostawcy `buy-1-1` ma cenę za sztukę 6.3762 i jest spodziewane w
  okresie 5. W okresie 1 fabryka nic za nie nie płaci.
- Trzy odrzucone decyzje niczego nie zmieniają. Po kosztach składowania i odsetkach
  gotówka przy zamknięciu okresu 1 wynosi -1828.26249.
