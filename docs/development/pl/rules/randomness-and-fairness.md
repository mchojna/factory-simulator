# Losowość i uczciwość

Każda losowa wartość przebiegu pochodzi z jednej liczby całkowitej, ziarna, i jest
ustalona przed pierwszym okresem.

## Ziarno

- Ziarno to liczba całkowita od 0 do 2 do potęgi 128 minus 1. Program badania podaje
  je, gdy zaczyna przebieg.
- Badanie losuje swoje ziarna spośród wielu możliwych wartości, aby nikt nie mógł ich
  zgadnąć.
- Ziarno zapisuje się z przebiegiem, gdy przebieg się zaczyna. Żadna odpowiedź
  interfejsu HTTP w trakcie przebiegu go nie pokazuje. Można je odczytać po końcu
  przebiegu.
- Jeden manifest służy wielu scenariuszom, a jeden scenariusz działa z wieloma
  ziarnami.

## Świat losuje się raz

Przed okresem 1 symulator losuje cały świat z manifestu, scenariusza i ziarna:

- każdy parametr podany jako zakres i losowany raz na przebieg;
- ceny losowane w każdym okresie;
- popyt bazowy każdego klienta i produktu w każdym okresie;
- błąd każdej prognozy;
- wynik każdej dostawy: na czas lub spóźniona, opóźnienie, kompletność i przyjęcie;
- uzysk każdej linii i pozycji w każdym okresie;
- awarie każdej linii i ich straty;
- zakłócenia losowe.

Świat trafia do zapisu przebiegu, gdy przebieg się zaczyna. W trakcie przebiegu
pozostaje ukryty. Po końcu przebiegu zwraca go `GET /api/v1/runs/{id}/world`. Dla
każdego parametru pokazuje wartość, skąd pochodzi (zapisana, z grupy lub wbudowana
wartość domyślna) i czy została wylosowana.

## Zakresy i ich cztery rozkłady

Parametr to stała liczba albo zakres. Zakres ma najniższą wartość `min`, najwyższą
wartość `max` i rozkład między nimi.

| `distribution` | Dodatkowe klucze | Wylosowana wartość |
| --- | --- | --- |
| `uniform` (domyślny) | brak | Każda wartość od `min` do `max` ma tę samą szansę. |
| `triangular` | `mode` | Najbardziej prawdopodobna blisko `mode`, mniej prawdopodobna w stronę `min` i `max`. |
| `normal` | `mean`, `sd` | Rozkład normalny ze średnią `mean` i odchyleniem standardowym `sd`, obcięty do zakresu. |
| `lognormal` | `median`, `spread` | Logarytm naturalny wartości ma rozkład normalny ze średnią równą logarytmowi `median` i odchyleniem standardowym `spread`, obcięty do zakresu. |

Zasady zakresu:

- `min` jest najwyżej równe `max`. Zakres trójkątny, normalny lub logarytmicznie
  normalny wymaga `min` mniejszego niż `max`.
- `mode`, `mean` i `median` leżą w zakresie. `sd` i `spread` są powyżej 0;
  `spread` jest najwyżej równy 10.
- Zakres logarytmicznie normalny wymaga `min` powyżej 0. Daje rzadkie wysokie
  wartości: długi ogon powyżej mediany.
- Liczbę całkowitą okresów, na przykład czas realizacji lub opóźnienie, losuje się
  tylko z równą szansą. Zakres okresów od 3 do 5 daje 3, 4 lub 5, każde z szansą 1/3.
- Wylosowaną wartość zaokrągla się do liczby miejsc po przecinku jej rodzaju: 3 dla
  ilości, 4 dla pieniędzy i części.
- Wylosowana wartość nigdy nie wychodzi poza swój zakres.

Jak działa losowanie:

- Każde losowanie bierze jedną liczbę losową od 0 do 1, z równą szansą.
- Zakres jednostajny zamienia ją na `min` + (`max` - `min`) x liczba losowa.
- Zakres normalny lub logarytmicznie normalny jest obcięty do zakresu: liczba losowa
  trafia na tę część rozkładu, która leży od `min` do `max`. Losowanie nigdy nie
  potrzebuje drugiej liczby, a wartości spoza zakresu nigdy nie występują.
- Zakres normalny lub logarytmicznie normalny znacznie węższy niż jego `sd` lub `spread`
  losuje prawie równomiernie w całym zakresie. Zakres normalny od 1 do 9 ze średnią 5 i
  `sd` 10 do potęgi 20 losuje 1.08 przy liczbie losowej 0.01 i 8.92 przy 0.99, a jego
  `cut_mean` wynosi 5.
- Losowanie normalne lub logarytmicznie normalne jest liczone w binarnej arytmetyce
  zmiennoprzecinkowej komputera. Blisko granicy dalszej niż 6 odchyleń standardowych od
  średniej albo 6 rozrzutów od mediany w logarytmie traci cyfry i może się różnić
  między komputerami: 80 w zakresie normalnym od 40 do 80 ze średnią 40 i `sd` 5 jest
  taką granicą. Każde inne losowanie jest takie samo na Linuksie, macOS i Windows.
- Szansa, na przykład szansa awarii, spełnia się, gdy jej liczba losowa jest od niej
  mniejsza.

Losowania z zakresów fabryki przykładowej dla liczb losowych 0.1, 0.5 i 0.9:

| Parametr | Zakres | 0.1 | 0.5 | 0.9 |
| --- | --- | --- | --- | --- |
| uzysk `control-board` na `smt-line` | jednostajny od 0.96 do 0.99 | 0.963 | 0.975 | 0.987 |
| cena `microchip` od `apac-chips` | trójkątny od 6.0 do 7.5, `mode` 6.5 | 6.2739 | 6.634 | 7.1127 |
| popyt na `industrial-controller` od `tier1-distributor` | normalny od 27 do 63, `mean` 45, `sd` 5.4 | 38.09 | 45 | 51.91 |
| popyt na `smart-monitor` od `tier1-distributor` | logarytmicznie normalny od 14 do 70, `median` 35, `spread` 0.4 | 21.233 | 34.468 | 54.281 |

Losowanie logarytmicznie normalne przy 0.5 jest poniżej mediany 35, bo zakres obcina
więcej rozkładu powyżej mediany niż poniżej niej.

Każdy zakres w opisie ma `cut_mean`, średnią swojego rozkładu obciętego do `min` i
`max`, zaokrągloną połówkowo do parzystej do 6 miejsc po przecinku. Zakres normalny
zachowuje swoją `mean`, średnią bez obcięcia. Popyt logarytmicznie normalny z `median`
35 i `spread` 0.4, obcięty do zakresu od 14 do 70, ma `cut_mean` 36.222159.

## Kiedy wartość się losuje

Każdy parametr ma jedną chwilę losowania:

| Chwila | Parametry |
| --- | --- |
| Raz na przebieg | Większość parametrów: koszty, ceny, czasy realizacji, punktualność, zdolności, zużycie, szansa awarii, czasy i koszty produkcji, kary, cierpliwość. |
| W każdym okresie | Popyt bazowy, uzysk i cena materiału, którego zakres ma `drawn: period`. |
| Na zdarzenie | Na dostawę: opóźnienie, kompletność i przyjęcie. Na awarię: jej strata. |

Niektóre parametry nie mogą być zakresami: miejsce, receptury, trwałość popytu, część
wspólna, zdolność i współczynniki magazynu oraz stopy i limit kredytowy gotówki.

- Cenę losuje się raz na przebieg, chyba że jej zakres ma `drawn: period`. Cenę
  losowaną w każdym okresie losuje się dla każdego okresu przed okresem 1 (zobacz
  [Dostawcy](suppliers.md)).
- Wartość losowaną na zdarzenie losuje się z góry dla każdego okresu. Wynik dostawy
  należy do dostawcy, materiału, okresu złożenia zamówienia i rodzaju zamówienia.
  Wszystkie zwykłe zamówienia tego materiału złożone u tego dostawcy w tym okresie
  dzielą jeden wynik, a wszystkie zamówienia ekspresowe drugi. Wynik okresu bez
  zamówienia też się losuje, ale się go nie używa.
- Liczbę losową awarii i stratę losuje się dla każdej linii w każdym okresie.
- Reguła zakłóceń losowych losuje w każdym okresie i dla każdego celu liczbę, która
  decyduje o jej początku lub o jej celu, czas trwania i działanie.
- Przy części wspólnej powyżej 0 klienci produktu dzielą część liczby losowej, która
  stoi za ich popytem. Każdy klient zachowuje własny zakres (zobacz
  [Klienci i popyt](customers-and-demand.md)).

## Każdy strumień losuje osobno

Każdy rodzaj losowej wartości ma własny strumień liczb losowych, nazwany tym, co
losuje: jeden parametr jednego obiektu, popyt jednego klienta i produktu, zwykłe
dostawy jednego dostawcy i materiału, jego dostawy ekspresowe, uzysk jednej linii
i pozycji, awarie jednej linii, jedna reguła zakłóceń losowych na jednym celu.

- Strumień losuje tyle samo liczb, cokolwiek dzieje się w przebiegu.
- Dodanie dostawcy, klienta, linii lub reguły zakłóceń losowych nie zmienia żadnej innej
  wylosowanej wartości.
- Zamiana stałego parametru na zakres albo zakresu jednostajnego na logarytmicznie
  normalny nie zmienia żadnej innej wylosowanej wartości.
- Dodanie celu do reguły z `choose: one` zmienia wybór tylko w okresach, w których
  wygrywa nowy cel.
- Przy tych samych wersjach ten sam manifest, scenariusz i ziarno dają ten sam świat,
  cyfra w cyfrę, na Linuksie, macOS i Windows, poza losowaniami blisko granicy daleko
  w ogonie (zobacz [Zakresy i ich cztery rozkłady](#zakresy-i-ich-cztery-rozkłady)).

## Ten sam świat dla każdego agenta

- Żadna losowa wartość nie zależy od decyzji. Agent nie może zmienić swojego
  szczęścia.
- Dwaj agenci z tym samym manifestem, scenariuszem i ziarnem mają ten sam popyt,
  dostawy, uzyski, awarie i zakłócenia. Ich zyski różnią się tylko z powodu ich
  decyzji.
- Awaria nie jest bardziej prawdopodobna na linii, która ciężko pracuje. Duże użycie
  obniża stan przez zużycie, które jest stałą zasadą (zobacz
  [Produkcja](production.md)).
- Świat jest ustalony przed okresem 1. Optymalizator odniesienia zna cały świat i
  planuje do końca przebiegu. Jego zysk to odniesienie, z którym porównuje się
  agentów.

## Prognozy są takie same dla każdego

- Prognoza zrobiona w okresie t na okres t + k to popyt okresu t + k razy (1 + e),
  zaokrąglony do 3 miejsc po przecinku i nigdy poniżej 0.
- Popyt w prognozie pomija zakłócenia, które w okresie t nie są jeszcze widoczne.
- Błąd e prognozy na k okresów naprzód to suma k przyrostów, z których każdy losuje
  się z równą szansą w swoim zakresie i zaokrągla do 4 miejsc po przecinku: jeden od
  `-noise` do `noise` i k - 1 od `-noise_growth` do `noise_growth`. Leży od
  -(`noise` + `noise_growth` x (k - 1)) do tej samej wartości powyżej 0.
- Przyrosty okresu losuje się raz; prognoza zrobiona okres później pomija przyrost
  najdalszej odległości.
- Każdy błąd jest częścią świata. Dlatego każdy agent z tym samym ziarnem widzi te
  same prognozy, cokolwiek decyduje.

Zobacz [Informacje](information.md), gdzie opisano prognozy, które podaje
scenariusz.

## Wersje i odtwarzanie

- Każdy przebieg zapisuje wersje pakietu, numpy i Pythona, które go zapisały.
- Wersję numpy, która losuje świat, ustala pakiet.
- Każda zmiana zasad fabryki, obserwacji, miar lub zapisu przebiegu podnosi wersję
  pakietu i dodaje wpis do dziennika zmian. Taka zmiana może zmienić przebieg z tymi
  samymi danymi wejściowymi i ziarnem.
- Każda inna zmiana zostawia każdą odpowiedź interfejsu HTTP i każdy wiersz zapisu
  przebiegu bez zmian dla tego samego manifestu, scenariusza, ziarna i decyzji, poza
  identyfikatorem przebiegu i wersjami. Sprawdzają to przebiegi zamrożone w zestawie
  testów.
- Po ponownym uruchomieniu serwera niezakończony przebieg jest kontynuowany od swojego
  zapisu przebiegu. Symulator losuje świat jeszcze raz, porównuje go z zapisanym światem
  i odtwarza zapisane zgłoszenia. Odgałęzienie odtwarza je tak samo do swojego okresu.
- Przebieg odtwarza się tylko z wersjami, które go zapisały: z tym samym pakietem i
  numpy oraz z Pythonem o tych samych dwóch pierwszych częściach wersji. Inne wersje go
  odrzucają. Zapisy przebiegów wcześniejszych wersji pozostają.
- Manifest przykładowy i biblioteka scenariuszy są zamrożone dla wersji. Ich zmiana to
  nowa wersja.

## Przykład

Przebieg `steady-market` na fabryce przykładowej z ziarnem 0 losuje uzysk
`control-board` na `smt-line` raz na okres. Jego zakres jest jednostajny od 0.96 do
0.99, więc uzysk wynosi 0.96 + 0.03 x liczba losowa. Uzysk jest częścią, więc każdą
wartość zaokrągla się połówkowo do parzystej do 4 miejsc po przecinku. Liczby losowe
poniżej są podane z dokładnością do 4 miejsc po przecinku.

- Okres 1: liczba losowa to 0.3144, więc uzysk wynosi 0.96 + 0.03 x 0.3144 = 0.969432,
  po zaokrągleniu 0.9694.
- Okres 2: liczba losowa to 0.0491, więc uzysk wynosi 0.96 + 0.03 x 0.0491 = 0.961473,
  po zaokrągleniu 0.9615.
- Okres 3: liczba losowa to 0.9299, więc uzysk wynosi 0.96 + 0.03 x 0.9299 = 0.987897,
  po zaokrągleniu 0.9879. Produkcja 400 płyt sterujących rozpoczęta w okresie 3 daje
  400 x 0.9879 = 395.16 dobrych sztuk, jak w przykładzie na stronie [Okres](period.md).
- Przebieg z ziarnem 0 bez decyzji ma w swoim świecie te same 3 uzyski co przebieg ze
  strony [Okres](period.md) z jego decyzjami zakupu i produkcji.
- Przy ziarnie 1 ten sam strumień daje liczby losowe 0.6771, 0.6156 i 0.6439, więc
  uzyski wynoszą 0.9803, 0.9785 i 0.9793.
