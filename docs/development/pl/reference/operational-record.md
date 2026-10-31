# Zapis operacji

Serwer zapisuje w DuckDB każdą operację HTTP, każdy start i każde zamknięcie, obok
zapisu przebiegu fabryki. Przechowuje dokładne treści żądań i odpowiedzi, czasy i to,
co zgłasza transport. Agent w trakcie przebiegu odczytuje tylko opis, obserwację
i zamknięte okresy swojego przebiegu. Treści operacji są w eksporcie zakończonego
przebiegu i w paczce offline.

## Wiersze operacji

Sekwencja bazy danych daje każdej operacji pozycję w `operation_identities`. Pozycja
nigdy się nie zmienia. `operations` zawiera to, co serwer obserwuje o operacji na każdej
pozycji. Żądania obsługiwane w tym samym czasie mogą kończyć się w innej kolejności niż
ich pozycje. Pozycje mogą pomijać liczby, a pominięta liczba pozostaje niewykorzystana.

| Kolumny | Wartości |
| --- | --- |
| `position`, `request_id` | Pozycja w kolejności bazy danych i unikalny identyfikator żądania. |
| `kind`, `state` | `http`, `startup` lub `shutdown`; `received`, `completed`, `failed` lub `interrupted`. |
| `status_code` | Status odpowiedzi lub null. |
| `correlation_id` | `x-correlation-id` wysłane przez klienta lub null. |
| `method`, `path`, `route` | Metoda HTTP, odkodowana ścieżka i rozpoznany wzorzec ścieżki, gdy są znane. |
| `raw_path`, `query` | Bajty zakodowanej ścieżki i zapytania; zakodowana ścieżka ma wartość null, gdy ASGI jej nie podaje. |
| `requested_run_id` | Identyfikator przebiegu ze ścieżki, także nieznany. |
| `run_id`, `created_run_id` | Przebieg, gdy istnieje, i przebieg tworzony przez operację. Odgałęzienie wskazuje przebieg, który powtarza, i nowy przebieg. |
| `manifest_id`, `scenario_id` | Identyfikatory manifestu i scenariusza, gdy są znane, lub null. |
| `started_at`, `generated_at`, `finished_at`, `recovered_at` | Czasy UTC w formacie ISO. Czas, którego serwer nie obserwuje, ma wartość null. |
| `duration_ns` | Czas przetwarzania w nanosekundach, gdy jest zaobserwowany. |
| `request_complete`, `response_generated` | Czy zapis zawiera pełne żądanie i czy pełna odpowiedź jest wygenerowana. |
| `request_bytes`, `response_bytes` | Długości pełnych treści, gdy są znane; pusta pełna treść ma długość 0. |
| `headers_attempted`, `headers_sent` | Czy wysyłanie nagłówków odpowiedzi się zaczyna i czy wraca. |
| `attempted_bytes`, `sent_bytes` | Bajty treści, których wysyłanie się zaczyna, i bajty treści, których wysyłanie wraca. |
| `request_headers`, `response_headers` | Wybrane nagłówki protokołu w ich kolejności. |
| `exception_type`, `exception_message`, `exception_traceback` | Typ, tekst i ślad stosu wyjątku, gdy są znane. |

Obsłużone 404, 409 lub 422 kończy operację HTTP ze stanem `completed`. Wyjątek, którego
serwer nie obsługuje, daje stan `failed`, a zapis zachowuje stałą treść 500 jego
odpowiedzi. Przerwane odbieranie lub wysyłanie daje stan `interrupted`. Operacja, która
przy ponownym uruchomieniu jest wciąż w `received`, dostaje stan `interrupted`
i `recovered_at`; jej czas zakończenia i czas trwania pozostają null.

Zapis przechowuje nazwy i wartości nagłówków jako tekst Latin-1 w parach JSON, więc
bajty można odtworzyć. Wybrane nazwy to `host`, `accept`, `accept-encoding`,
`content-type`, `content-length`, `content-disposition`, `user-agent`, `allow`,
`location`, `etag`, `last-modified`, `cache-control`, `x-correlation-id`
i `x-request-id`. Zapis pomija każdy inny nagłówek, na przykład nagłówki
uwierzytelniania i ciasteczek.

## Fragmenty treści

`operation_bodies` przechowuje każdą treść we fragmentach. Fragment podaje swoje
`operation_id`, czyli pozycję swojej operacji. Jego `direction` to `request` lub
`response`; jego `position` zaczyna się od 1 w każdym kierunku. `body` zawiera najwyżej
65536 bajtów, a `digest` to ich SHA-256. Bajty są dokładne: białe znaki, zapis liczb
dziesiętnych, pominięte wartości domyślne, błędny JSON i niepoprawny UTF-8 zostają
takie, jak wysłał je klient. Pusta pełna treść nie ma fragmentów.

Rejestrator najpierw zapisuje żądanie do pliku tymczasowego, a potem kopiuje je do bazy
danych we fragmentach ograniczonej wielkości. Każdy zapis do bazy danych używa krótkiej
transakcji. Serwer zwalnia połączenie z bazą danych, zanim obliczy fabrykę lub wyśle
odpowiedź. Oczekujący zapis działa poza pętlą zdarzeń, więc inne żądania są dalej
obsługiwane.

## Obserwacje transportu

`response_generated` ma wartość true, gdy aplikacja wytworzyła pełną treść odpowiedzi.
Liczniki wysyłki liczą wywołania transportu ASGI, które się kończą, z błędem lub bez.
Poprawny powrót pokazuje tylko, że wywołanie wysyłki się skończyło; klient może nie
dostać bajtów. Przerwana wysyłka może zostawić nieznany wynik. Dla HEAD zapis zachowuje
treść, którą wytwarza aplikacja, także gdy transport pomija ją w odpowiedzi do klienta.

Odtwarzanie fabryki porównuje tabele fabryki i migawki śladu. Czasy, identyfikatory
żądań i fakty transportu operacji mają własną kolejność i własne sprawdzenia.

## Eksport zakończonego przebiegu

`GET /api/v1/runs/{id}/export` zawiera te pliki obok tabel fabryki i wejść przebiegu:

| Plik | Zawartość |
| --- | --- |
| `operations.parquet` | Operacje przebiegu, razem z operacjami, które go tworzą lub odgałęziają. |
| `operation_bodies.parquet` | Dokładne fragmenty żądań i odpowiedzi; odpowiedzi wcześniejszych eksportów są tylko odwołaniami. |
| `operations.json` | Format, przebieg, ostatnią uwzględnioną operację, rozmiar fragmentu i odwołania do treści przechowywanych poza eksportem. |

Ostatnia uwzględniona operacja jest wcześniejsza niż sam eksport, więc eksport pomija
własne żądanie i odpowiedź. Poprawna odpowiedź wcześniejszego eksportu jest
odwołaniem: operacją, kierunkiem, pozycją fragmentu, skrótem i długością w bajtach. Jej
bajty zostają w DuckDB i trafiają do paczki offline. Dzięki temu eksport przebiegu,
który eksportowano wiele razy, ma ograniczoną wielkość.

## Paczka offline

Zatrzymaj serwer zwykłym zamknięciem, następnie uruchom:

```sh
uv run python -m factory_simulator.api.record.transport \
  data/records/runs.duckdb data/records/transport.zip
```

Polecenie otwiera bazę danych tylko do odczytu, z wersją pakietu, która ją zapisała.
Sprawdza kolejność fragmentów, skróty, pełne długości i każde odwołanie do
wcześniejszego eksportu. Paczka zawiera każdą zapisaną treść do swojej ostatniej
operacji, razem z odpowiedziami wcześniejszych eksportów i operacjami bez przebiegu. Jej
`operations.json` zawiera sumę kontrolną bazy danych, wersję i liczniki sprawdzeń.
Polecenie odmawia zapisu w miejsce istniejącego pliku.

Baza danych rośnie z zapisanymi treściami i faktami ich operacji. Każdy eksport HTTP
dodaje własne bajty do bazy danych i do paczki offline. Praca eksportu i jego sprawdzeń
rośnie z historią i odwołaniami do wcześniejszych eksportów. Serwer zachowuje każdą
zapisaną operację. Zwykłe żądanie kosztuje tyle samo bez względu na historię, przy
treści tej samej wielkości.

## Dostępność i odtwarzanie

Gdy serwer nie może zapisać początku operacji, daje odpowiedź 503, zanim zadziała
funkcja obsługi ścieżki, i zapisuje błąd w logu. Gdy baza danych zawodzi, zapisy,
których nie przyjmie, przepadają. Gdy późniejszy zapis operacji zawodzi, operacja
zachowuje ostatnie zapisane fakty; mogą one być niekompletne.

Zapis startu zaczyna się, gdy baza danych się otworzy, a jej schemat zostanie przyjęty.
Błąd sprzed tej chwili jest tylko w wyjściu błędów polecenia startu. Zwykłe zamknięcie
zapisuje własną operację. Ponowne uruchomienie daje każdej niedokończonej operacji czas
odtworzenia i odtwarza otwarty okres fabryki zwykłym odtwarzaniem. Zobacz
[Miary i zapis przebiegu](measures-and-the-record.md).
