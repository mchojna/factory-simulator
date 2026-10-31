# Miary i zapis przebiegu

Zysk to jedyna liczba, która ocenia przebieg. Obok niego symulator zapisuje w każdym
okresie 61 miar, dla całej fabryki oraz dla każdego klienta, produktu, dostawcy, linii,
magazynu, trasy i grupy.

## Wynik przebiegu

`GET /api/v1/runs/{id}/result` daje wynik przebiegu, gdy przebieg jest zakończony:

| Klucz | Zawiera |
| --- | --- |
| `seed` | Ziarno przebiegu. |
| `periods` | Liczbę okresów, czyli horyzont. |
| `profit` | Zysk przebiegu. |
| `cash_at_start`, `cash_at_end` | Gotówkę przed okresem 1 i przy zamknięciu ostatniego okresu. |
| `receivables` | Należności wciąż otwarte na końcu. |
| `terms` | Każdy składnik zysku: `revenue`, każdy koszt, `interest_paid`, `interest_earned`, `late_penalty`, `lost_sale_penalty` i `salvage`. Koszty są liczbami dodatnimi. |
| `measures` | Każdą miarę całego przebiegu, według klucza, potem według nazwy. |

Zysk równa się `cash_at_end - cash_at_start + receivables + salvage`; zobacz
[Gotówka i zysk](../rules/cash-and-profit.md). Przebieg `steady-market` na fabryce
przykładowej z ziarnem 7 i bez decyzji kończy się z `cash_at_start` 0, `cash_at_end`
-736765.4409, `receivables` 0 i `salvage` 27434.2103. Jego zysk to -736765.4409 - 0 +
0 + 27434.2103 = -709331.2306.

## Przepływy, poziomy i stosunki

Każda miara jest jednego z trzech rodzajów:

- Przepływ liczy, co stało się w okresie, na przykład wysłane sztuki. W całym przebiegu
  się go sumuje.
- Poziom to wartość przy zamknięciu okresu, na przykład gotówka lub zapas. W całym
  przebiegu to jego wartość przy zamknięciu ostatniego okresu.
- Stosunek dzieli dwie sumy narastające, od okresu 1 do danego okresu, na przykład
  sztuki wysłane na czas przez sztuki wysłane. W całym przebiegu to jego wartość w
  ostatnim okresie. Stosunek z mianownikiem 0 ma wartość `null`. Każdy stosunek i każda
  średnia jest zaokrąglona połówkowo do parzystej do 12 miejsc po przecinku.

## Klucze

| Klucz | Miary |
| --- | --- |
| `total` | Całej fabryki. |
| `customers.<c>` | Jednego klienta. |
| `products.<p>` | Jednego produktu. |
| `pairs.<c>/<p>` | Jednego klienta i jednego produktu. |
| `warehouses.<w>` | Jednego magazynu. |
| `warehouses.<w>/<i>` | Jednej pozycji w jednym magazynie. |
| `suppliers.<s>/<m>` | Jednego materiału od jednego dostawcy. |
| `lines.<l>` | Jednej linii. |
| `lines.<l>/<i>` | Jednej pozycji na jednej linii. |
| `routes.<from>/<to>` | Jednej trasy. |
| `groups.<g>` | Jednej grupy. |
| `reasons.<reason>` | Jednego powodu odrzucenia, tylko dla `decisions_rejected`. |

- W wyniku przebiegu i w `GET /api/v1/runs/{id}/periods` miary są zagnieżdżone według
  pierwszej części klucza: `measures.total.service`,
  `measures.customers["retail-chain"].service`,
  `measures.pairs["retail-chain/smart-monitor"].service`.
- Każda miara klienta, produktu, dostawcy i materiału, linii lub pozycji jest też
  przechowywana dla grupy, pod `groups.<g>`. Zobacz [Grupy](../rules/groups.md).

## Miary

### Pieniądze

| Miara | Rodzaj | Klucze | Liczy |
| --- | --- | --- | --- |
| `revenue` | przepływ | total, customers, products, pairs | Cenę wysłanych sztuk, zapłaconych lub nie. |
| `material_payment` | przepływ | total | Koszt przyjętych sztuk zamówień u dostawców. |
| `production_cost` | przepływ | total | Koszt rozpoczętej produkcji. |
| `overtime_cost` | przepływ | total, lines | Koszt nadgodzin. |
| `changeover_cost` | przepływ | total, lines | Koszt przezbrojeń. |
| `repair_cost` | przepływ | total | Koszt napraw. |
| `transport_cost` | przepływ | total, warehouses | Transport wysyłek, przy magazynie, z którego wychodzą. |
| `transfer_cost` | przepływ | total, routes | Koszt przesunięć, w okresie wysłania przesunięcia. |
| `storage_cost` | przepływ | total, warehouses | Składowanie zapasu oraz przesunięć w drodze, przy ich magazynie docelowym. |
| `cancellation_fee` | przepływ | total, suppliers | Opłaty za anulowane części zamówień u dostawców. |
| `interest_paid`, `interest_earned` | przepływ | total | Odsetki od gotówki poniżej 0 i od gotówki równej 0 lub wyższej. |
| `late_penalty` | przepływ | total, customers, products, pairs | Kary za sztuki jeszcze niewysłane, w każdym okresie od okresu terminu poza tym, w którym zamówienie przepada. |
| `lost_sale_penalty` | przepływ | total, customers, products, pairs | Kary za utraconą sprzedaż. |
| `cash` | poziom | total | Gotówkę przy zamknięciu. |
| `profit_so_far` | poziom | total | Gotówkę przy zamknięciu minus gotówkę na początku, plus należności przy zamknięciu. |
| `receivables` | poziom | total, customers | Należności otwarte przy zamknięciu. |
| `periods_below_credit_limit` | przepływ | total | 1 w okresie, w którym gotówka po odsetkach jest poniżej minus limitu kredytowego. |

- Każdy koszt jest liczbą dodatnią. Płatności klientów nie mają własnej miary: `revenue`
  liczy wysyłki.
- `profit_so_far` pomija wartość odzysku zapasu.

### Klienci

| Miara | Rodzaj | Klucze | Liczy |
| --- | --- | --- | --- |
| `units_ordered` | przepływ | total, customers, products, pairs | Sztuki złożonych zamówień klientów. Zamówienia ze stanu początkowego liczą się w okresie 1. |
| `units_shipped` | przepływ | total, customers, products, pairs | Wysłane sztuki. |
| `units_shipped_on_time` | przepływ | total, customers, products, pairs | Sztuki wysłane w okresie terminu ich zamówienia lub wcześniej. |
| `units_shipped_late` | przepływ | total, customers, products, pairs | Sztuki wysłane po okresie terminu ich zamówienia. |
| `units_lost` | przepływ | total, customers, products, pairs | Sztuki utraconej sprzedaży. |
| `units_past_due` | przepływ | total, customers, products, pairs | Pełną ilość zamówień, których okresem terminu jest dany okres, liczoną na jego zamknięciu. |
| `units_past_due_on_time` | przepływ | total, customers, products, pairs | Sztuki tych zamówień wysłane na czas, liczone na tym samym zamknięciu. |
| `service` | stosunek | total, customers, products, pairs | `units_past_due_on_time` przez `units_past_due`: ze sztuk zamówień, których okres terminu minął, część wysłana na czas. |
| `on_time_share` | stosunek | total, customers, products, pairs | `units_shipped_on_time` przez `units_shipped`: z wysłanych sztuk, część wysłana na czas. |
| `orders_in_full_on_time_share` | stosunek | total, customers, products, pairs | Z zamkniętych zamówień, część wysłana w całości do okresu terminu. |
| `mean_lateness` | stosunek | total, customers, products, pairs | Okresy spóźnienia razy sztuki, przez sztuki wysłane z opóźnieniem: o ile średnio spóźnia się spóźniona sztuka. |

- `service` liczy zamówienie, gdy minie jego okres terminu, wysłane lub nie. Agent,
  który nic nie wysyła, ma `service` 0. `on_time_share` liczy tylko wysłane sztuki, więc
  gdy nic nie wysłano, ma wartość `null`. Poziom realizacji, czyli `units_shipped` przez
  `units_ordered`, nie jest miarą zapisu przebiegu.
- Każda utracona sprzedaż to zdarzenie `lost_sale` z `quantity`, `amount` i `at_end`.
  `at_end` to true, gdy zamówienie przepada przez koniec przebiegu, zanim skończy się
  jego cierpliwość, a false, gdy nadszedł ostatni okres cierpliwości.

### Linie

| Miara | Rodzaj | Klucze | Liczy |
| --- | --- | --- | --- |
| `units_started` | przepływ | lines, lines z pozycją | Rozpoczęte sztuki, w okresie rozpoczęcia. |
| `units_good` | przepływ | lines, lines z pozycją | Dobre sztuki, w okresie gotowości. |
| `units_scrap` | przepływ | lines, lines z pozycją | Braki, w okresie gotowości. |
| `hours_available` | przepływ | lines | Zwykłe godziny, które linia ma w okresie: zdolność razy cięcie razy stan, zaokrąglone w dół do 3 miejsc po przecinku, tak jak pokazuje je obserwacja. |
| `regular_hours` | przepływ | lines | Zwykłe godziny produkcji. |
| `overtime_hours` | przepływ | lines | Nadgodziny. |
| `repair_hours` | przepływ | lines | Godziny naprawy. |
| `changeover_hours` | przepływ | lines | Godziny przezbrojeń. |
| `changeovers` | przepływ | lines | Przezbrojenia, także te, których czas i koszt wynoszą 0. |
| `breakdowns` | przepływ | lines | Awarie. |
| `condition` | poziom | lines | Stan przy zamknięciu. |
| `utilisation` | stosunek | lines | Zwykłe godziny produkcji plus godziny przezbrojeń przez zdolność linii, obie sumowane od okresu 1. Godziny napraw i nadgodziny nie liczą się w żadnej; zdolność liczy się w całości przy cięciu zdolności. |

### Dostawcy

| Miara | Rodzaj | Klucze | Liczy |
| --- | --- | --- | --- |
| `units_ordered_from_suppliers` | przepływ | suppliers | Sztuki złożonych zamówień u dostawców. |
| `units_arrived` | przepływ | suppliers | Sztuki, które dotarły. |
| `units_accepted` | przepływ | suppliers | Sztuki, które dotarły i przeszły kontrolę. |
| `units_rejected_at_inspection` | przepływ | suppliers | Sztuki, które dotarły, nie przeszły kontroli i zostały zwrócone. |
| `units_lost_in_delivery` | przepływ | suppliers | Utracone sztuki: brakująca część dostawy bez dosłania oraz część, którą wstrzymuje przestój dostawcy. |
| `units_cancelled` | przepływ | suppliers | Anulowane sztuki. |
| `units_arrived_late` | przepływ | suppliers | Sztuki, które dotarły po okresie złożenia plus użyty czas realizacji. Każda sztuka dosłania liczy się jako spóźniona. Początkowe zamówienie u dostawcy dociera w zapisanym okresie przybycia i nigdy nie liczy się jako spóźnione. |

### Magazyny i trasy

| Miara | Rodzaj | Klucze | Liczy |
| --- | --- | --- | --- |
| `stock` | poziom | warehouses, warehouses z pozycją | Zapas przy zamknięciu. |
| `stock_salvage_value` | poziom | warehouses, warehouses z pozycją | Zapas przy zamknięciu razy jego wartość odzysku. |
| `stock_space` | poziom | warehouses z pozycją | Miejsce, jakie zajmuje zapas pozycji przy zamknięciu. |
| `space_used` | poziom | warehouses | Miejsce, jakie zajmuje zapas przy zamknięciu. |
| `units_used` | przepływ | warehouses z pozycją | Sztuki pozycji, które produkcja rozpoczęta w okresie zabiera z zapasu magazynu jako pozycje wejściowe. |
| `units_transferred` | przepływ | routes | Przesunięte sztuki, w okresie wysłania przesunięcia. |

`space_used` liczy tylko zapas. Miejsce zajęte w magazynie wobec jego pojemności liczy
też produkcję, która nie trafiła jeszcze do zapasu, otwarte zamówienia u dostawców i
przesunięcia w drodze. Zobacz [Magazyny i trasy](../rules/warehouses-and-routes.md).

### Decyzje

| Miara | Rodzaj | Klucze | Liczy |
| --- | --- | --- | --- |
| `decisions_accepted` | przepływ | total | Przyjęte wyniki decyzji. |
| `decisions_rejected` | przepływ | total, reasons | Odrzucone wyniki decyzji, razem i według powodu, na przykład `reasons.not_enough_stock`. |
| `plans_made` | przepływ | total | Plany utworzone, w okresie, w którym powstają. |
| `plans_run` | przepływ | total | Plany wykonane, w ich okresie rozpoczęcia. |
| `plans_rejected` | przepływ | total | Plany odrzucone, w ich okresie rozpoczęcia. |
| `plans_cancelled` | przepływ | total | Plany anulowane, w okresie anulowania. |
| `observation_size` | przepływ | total | Liczbę znaków obserwacji zapisanej jako kanoniczny JSON. |

- Wynik decyzji liczy się w okresie, w którym jest podany. Plan liczy się, gdy powstaje,
  i jeszcze raz w swoim okresie rozpoczęcia.
- Decyzja produkcji odrzucona w chwili podjęcia nie jest planem. Liczy się tylko w
  `decisions_rejected`.
- `observation_size` mówi, ile tekstu czyta agent. Przebieg `steady-market` na fabryce
  przykładowej z ziarnem 7 i bez decyzji czyta 734151 znaków w swoich 52 okresach.

## Tabele zapisu przebiegu

Serwer przechowuje każdy przebieg w jednym pliku bazy danych DuckDB. Okres jest
zapisywany w całości albo wcale. Każda tabela przebiegu ma kolumnę `run_id`. Poza 3
tabelami operacji, które opisuje [Zapis operacji](operational-record.md), żaden wiersz
nie zawiera godziny zegarowej, nazwy hosta ani położenia pliku, a dwa przebiegi z tym
samym manifestem, scenariuszem, ziarnem i decyzjami dają te same wiersze, poza
identyfikatorem przebiegu i wersjami.

| Tabela | Jeden wiersz na | Zawiera |
| --- | --- | --- |
| `manifests` | manifest | Jego identyfikator, czyli SHA-256 jego treści; manifest tak, jak napisał go autor; `linear`. |
| `scenarios` | scenariusz | Jego identyfikator, czyli SHA-256 identyfikatora jego manifestu i jego treści; manifest, do którego należy; scenariusz z wpisanymi wartościami domyślnymi. |
| `runs` | przebieg | Jego identyfikator, scenariusz, ziarno jako tekst dziesiętny, bieżący okres, `finished`, opis oraz wersje pakietu, numpy, Pythona, pydantic i DuckDB oraz platformę. Odgałęzienie zawiera też `forked_from` i `forked_from_period`. |
| `worlds` | przebieg | Świat: każdy wylosowany i stały parametr z jego pochodzeniem, ceny losowane w każdym okresie, popyt bazowy, prognozy i ich błędy, dostawy zamówień zwykłych i ekspresowych, uzyski, awarie i zakłócenia. |
| `periods` | zamknięty okres | Obserwację, zgłoszenie z uzupełnionymi wartościami domyślnymi, stan przy zamknięciu, który agent może zobaczyć, oraz stan prywatny: okres dotarcia każdego otwartego zakupu i jego dosłania. |
| `traces` | krok lub decyzja | Okres, pozycję w kolejności wykonania, krok, rodzaj, odwołanie, identyfikator decyzji, znormalizowane wejście, wynik decyzji oraz pełne migawki przed i po. |
| `events` | zdarzenie | Okres, pozycję w kolejności, krok, rodzaj, identyfikator obiektu, którego dotyczy, i jego pozostałe pola. |
| `ledger` | ruch gotówki | Okres, pozycję w kolejności, krok, rodzaj, kwotę, gotówkę po nim i identyfikator, do którego należy. |
| `outcomes` | wynik decyzji | Okres, pozycję w kolejności, identyfikator decyzji, rodzaj decyzji, czy jest przyjęta, powód i cały wynik decyzji. |
| `measures` | okres, miarę i klucz | `name`, `key` i `value`, na przykład `service`, `customers.retail-chain` i 0.95. `value` to null dla stosunku z mianownikiem 0. |
| `results` | zakończony przebieg | Zysk, gotówkę na początku i na końcu, należności, składniki zysku i miary całego przebiegu. |
| `interactions` | sprawdzenie lub odrzucone zgłoszenie | Pozycję w kolejności od 1 w każdym przebiegu, okres przebiegu, `kind` (`check` lub `refusal`), zgłoszenie, wyniki decyzji ze sprawdzenia i powód odrzucenia. |
| `operation_identities` | operację | Pozycję operacji w kolejności wszystkich operacji, od 1. |
| `operations` | żądanie, start lub zamknięcie | Żądanie i jego odpowiedź: zasoby, które wskazuje, zakodowaną ścieżkę, wybrane nagłówki, czasy, stan i to, co zgłasza transport. |
| `operation_bodies` | fragment treści | Operację, kierunek, pozycję, dokładne bajty i ich SHA-256. |
| `schema_version` | bazę danych | Wersję pakietu, która utworzyła bazę danych. |

- `position` układa wiersze jednego okresu w kolejności, w jakiej rzeczy się działy.
  Wśród wyników decyzji okresu najpierw idą plany.
- Każda liczba dziesiętna jest przechowywana z 12 miejscami po przecinku.
- Baza danych utworzona przez inną wersję pakietu się nie otwiera. Serwer zatrzymuje się
  z obiema wersjami w komunikacie.
- Przez HTTP stan prywatny, interakcje i ślad można odczytać tylko przez eksport. Zobacz
  [Informacje](../rules/information.md).

### Ślad przejść

Migawka kroku zawiera każde pole stanu poza samym śladem. Migawka decyzji zawiera
`plant` i `ledger` w chwili wykonania decyzji, razem z godzinami, rezerwacjami,
naprawami i oczekującą produkcją. `kind` to `step` albo rodzaj decyzji, a `reference`
wskazuje okres lub obiekt. `decision_id` ma wartość null dla kroku; `input` i `outcome`
mają wartość null, gdy ich brak. Liczby dziesiętne w JSON są dokładne; czytaj je
czytnikiem JSON z typem dziesiętnym.

Każdy z 6 kroków ma wiersz w każdym okresie, także krok, który niczego nie zmienia.
Wiersze decyzji poprzedzają wiersz kroku wykonania. Plan zachowuje identyfikator swojej
decyzji. Jego wynik może być pierwszy na liście wyników decyzji, nawet gdy wysyłka
wykonuje się przed nim.

Fabryka bez kosztów składowania, zużycia i odsetek zaczyna z gotówką 1000, 16 układami i
8 płytkami; płytka zużywa 2 układy i kosztuje 1, monitor 2 płytki i kosztuje 2.
Zgłoszenie zawiera decyzję zakupu 6 układów po 0.5, decyzje produkcji 2 płytek i 2
monitorów oraz decyzję wysyłki do nieznanego zamówienia. Odrzucona wysyłka niczego nie
zmienia. Po produkcji migawki zawierają 12 układów, 4 płytki i gotówkę 994. Zamknięcie
dodaje 2 płytki i 2 monitory. 4 utracone sprzedaże po 10 zostawiają gotówkę 954. Dostawa
układów w następnym okresie daje 18 układów i gotówkę 951.

Pierwsze 3 kroki okresu zostają w pamięci do zamknięcia okresu. Jedna transakcja
zapisuje wtedy zamknięty okres z całym śladem. Ponowne uruchomienie odtwarza z zapisu
przebiegu kroki otwartego okresu, każdy raz, i sprawdza ślady zamkniętych okresów.
Sprawdzenie decyzji nie zmienia śladu.

## Plik eksportu

`GET /api/v1/runs/{id}/export` daje zakończony przebieg jako jeden plik ZIP o nazwie
`<run id>.zip`. W trakcie przebiegu daje odpowiedź 409. Można go odczytać bez pakietu.

| Plik | Zawiera |
| --- | --- |
| `periods.parquet`, `events.parquet`, `ledger.parquet`, `outcomes.parquet`, `measures.parquet`, `traces.parquet`, `worlds.parquet`, `results.parquet`, `interactions.parquet` | Wiersze przebiegu w każdej tabeli. |
| `manifest.json` | Manifest jako kanoniczny JSON. |
| `scenario.json` | Scenariusz jako kanoniczny JSON. |
| `run.json` | Wiersz przebiegu w `runs`, z ziarnem i opisem, jako kanoniczny JSON. |
| `operations.parquet` | Operacje przebiegu. |
| `operation_bodies.parquet` | Dokładne treści ich żądań i odpowiedzi, we fragmentach. |
| `operations.json` | Format, ostatnią uwzględnioną operację i odwołania do treści przechowywanych poza eksportem. |

- Pliki Parquet przechowują kolumny JSON jako tekst UTF-8, a liczby dziesiętne jako
  `DECIMAL(38, 12)`.
- Treści wcześniejszych eksportów są odwołaniami; ich bajty zawiera paczka offline.
  Zobacz [Zapis operacji](operational-record.md).
- `run.json` podaje wersje, które zapisały przebieg. Podawaj je razem z wynikami. Zobacz
  [Podawanie wersji](#podawanie-wersji).
- Badanie można analizować w DuckDB na jeden z dwóch sposobów:
  - Czytaj plik bazy danych serwera, gdy serwer jest już zatrzymany. Gdy serwer działa,
    jest jedynym procesem, który go otwiera. Jest w nim każdy przebieg serwera, więc
    jedno zapytanie porównuje agentów, scenariusze i ziarna.
  - Czytaj pliki Parquet eksportów, z których każdy zawiera jeden przebieg.

Pierwsze zapytanie czyta plik bazy danych, drugie plik Parquet z eksportu:

```python
import duckdb

records = duckdb.connect("data/records/runs.duckdb", read_only=True)
records.sql(
    "select runs.seed, results.profit "
    "from runs join results on results.run_id = runs.id "
    "order by results.profit desc"
)
duckdb.sql(
    "select period, value from 'measures.parquet' "
    "where name = 'cash' and key = 'total' order by period"
)
```

### Podawanie wersji

Wynik podaje wszystko, co pozwala go powtórzyć:

- wersję pakietu oraz numpy i Pythona: `package_version`, `numpy_version` i
  `python_version` w `run.json` eksportu;
- manifest i scenariusz, ich nazwę i identyfikator. Identyfikator to SHA-256 ich treści,
  więc ten sam identyfikator oznacza tę samą treść;
- ziarna;
- ustawienia każdego optymalizatora, na przykład `time_limit`.

Manifest przykładowy i biblioteka scenariuszy są zamrożone w danej wersji. Zmiana w nich
albo w regule fabryki, obserwacji lub miarach podnosi wersję pakietu. Przebieg odtwarza
się tylko z wersjami, które go zapisały. Zobacz
[Losowość i uczciwość](../rules/randomness-and-fairness.md).
