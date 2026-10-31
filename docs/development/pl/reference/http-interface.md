# Interfejs HTTP

Symulator to usługa przez HTTP. Program badania tworzy lub wybiera manifest
i scenariusz, zaczyna przebieg z ziarnem, czyta obserwację każdego okresu i zgłasza
decyzje. Każda ścieżka leży pod `/api/v1`, czyta JSON i odpowiada JSON. Wyjątkiem jest
eksport, który odpowiada plikiem ZIP.

## Wszystkie ścieżki

`{manifest_id}`, `{scenario_id}` i `{run_id}` oznaczają identyfikatory. Myślnik
oznacza, że ścieżka nie przyjmuje treści albo nie ma własnego błędu.

| Ścieżka | Treść | Odpowiedź | Błędy |
| --- | --- | --- | --- |
| `POST /api/v1/manifests` | Manifest. | 201 i nowy manifest; 200 i zapisany manifest, gdy ten sam manifest jest już zapisany. | 422 |
| `POST /api/v1/manifests/generated` | `{"counts": {...}, "seed": n, "economy": "unrestricted"}` | 201 i manifest wygenerowany z liczby obiektów, ziarna i ekonomii; 200, gdy jest już zapisany. | 422 |
| `GET /api/v1/manifests` | - | 200 i `{"manifests": [...]}`: `id`, `name` i `description` każdego zapisanego manifestu, w kolejności `id`. | - |
| `GET /api/v1/manifests/{manifest_id}` | - | 200 i `{"id", "content", "linear"}`. | 404 |
| `POST /api/v1/manifests/{manifest_id}/scenarios` | Scenariusz. | 201 i nowy scenariusz; 200 i zapisany scenariusz, gdy ten sam scenariusz jest już zapisany. | 404, 422 |
| `GET /api/v1/manifests/{manifest_id}/scenarios` | - | 200 i `{"scenarios": [...]}`: `id`, `name` i `description` każdego scenariusza manifestu, w kolejności `id`. | 404 |
| `GET /api/v1/scenarios/{scenario_id}` | - | 200 i `{"id", "content"}`. | 404 |
| `POST /api/v1/runs` | `{"scenario_id", "seed"}` | 201 i przebieg, w okresie 1. | 404, 422 |
| `GET /api/v1/runs/{run_id}` | - | 200 i przebieg. | 404, 409 |
| `GET /api/v1/runs/{run_id}/observation` | - | 200 i obserwacja bieżącego okresu. | 404, 409 |
| `POST /api/v1/runs/{run_id}/decisions` | `{"period", "decisions"}` | 200 i obserwacja następnego okresu albo, po ostatnim okresie, przebieg z `finished: true`. | 404, 409, 422 |
| `POST /api/v1/runs/{run_id}/checks` | `{"period", "decisions"}` | 200 i `{"outcomes": [...]}`: wynik, jaki każda decyzja miałaby teraz. Przebieg się nie zmienia. | 404, 409, 422 |
| `POST /api/v1/runs/{run_id}/forks` | `{"period"}` | 201 i nowy przebieg, w tym okresie. | 404, 409, 422 |
| `GET /api/v1/runs/{run_id}/periods` | - | 200 i `{"periods": [...]}`: każdy zamknięty okres. | 404, 409 |
| `GET /api/v1/runs/{run_id}/result` | - | 200 i wynik zakończonego przebiegu. | 404, 409 |
| `GET /api/v1/runs/{run_id}/world` | - | 200 i każda wartość wylosowana z ziarna. | 404, 409 |
| `GET /api/v1/runs/{run_id}/export` | - | 200 i plik ZIP `<run id>.zip`. | 404, 409 |

Co każda ścieżka odpowiada w trakcie przebiegu i po nim, podaje strona
[Informacje](../rules/information.md#kto-co-może-czytać).

## Manifesty i scenariusze

- Treść `POST /api/v1/manifests` to manifest w JSON. Zobacz
  [Pisanie manifestu](../guides/writing-a-manifest.md) i
  [dokumentację pól](manifest-fields.md).
- Identyfikator manifestu to SHA-256 jego treści, jako 64 cyfry szesnastkowe. Ta sama
  treść zawsze daje ten sam identyfikator.
- `content` manifestu to manifest taki, jak napisał go autor. Wartości dane przez
  grupy i wbudowane wartości domyślne nie są dodawane. `linear` to true, gdy żaden wpis
  katalogu nie podaje minimalnej ilości ani rabatów i żaden wpis linii nie podaje czasu
  ani kosztu przezbrojenia. `min_quantity`, `changeover_time` lub `changeover_cost`
  zapisane, nawet jako 0, dają `linear` równe false.
- Treść `POST /api/v1/manifests/{manifest_id}/scenarios` to scenariusz w JSON. Jest
  sprawdzany względem manifestu. Zobacz
  [Pisanie scenariusza](../guides/writing-a-scenario.md).
- Identyfikator scenariusza to SHA-256 identyfikatora jego manifestu i jego treści.
  Jeden scenariusz zapisany pod dwoma manifestami ma dwa identyfikatory.
- `content` scenariusza zawiera każdy klucz. Tam, gdzie autor pominął klucz, jest
  wpisana jego wartość domyślna. `name` i `description` scenariusza są zapisane razem
  z nim i nigdy nie są częścią opisu przebiegu.
- Manifest lub scenariusz wysłany dwa razy jest zapisany raz. Druga odpowiedź to 200
  z zapisanym dokumentem.

## Manifest wygenerowany z liczby obiektów

`POST /api/v1/manifests/generated` pisze manifest z liczby obiektów i ziarna, a potem
zapisuje go tak jak `POST /api/v1/manifests`:

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

| Klucz | Dozwolone wartości |
| --- | --- |
| `counts.materials` | Liczba całkowita od 1 do 200. |
| `counts.components` | Liczba całkowita od 1 do 100. |
| `counts.products` | Liczba całkowita od 1 do 50. |
| `counts.suppliers` | Liczba całkowita od 1 do 50. |
| `counts.customers` | Liczba całkowita od 1 do 50. |
| `counts.lines` | Liczba całkowita od 1 do 20 i najwyżej `components` plus `products`. |
| `seed` | Liczba całkowita od 0 do 2 do potęgi 128 minus 1. |
| `economy` | `unrestricted`, domyślnie, albo `matched`. |

- Sześć liczb obiektów jest wymaganych. Każda to liczba całkowita, jako liczba JSON
  albo jako tekst: `9` i `"9"` to ta sama liczba obiektów.
- Ziarno decyduje tylko o manifeście. Nie jest ziarnem żadnego przebiegu.
- Te same liczby obiektów i to samo ziarno dają ten sam manifest, bajt w bajt,
  w jednej wersji pakietu. Wysłane ponownie dostają odpowiedź 200 z zapisanym
  manifestem.
- Manifest przechodzi każde sprawdzenie `POST /api/v1/manifests`. Jest liniowy i ma
  jeden magazyn, `plant`. Jego obiekty mają nazwy z rodzaju i numeru, takie jak
  `material-1` i `line-3`. Jego `name` to `Generated factory`, a jego `description`
  podaje liczby obiektów i ziarno.
- Liczba obiektów spoza swoich wartości dostaje odpowiedź 422 przy swoim kluczu, na
  przykład `counts.lines: is above components + products`.
- `economy` ustala ceny produktów klienta: w zakresie cen fabryki przykładowej albo
  jako najniższy koszt produktu razy stosunek od 1.8124 do 2.4250. Inne słowo dostaje
  odpowiedź 422 przy `economy`. Zobacz
  [Większe manifesty](../guides/larger-manifests.md#ekonomia-manifestu-wygenerowanego).
- Scenariusz pisze się do manifestu wygenerowanego tak jak do każdego innego.

Jak generator buduje fabrykę, opisuje strona
[Pisanie manifestu](../guides/writing-a-manifest.md).

## Przebiegi

- `POST /api/v1/runs` przyjmuje `{"scenario_id": ..., "seed": ...}`. Ziarno to liczba
  całkowita od 0 do 2 do potęgi 128 minus 1, jako liczba JSON albo jako tekst: `7`
  i `"7"` to to samo ziarno. `7.0`, `-1`, `1.5`, `"1.5"`, 2 do potęgi 128 i `true` są
  odrzucane przy `seed`.
- Przebieg dostaje odpowiedź w postaci
  `{"id", "scenario_id", "description", "period", "finished"}`. `description` zawiera
  fabrykę i scenariusz takie, jakie agent może zobaczyć, oraz `linear`. Każdy zakres w
  nim ma `cut_mean`, średnią swojego rozkładu obciętego do `min` i `max`, zaokrągloną
  połówkowo do parzystej do 6 miejsc po przecinku: popyt `smart-monitor` dla
  `tier1-distributor`, logarytmiczno-normalny z medianą 35 i rozrzutem 0.4, obcięty do
  14 do 70, ma `cut_mean` 36.222159. Zobacz [Informacje](../rules/information.md#opis).
- Przebieg nigdy nie zawiera ziarna, świata, stanu przebiegu ani wyniku przebiegu.
- Przebieg zaczyna się w okresie 1. Zakończony przebieg ma `period` równe horyzontowi
  i `finished: true`.
- Zgłoszenie to `{"period": 7, "decisions": [...]}`, z numerem bieżącego okresu.
  Zobacz [Decyzje](../rules/decisions.md#zgłoszenie).
- Sprawdzenie przyjmuje tę samą treść co zgłoszenie. Nie zmienia niczego poza zapisem
  interakcji. Zobacz [Decyzje](../rules/decisions.md#sprawdzenie-bez-wykonania).
- Odgałęzienie przyjmuje `{"period": p}`, gdzie p jest od 1 do horyzontu zakończonego
  przebiegu. Nowy przebieg ma ten sam scenariusz i to samo ziarno i stoi w okresie p.
  Zobacz
  [Rozgrywanie przebiegu](../benchmark/playing-a-run.md#odgałęzienia-dla-pytania-co-jeśli).
- `GET /api/v1/runs/{run_id}/periods` podaje każdy zamknięty okres jako `period`, jego
  sześć kroków `steps` po kolei, każdy z tym, co krok zrobił, oraz jego wiersze
  `ledger` po kolei, każdy z jego `period`, `step`, `kind`, `amount`, `cash_after` i
  `reference`.
- Wynik przebiegu, świat i eksport odpowiadają, gdy przebieg jest zakończony. Zobacz
  [Miary i zapis przebiegu](measures-and-the-record.md) oraz
  [Losowość i uczciwość](../rules/randomness-and-fairness.md).
- Zgłoszenia, sprawdzenia i odgałęzienia jednego przebiegu są wykonywane po jednym.
  Z dwóch zgłoszeń na jeden okres jedno jest wykonywane, a drugie dostaje odpowiedź
  409.
- Żadna ścieżka nie ma limitu czasu. Przebieg czeka na następne zgłoszenie tak długo,
  jak trzeba. Ponowne uruchomienie serwera prowadzi niezakończony przebieg dalej od
  jego zapisu przebiegu.

## Błędy

Każdy błąd odpowiada obiektem JSON z jednym kluczem:

```json
{"detail": "decisions.0.quantity: has more than 3 places"}
```

Tekst ma postać `<key>: <problem>`. Klucz to łańcuch kluczy połączonych kropkami
prowadzący do miejsca problemu. Pozycje na liście są liczone od 0, na przykład
`suppliers.apac-chips.catalogue.microchip.price` albo
`start.supplier_orders.0.quantity`. Problem całej treści ma klucz `body`. Odpowiedź
podaje tylko pierwszy problem.

| Kod | Kiedy | Tekst |
| --- | --- | --- |
| 404 | Manifest nie istnieje. | `manifest_id: unknown manifest <id>` |
| 404 | Scenariusz nie istnieje. | `scenario_id: unknown scenario <id>` |
| 404 | Przebieg nie istnieje. | `run_id: unknown run <id>` |
| 404 | Żadna ścieżka nie pasuje do adresu żądania. | `route: not found` |
| 405 | Ścieżka o tym adresie przyjmuje inną metodę, na przykład `DELETE /api/v1/manifests`. | `route: method not allowed` |
| 409 | Zakończony przebieg dostaje zgłoszenie lub sprawdzenie albo ktoś czyta jego obserwację. | `run: the run is finished` |
| 409 | Ktoś prosi niezakończony przebieg o wynik, świat lub eksport albo tworzy z niego odgałęzienie. | `run: the run is not finished` |
| 409 | Zgłoszenie lub sprawdzenie podaje inny okres niż bieżący. | `period: is 2, the run is in period 1` |
| 409 | Przebieg do kontynuowania po ponownym uruchomieniu albo do odgałęzienia został zapisany przez inne wersje albo przy powtórzeniu nie zgadza się ze swoim zapisem przebiegu. | Różnica, na przykład `runs.package_version: recorded 0.2.0, running 0.3.0`, `world: does not match the record` albo `periods.3: replayed period differs from the record` |
| 422 | Treść nie jest w UTF-8. | `body: is not UTF-8` |
| 422 | Treść nie jest JSON. | `body: is not JSON` |
| 422 | Treść jest zagnieżdżona głębiej, niż czytnik potrafi przeczytać, na przykład 5000 list jedna w drugiej. | `body: is nested too deeply` |
| 422 | Tekst lub klucz nie jest poprawnym Unicode, na przykład escape `"\ud800"`, połowa emoji. | `<key>: is not valid text`, `<key>: holds a key that is not valid text` |
| 422 | Obiekt treści zawiera klucz dwa razy. | `<key>: duplicate key` |
| 422 | Liczba nie jest w prostej postaci dziesiętnej albo jest `NaN` lub `Infinity`. | `<key>: is not a plain decimal number`, `<key>: is not a finite number` |
| 422 | Liczba ma więcej niż 50 cyfr, licząc miejsca po przecinku. | `<key>: has more than 50 digits` |
| 422 | Ziarno wysłane jako tekst ma więcej niż 39 cyfr. | `seed: is not from 0 to 2 ** 128 - 1` |
| 422 | Treść łamie swoją postać: brakujący lub nieznany klucz, zły typ, liczba spoza swoich wartości albo ze zbyt wieloma miejscami po przecinku. | `<key>: <problem>`, na przykład `counts.materials: Input should be greater than or equal to 1` |
| 422 | Manifest lub scenariusz nie przechodzi sprawdzenia. | `<key>: <problem>`, na przykład `horizon: material-1 cannot arrive within it and is not at hand` |
| 422 | Odgałęzienie podaje okres spoza horyzontu. | `period: is not from 1 to the horizon` |
| 500 | Błąd w symulatorze. Odpowiedź nigdy nie zawiera tekstu błędu; zawiera go dziennik serwera. | `server: internal error` |
| 503 | Żadne połączenie z bazą danych nie zwolniło się w ciągu 30 sekund. | `database: no connection was free within 30 s` |

- Każda ścieżka może odpowiedzieć 503, gdy serwer ma naraz wiele żądań, na przykład
  wiele przebiegów wracających po ponownym uruchomieniu. Program badania może wysłać
  żądanie ponownie.
- Zgłoszenie lub sprawdzenie dostaje odpowiedź w tej kolejności: nieznany przebieg
  404; zakończony przebieg 409; treść, która nie jest w UTF-8 albo nie jest JSON, 422;
  treść, która łamie swoją postać, 422; inny okres 409.
- Zgłoszenie lub sprawdzenie odrzucone z 409 z powodu innego okresu albo z 422 jest
  przechowywane w zapisie przebiegu jako interakcja, osobno od przebiegu. Odrzucone
  zgłoszenie zostawia przebieg w jego okresie.
- Odrzucone zgłoszenie to nie to samo co odrzucona decyzja. Poprawnie zbudowana decyzja,
  która łamie regułę fabryki, jest odrzucana z powodem w swoim wyniku decyzji, a okres
  się zamyka. Zobacz [Decyzje](../rules/decisions.md#powody-odrzucenia).
- Jak błąd wskazuje miejsce problemu w manifeście, opisuje strona
  [Pisanie manifestu](../guides/writing-a-manifest.md).

## Liczby

Każda ilość, cena, część i kwota pieniędzy to dokładna liczba dziesiętna.

- W treści żądania każda liczba może być liczbą JSON albo tekstem tej samej postaci:
  `40.5` i `"40.5"` to ta sama liczba.
- Postać to opcjonalny minus, potem cyfry bez zera na początku, potem opcjonalnie
  kropka i co najmniej jedna cyfra. `-0.25`, `0`, `12` i `12.5` przechodzą. `+5`, `.5`,
  `5.`, `010`, `1e3`, `1_000`, `NaN` i `Infinity` są odrzucane.
- Liczba ma najwyżej 50 cyfr, licząc miejsca po przecinku: ilość ma najwyżej 47 cyfr
  przed kropką.
- Każdy rodzaj liczby ma stałą liczbę miejsc po przecinku:

| Rodzaj | Miejsca | Przykłady |
| --- | --- | --- |
| ilość, miejsce, godziny | 3 | ilość w decyzji, miejsce pozycji, zdolność linii |
| pieniądze | 4 | cena, koszt, kara, wartość odzysku, gotówka na starcie |
| część, szansa, stopa, czynnik | 4 | uzysk, punktualność, stopa odsetek, wielkość naprawy |
| okresy | 0 | okres, horyzont, czas realizacji, ziarno |

- Liczba z większą liczbą miejsc niż jej rodzaj jest odrzucana, na przykład
  `decisions.0.amount: has more than 4 places`. Liczba z mniejszą liczbą miejsc jest
  uzupełniana: `40`, `40.0` i `40.000` to ta sama ilość.
- Liczba całkowita zapisana z kropką jest odrzucana: `52.0` jako horyzont dostaje
  odpowiedź `horizon: is not a whole number`.
- Odpowiedzi zapisują każdą liczbę dziesiętną jako liczbę JSON w prostej postaci: bez
  wykładnika, bez zer na końcu i 0 zamiast ujemnego zera. `40.000` jest zapisane jako
  `40`. Ziarno też jest liczbą JSON. Klucze każdego obiektu są posortowane.
- Liczby liczone w trakcie przebiegu, takie jak zysk, mogą mieć więcej miejsc po
  przecinku niż liczby, z których powstają; zapis przebiegu przechowuje do 12.
- Czytaj odpowiedzi bez binarnych liczb zmiennoprzecinkowych. Gubią one cyfry liczb
  dziesiętnych i ziaren powyżej 2 do potęgi 53. W Pythonie:
  `json.loads(text, parse_float=Decimal)`.
- Wysyłaj liczby dziesiętne jako tekst. W Pythonie `json.dumps(body, default=str)`
  zapisuje `Decimal("12.5")` jako `"12.5"`. Liczba zmiennoprzecinkowa może zostać
  zapisana z wykładnikiem, na przykład `1e-05`, a to jest odrzucane.

Program badania, który przestrzega tych reguł, pokazuje strona
[Rozgrywanie przebiegu](../benchmark/playing-a-run.md#dokładne-liczby-dziesiętne).

## Schemat OpenAPI

- `GET /api/v1/openapi.json` podaje schemat OpenAPI interfejsu: każdą ścieżkę, schemat
  każdej treści żądania i każdej odpowiedzi. Schemat opisuje dla każdej ścieżki
  odpowiedzi z błędem, jakie daje, każdą z treścią z sekcji [Błędy](#błędy),
  `ErrorPublic`.
- Schematy treści żądań to `ManifestCreate`, `ManifestGenerate`, `ScenarioCreate`,
  `RunCreate`, `DecisionsCreate` i `ForkCreate`.
- Schemat treści żądania deklaruje liczbę dziesiętną jako liczbę JSON albo jako tekst
  postaci podanej powyżej, a liczbę całkowitą jako całkowitą liczbę JSON albo jako jej
  tekst. Schemat odpowiedzi deklaruje obie jako liczby JSON.
- Schemat manifestu zostawia jako opcjonalny każdy klucz, który grupa może dać swojemu
  członkowi, na przykład `lead_time` wpisu katalogu. Członek, który pomija taki
  klucz, bierze go od swoich grup, a manifest, którego grupy nie dają wartości, jest
  odrzucany z kodem 422. `content` w `GET /api/v1/manifests/{manifest_id}` ma schemat
  treści żądania, `ManifestCreate`.
- `/api/v1/docs` pokazuje schemat jako stronę w przeglądarce, gdzie każdą ścieżkę
  można wypróbować.
- Narzędzie, które czyta OpenAPI, może z tego schematu zrobić kod w innym języku,
  który wywołuje interfejs.

## Serwer

- Serwer uruchamia się tak jak w [Szybkim starcie](../start/quick-start.md). Czyta dwie
  zmienne środowiskowe:

| Zmienna | Wartość |
| --- | --- |
| `FACTORY_SIMULATOR_DATABASE_URL` | Wymagana. Baza danych zapisu przebiegu, na przykład `duckdb:///data/records/runs.duckdb`. |
| `FACTORY_SIMULATOR_LOAD_EXAMPLES` | Domyślnie `true`. Gdy jest true, serwer przy starcie zapisuje manifest przykładowy i jego bibliotekę scenariuszy, chyba że są już zapisane. |

- Bez `FACTORY_SIMULATOR_DATABASE_URL` serwer nie startuje i podaje
  `FACTORY_SIMULATOR_DATABASE_URL: Field required`.
- `duckdb:///:memory:` jest odrzucany: baza danych w pamięci potrzebuje nazwy, na
  przykład `duckdb:///:memory:runs`. Serwer wtedy nie startuje i podaje
  `FACTORY_SIMULATOR_DATABASE_URL: an in-memory database needs a name, such as duckdb:///:memory:runs`.
- Serwer działa w jednym procesie. To jedyny proces, który otwiera plik bazy danych.
- Słucha na `127.0.0.1`, port 8000, chyba że uvicorn dostanie inne ustawienia. Nie ma
  logowania.
- Trwający przebieg trzyma swój świat i stan przebiegu w pamięci, aż zostanie zgłoszony
  jego ostatni okres albo serwer się zatrzyma. Ponowne uruchomienie zwalnia pamięć
  przebiegu, który program badania zostawił; następne żądanie do niego odbudowuje go.
- Serwer nie ogranicza żadnej treści żądania, żadnej listy decyzji ani liczby
  przebiegów. Odrzucona treść jest przechowywana w `interactions` w całości.
