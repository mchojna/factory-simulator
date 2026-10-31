# Optymalizatory

Benchmark ma 8 agentów: brak decyzji, optymalizator odniesienia, 5 optymalizatorów
z ograniczoną wiedzą i optymalizator poinformowany.

## Optymalizatory

Każdy agent to jeden moduł `factory_simulator.benchmark.optimizers`:

| Agent | Moduł | Co wie | Co planuje |
| --- | --- | --- | --- |
| `no_decisions` | `no_decisions.py` | Nic. | Pustą listę decyzji w każdym okresie. Jego zysk to 0 znormalizowanego wyniku. |
| `reference_optimizer` | `reference.py` | Cały świat przebiegu. | Program od bieżącego okresu do końca przebiegu. Jego zysk to odniesienie, 1 znormalizowanego wyniku. |
| `full_horizon_optimizer` | `full_horizon.py` | Opis i obserwacje. | Program od bieżącego okresu do końca przebiegu, ze spodziewanym popytem. |
| `rolling_optimizer` | `rolling.py` | Opis i obserwacje. | Program na oknie tak długim jak najdłuższy łańcuch czasów realizacji od zakupu do sprzedaży, plus 2 okresy, ze spodziewanym popytem i wartością końcową zapasu. |
| `buffered_rolling_optimizer` | `buffered_rolling.py` | Opis i obserwacje. | Program optymalizatora kroczącego, w którym zapas na końcu okna jest wart 1.2 razy swój koszt zamiast 1.01. |
| `aligned_optimizer` | `aligned.py` | Opis i obserwacje. | Program na oknie optymalizatora kroczącego, z popytem tylko z otwartych zamówień klientów i prognoz. |
| `informed_optimizer` | `informed.py` | Opis i obserwacje oraz opis przebiegu bliźniaka swojego scenariusza, w którym nic nie jest ukryte. | Program optymalizatora kroczącego, przy danym mu współczynniku wartości końcowej, 1.01 albo 1.2, z każdym ukrytym zakresem według `cut_mean`, który pokazuje bliźniak. |
| `myopic_optimizer` | `myopic.py` | Opis i obserwacje. | Program tylko na bieżący okres, z wartością końcową zapasu i zamówień, które są jeszcze w drodze. |

Optymalizator na cały horyzont, kroczący, buforowy kroczący, dopasowany i
krótkowzroczny to optymalizatory z ograniczoną wiedzą: znają tylko opis i obserwacje.
Optymalizator poinformowany to diagnostyka.

- Każdy optymalizator w każdym okresie rozwiązuje jeden program zysku za pomocą
  HiGHS, z prawdziwego stanu przebiegu. Program jest mieszany całkowitoliczbowy, gdy
  pierwszy okres jego okna ma zakup albo zakup ma minimalną ilość powyżej 0 albo progi
  rabatowe lub pozycja linii ma czas lub koszt przezbrojenia powyżej 0. W przeciwnym
  razie jest liniowy. To, czy okres kupuje, jest wyborem tak albo nie: okres, którego
  gotówka pomniejszona o to, co są winne otwarte zamówienia u dostawców, jest poniżej
  minus limit kredytowy, nie składa zakupu, bo silnik go odrzuca. Manifest liniowy też
  ma ten wybór. Fabryka przykładowa ma wszystkie trzy, więc każdy optymalizator
  rozwiązuje na niej program mieszany całkowitoliczbowy. Jego wybory tak albo nie są
  całkowite tylko w pierwszym okresie programu. W każdym późniejszym okresie mogą
  przyjąć dowolną wartość od 0 do 1.
- Optymalizator zaokrągla decyzje okresu w dół do ich miejsc po przecinku i sprawdza je
  przez `POST /api/v1/runs/{id}/checks` swojego przebiegu. Decyzja, którą sprawdzenie
  odrzuca z braku pozycji wejściowych, miejsca lub kredytu, jest korygowana do tego, co
  dostępne, po jednej, od pierwszej, a decyzje są sprawdzane jeszcze raz po każdej
  korekcie, więc decyzja odrzucona tylko dlatego, że odrzucono wcześniejszą, zachowuje
  swoją ilość. Sprawdzenie podaje po jednej brakującej pozycji wejściowej, więc
  produkcja, której brakuje kilku pozycji, jest korygowana do każdej po kolei i
  zachowuje najwięcej, na ile pozwala każda z nich. Pozycje wejściowe produkcji
  opuszczają zapas zaokrąglone w górę przy każdej ilości, więc produkcja skorygowana do
  miejsca może nadal go nie mieć; jest korygowana jeszcze raz, aż się zmieści.
  Sprawdzenie zakupu czyta jego miejsce przed jego kredytem, więc zakup skorygowany do
  miejsca może nadal nie mieć kredytu; jest korygowany także do kredytu. Optymalizator
  zgłasza decyzje, które przyjmuje ostatnie sprawdzenie.
- Rozwiązywanie kończy się, gdy znalezione rozwiązanie jest najwyżej 0.01 poniżej
  ograniczenia jego programu, w pieniądzu, albo po 1000 węzłach HiGHS, zależnie od
  tego, co nastąpi pierwsze, i gra najlepsze znalezione rozwiązanie. HiGHS czyta zysk
  bez części, której żadna decyzja nie zmienia, takiej jak gotówka początkowa albo
  zysk wcześniejszych okresów, więc ta część nigdy nie przesuwa miejsca, w którym
  rozwiązywanie się kończy. `time_limit`, domyślnie 600 sekund, to jeden budżet na
  rozwiązanie, zabezpieczenie: przebieg z rozwiązaniem zatrzymanym na nim zależy od
  szybkości komputera.
- Rozwiązywanie, które kończy się na limicie bez znalezionego rozwiązania, zostawia swój
  okres bez decyzji, a przebieg idzie dalej. Program, który HiGHS uznaje za sprzeczny
  albo za nieograniczony lub sprzeczny, jest rozwiązywany jeszcze raz bez presolve, w
  tym samym budżecie. Program nadal sprzeczny albo nieograniczony zatrzymuje
  optymalizator z błędem, który podaje okres.
- Optymalizator z ograniczoną wiedzą liczy zakres według jego `cut_mean`, średniej
  rozkładu obciętego do `min` i `max`, którą podaje opis. Cena losowana w każdym
  okresie liczy się według ceny z obserwacji w jej okresie, a później według jej
  `cut_mean`. Zakup dociera po czasie realizacji. Ukryte grupy stosują założenia z
  poniższej tabeli.
- Zapas na końcu okna, które kończy się przed końcem przebiegu, do jego spodziewanego
  użycia, jest wart współczynnik wartości końcowej razy koszt zakupu lub wytworzenia:
  1.2 dla buforowego optymalizatora kroczącego i 1.01 dla pozostałych. Zapas powyżej
  tego jest wart swoją wartość odzysku. W fabryce przykładowej okres składowania
  kosztuje od 0.41 do 0.51 procent tego kosztu, więc trzymana jednostka zwraca się
  przez około 2 okresy przy 1.01 i około 40 przy 1.2: współczynnik ustala zapas, który
  zostawia okno.
- Spodziewane użycie pozycji liczy spodziewany popyt okresów po oknie, tylu, ile liczy
  najdłuższy łańcuch czasów realizacji od zakupu do sprzedaży, i żadnego po ostatnim
  okresie przebiegu. W każdym z tych okresów popyt każdego klienta i produktu to jego
  średni popyt bazowy razy jego kształty popytu i widoczne szoki popytu; komponenty i
  materiały liczą to, czego potrzebują do niego domyślne receptury. Popyt, który
  kształt kończy przed tymi okresami, daje spodziewane użycie 0.

Optymalizatory z ograniczoną wiedzą stosują takie założenia dla ukrytych grup:

| Ukryta grupa | Założenie |
| --- | --- |
| `customers.products.demand` | Średnia popytu pary klient-produkt w obserwowanych okresach, w których współczynnik jej znanych kształtów popytu i widocznych szoków popytu jest powyżej 0, po podzieleniu przez ten współczynnik. Okres bez zamówienia liczy się jako 0, a zamówienie liczy się w okresie, w którym wpłynęło. Bez takiego okresu średnia wynosi 0. |
| `suppliers.catalogue.punctuality` | Każda dostawa dociera na czas. |
| `suppliers.catalogue.delay` | Pomijane; każda dostawa jest planowana na czas. |
| `suppliers.catalogue.completeness` | Dociera cała otwarta ilość. |
| `suppliers.catalogue.acceptance` | Każda dostarczona sztuka przechodzi kontrolę. |
| `lines.items.yield` | Uzysk wynosi 1. |
| `lines.breakdown_chance` | Szansa awarii wynosi 0. |
| `lines.breakdown_loss` | Strata awarii wynosi 0. |
| `disruptions.duration` | Zakłócenie jest planowane do końca przebiegu. |

Optymalizator poinformowany stosuje te same założenia. Dostaje wartości `cut_mean`
przebiegu bliźniaka i nigdy nie dostaje wartości losowanej na okres. Tak jak
optymalizatory z ograniczoną wiedzą pomija punktualność i opóźnienie, widoczne czy
ukryte, więc planuje każdą dostawę na czas.

- Program nigdy nie anuluje zamówienia u dostawcy.
- Program wykonuje przesunięcia okresu w kolejności swoich tras, według nazwy źródła,
  a potem celu, i optymalizator zgłasza je w tej kolejności. Przesunięcie z magazynu
  zwalnia jego miejsce dla przesunięcia do niego, które jest dalej w tej kolejności.
  Sztuka, którą przesunięcie wnosi do magazynu, nie jest przesyłana dalej w tym samym
  okresie.
- Program liczy przezbrojenia okresu dla jednej kolejności swoich produkcji: na każdej
  linii najpierw pozycja, na którą linia jest ustawiona, na końcu pozycja, na którą
  jest ustawiona przy zamknięciu, a produkcje jednej pozycji razem. Optymalizator
  zgłasza tę kolejność, gdy każda produkcja mieści się w miejscu, które jej magazyn ma
  wolne przed nią. W przeciwnym razie zgłasza kolejność, w której każda produkcja się
  mieści, z tak małą liczbą przezbrojeń, jaką znajduje. Taka kolejność może płacić
  więcej przezbrojeń, niż liczy program, i ich godziny; sprawdzenie odrzuca wtedy
  produkcję, której tych godzin brakuje.
- Każdy optymalizator przechowuje `solves`, raport każdego rozwiązania
  całkowitoliczbowego: jego okres, to, czy znalazło rozwiązanie, czy zatrzymało się na
  limicie węzłów lub limicie czasu, jego `value`, `bound` i `gap` w pieniądzu, jego
  sekundy, przezbrojenia, które płacą jego decyzje (`changeovers`), i te, które liczy
  jego program (`planned_changeovers`). `gap` to ograniczenie minus wartość, co najmniej
  0: najwięcej, o ile rozwiązanie może być poniżej najlepszego rozwiązania jego
  programu. Przechowuje też `dropped`, decyzje, które odrzuciło jego ostatnie
  sprawdzenie; `fitted`, decyzje, które zmieniła korekta; oraz `relaxed_program_value`,
  wartość programu zrelaksowanego jego pierwszego okresu.
- `reference_optimizer(check, customer_orders, world)` dostaje świat zakończonego
  przebiegu braku decyzji z tym samym scenariuszem i ziarnem oraz zamówienia klientów
  każdego okresu tego przebiegu, z `customer_orders_of(read_periods(...))` modułu
  `reference.py`. Zamówienia klientów nie zależą od decyzji.
- `reference_optimizer(check, customer_orders, world, exact=True)` to kontrola
  dokładna: jej wybory tak albo nie są całkowite w każdym okresie jej programu.
  Program o więcej niż 100 wyborach tak albo nie zgłasza `ValueError`, więc służy
  małym światom, na przykład testowi odniesienia. Nie jest agentem testu
  przeciążającego.
- `informed_optimizer(check, terminal_value_factor, shown_description)` dostaje opis
  przebiegu bliźniaka z `create_shown_description`, uruchomionego z ziarnem swojego
  przebiegu. Planuje z tego opisu i z obserwacji własnego przebiegu, więc liczy każdy
  ukryty zakres według jego `cut_mean` i nigdy nie widzi wartości losowanej na okres.
  Ukryty czas trwania zakłócenia planuje tak jak optymalizatory z ograniczoną wiedzą:
  do końca przebiegu.

Kalibrację biblioteki scenariuszy opisuje strona
[Test przeciążający](stress-test.md#kalibracja).

Ten program gra optymalizator kroczący na `steady-market` z ziarnem 0:

```python
from functools import partial

import httpx2 as httpx

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer

with httpx.Client(base_url="http://127.0.0.1:8000/api/v1") as client:
    name = "Electronics factory with economies of scale"
    manifest_id = benchmark.find_manifest(client, name)
    scenario_id = benchmark.find_scenario(client, manifest_id, "steady-market")
    run = benchmark.start_run(client, scenario_id, 0)
    optimizer = rolling_optimizer(partial(benchmark.create_check, client, run["id"]))
    result = benchmark.play_run(client, run, optimizer)
    print(result["profit"], len(optimizer.solves))
```

Wypisuje `1007491.89663264 52`. Uruchom dla niego serwer jak na stronie
[Szybki start](../start/quick-start.md), z `--timeout-keep-alive 30` dodanym do
polecenia `uvicorn`. Serwer trzyma wtedy bezczynne połączenie dłużej niż klient, który
zamyka je po 5 sekundach, gdy optymalizator rozwiązuje program.

## Limit zakupów

Optymalizator ma limit zakupów, `purchase_budget_cap`, domyślnie `None`. Z limitem jego
program utrzymuje koszt decyzji zakupu każdego okresu swojego okna na poziomie limitu
albo poniżej, po cenie ich progu rabatu i z ceną ekspresową. Program zrelaksowany ma
ten sam limit. Silnik nie ma limitu zakupów, a gotówka, przyjęcie i płatność zachowują
swoje reguły. Program badania może ustawiać nowy limit w każdym okresie i odrzucać
zgłoszenie, którego decyzje zakupu kosztują więcej.
