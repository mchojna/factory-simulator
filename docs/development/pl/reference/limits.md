# Ograniczenia

Symulator prowadzi jedną fabrykę z regułami liniowymi i jednym sprawdzeniem kredytu,
stałą liczbą miejsc po przecinku i odniesieniem granym przez optymalizator. Każda z tych
rzeczy ma ograniczenia. Każde ograniczenie poniżej ma trzy części: czym jest, jaki ma
skutek dla badania i co zrobić.

## Pominięte procesy

- Czym jest: Niektórych procesów prawdziwej fabryki nie ma w symulatorze: stałych
  kosztów za zamówienie, wysyłek typu wszystko albo nic, wad, które docierają do
  klientów, partii, zapasu wydawanego w kolejności przyjęcia, dat w kalendarzu, zmian
  zamówień klientów lub ich okresów terminu, rezerwowania godzin lub materiałów dla
  planu ani czasu drogi do klienta: wysyłka dociera do klienta w okresie, w którym
  zostaje wysłana.
- Skutek dla badania: Badanie nie może pytać o te procesy, na przykład o koszt
  częstego zamawiania, wycofanie złych sztuk albo święto w danym dniu. Plan niczego nie
  rezerwuje aż do swojego okresu początku, więc może zostać wtedy odrzucony. Złe sztuki
  pojawiają się tylko jako sztuki odrzucone przy kontroli i jako braki produkcji.
- Co zrobić: Trzymaj pytanie badania w granicach procesów, które symulator ma. Czytaj
  nazwę okresu, taką jak "week", tylko jako opis. Zapisuj sezony jako kształty popytu
  w okresach. Licz się z tym, że plan jest w całości sprawdzany w swoim okresie
  początku. Zobacz [Produkcja](../rules/production.md).

## Reguły liniowe

- Czym jest: Każda reguła poza sprawdzeniem kredytu przy zakupie jest liniowa
  w ciągłych ilościach. 12.5 sztuki to poprawna ilość. Wylosowana wartość wchodzi do
  reguły tylko jako znana liczba razy decyzja. Żadna reguła nie mnoży dwóch ilości,
  które zależą od decyzji. Odsetki też są liniowe. Sprawdzenie kredytu odrzuca zakup,
  który sprowadza gotówkę pomniejszoną o to, co są winne otwarte zamówienia
  u dostawców, poniżej minus limit kredytowy, i nigdy nie odrzuca żadnej innej decyzji.
  Dlatego decyzje, które je przechodzą, nie tworzą zbioru wypukłego. Przy gotówce 1,
  limicie kredytowym 0, zatrzymanej linii, której pełna naprawa kosztuje 2, i chipach
  po 1 sama naprawa 1 jest przyjmowana i zostawia gotówkę -1, a sam zakup 1 chipa też
  jest przyjmowany. W połowie drogi między nimi naprawa 0.5 z zakupem 0.5 chipa ma
  odrzucony zakup: naprawa zostawia gotówkę 0. Program potrzebuje więc wyboru tak albo
  nie w każdym okresie z zakupem: czy okres kupuje. Trzy kolejne mechanizmy wymagają
  wyboru tak albo nie: minimalne ilości, rabaty i przezbrojenia. Manifest bez żadnego
  z tych trzech jest liniowy; `linear` manifestu mówi, jaki on jest. `linear` opisuje
  tylko katalog i linie; nie liczy sprawdzenia kredytu.
- Skutek dla badania: Sztuki nigdy nie są z reguły całkowite, więc fabryka, która
  liczy całe sztuki, nie jest modelowana. Żaden manifest nie ma programu liniowego dla
  swoich najlepszych decyzji, gdy gotówka może dojść do limitu kredytowego.
  W manifeście liniowym program świata znanego w całości jest liniowy w każdej regule
  poza sprawdzeniem kredytu, z jednym wyborem tak albo nie na okres z zakupem: czy
  okres kupuje, na ile pozwala limit kredytowy. Podział przyjętej decyzji na dwie
  z tą samą sumą daje ten sam zapas, te same zamówienia, stan i gotówkę przy zamknięciu
  okresu. Każdy podział produkcji jednej linii i pozycji w jednym okresie daje te same
  dobre sztuki. Dwie produkcje jednej linii, pozycji i receptury w jednym okresie mogą
  zostawić zapas każdej pozycji wejściowej o 0.001 mniejszy niż jedna produkcja ich
  sumy, a gotówkę inną przez zaokrąglenie. Każdy podział zakupu na zakupy u tego
  samego dostawcy, tego samego materiału i do tego samego magazynu w jednym okresie
  daje te same sztuki, które dotarły, i te same przyjęte sztuki. W manifeście
  z korzyściami skali program ma więcej wyborów tak albo nie, a podział decyzji może
  zmienić to, co się dzieje: dwa zakupy poniżej minimalnej ilości są odrzucane, a jeden
  zakup ich sumy jest przyjmowany.
- Co zrobić: Używaj manifestu liniowego, na przykład wygenerowanego, gdy badanie
  potrzebuje programu, którego jedynymi wyborami tak albo nie są to, czy każdy okres
  kupuje. Daj mu gotówkę, której żaden koszt nie zużywa, gdy badanie potrzebuje
  odniesienia z dokładnym programem: limit kredytowy wtedy nigdy nie wiąże. Gdy limit
  kredytowy może wiązać w późniejszym okresie, mierz lukę polityki odniesienia kontrolą
  dokładną. Używaj fabryki przykładowej, aby badać minimalne ilości, rabaty
  i przezbrojenia, i podawaj luki jej odniesienia (zobacz
  [Odniesienie: limity pracy i luka](#odniesienie-limity-pracy-i-luka)). Zobacz
  [Pojęcia](../start/concepts.md#przebieg).

## Punkty zaokrąglania

- Czym jest: Ilości, miejsce i godziny mają 3 miejsca po przecinku; pieniądze
  i części mają 4. Symulator zaokrągla w stałych punktach:
  - każdą ilość, która wchodzi do zapasu lub zamówienia, na przykład sztuki dostarczone,
    przyjęte, dobre lub braki, połówkowo do parzystej do 3 miejsc;
  - każdą pozycję wejściową, którą produkcja bierze z zapasu, w górę do 3 miejsc;
  - cenę za sztukę zamówienia u dostawcy, połówkowo do parzystej do 4 miejsc, przy
    złożeniu zamówienia;
  - stan linii, w dół do 12 miejsc po każdej zmianie;
  - godziny pozostałe linii i limit zakupu przy braku materiału, w dół do 3 miejsc;
  - odsetki, do 4 miejsc na niekorzyść fabryki: odsetki zarobione w dół, odsetki
    zapłacone w górę;
  - wartości wylosowane do miejsc swojego rodzaju, a popyt bazowy, prognozy i ilość
    nowego zamówienia klienta połówkowo do parzystej do 3 miejsc;
  - ilorazy i średnie miar, połówkowo do parzystej do 12 miejsc.

  Każda inna kwota jest dokładna. Zapis przebiegu przechowuje każdą kwotę z 12
  miejscami.
- Skutek dla badania: Zaokrąglenie nie jest regułą liniową. Decyzje policzone
  dokładnie na kilka okresów mogą zostawić późniejszej decyzji 0.001 za mało, przez co
  zostanie odrzucona. Decyzja policzona w binarnych liczbach zmiennoprzecinkowych może
  mieć więcej miejsc niż jej rodzaj i wtedy całe zgłoszenie jest odrzucane. Przebieg
  powtarza się cyfra w cyfrę na każdym komputerze.
- Co zrobić: Licz decyzje w liczbach dziesiętnych. Przed wysłaniem zaokrąglaj ilości
  w dół do 3 miejsc, a wielkości napraw w dół do 4. Przed zgłoszeniem sprawdź decyzje
  okresu ścieżką `POST /api/v1/runs/{id}/checks`. Zobacz
  [Interfejs HTTP](http-interface.md#liczby).

## Odniesienie: limity pracy i luka

- Czym jest: Odniesienie to zysk, jaki optymalizator odniesienia osiąga, gdy gra świat
  przez symulator. W każdym okresie rozwiązuje program zysku do końca przebiegu,
  z prawdziwego stanu i przy znajomości całego świata. Zaokrągla decyzje okresu w dół,
  sprawdza je i zgłasza te, które sprawdzenie przyjmuje.
  - W manifeście liniowym jedynym wyborem tak albo nie programu jest to, czy okres
    kupuje.
  - Gdy wpis katalogu ma minimalną ilość powyżej 0 lub rabaty albo wpis linii ma czas
    lub koszt przezbrojenia powyżej 0, program ma więcej wyborów tak albo nie. Każdy
    wybór tak albo nie, także to, czy okres kupuje, jest całkowity tylko w pierwszym
    okresie programu; w każdym późniejszym okresie może przyjąć dowolną wartość od 0
    do 1. Rozwiązywanie kończy się, gdy jego rozwiązanie jest najwyżej 0.01 poniżej
    ograniczenia jego programu, w pieniądzu, albo po 1000 węzłach HiGHS, zależnie od
    tego, co nastąpi pierwsze, i gra najlepsze znalezione rozwiązanie. Oba limity liczą
    pracę, więc rozwiązanie powtarza się na każdym komputerze. Luka rozwiązania to
    ograniczenie minus wartość jego rozwiązania, co najmniej 0. HiGHS czyta zysk bez
    części, której żadna decyzja nie zmienia, więc gotówka początkowa i zysk
    wcześniejszych okresów zostawiają limit na 0.01. Program z kwotami powyżej 10 do
    potęgi 9 liczy pieniądz w większej jednostce, a jego limit to 0.01 tej jednostki.
    Limit czasu zegarowego 600 sekund na rozwiązanie to zabezpieczenie: przebieg z
    rozwiązaniem zatrzymanym na nim zależy od szybkości komputera, a test przeciążający
    oznacza go jako niepowtarzalny.
  - Okres kupuje tylko wtedy, gdy jego gotówka pomniejszona o to, co są winne otwarte
    zamówienia u dostawców, i o koszt jego zakupów pozostaje na poziomie minus limit
    kredytowy lub wyżej, tak jak silnik sprawdza zakup.
  - Luka rozwiązania ogranicza tylko program, który ono rozwiązuje. Późniejsze wybory
    od 0 do 1 pozwalają temu programowi wycenić plan, którego żaden przebieg nie
    zrealizuje, więc odniesienie może zarobić mniej niż najlepsza polityka o więcej niż
    luka. W świecie 5 okresów z jednym zamówieniem 4 monitorów, które potrzebuje
    16 chipów, chipy sprzedaje się w zamówieniach co najmniej 20 po 0.5000, a w okresie
    2 po 0.5500. Program okresu 1 liczy 16 chipów okresu 2 po 0.55 i jest wart 171.2.
    Odniesienie czeka, kupuje 20 chipów w okresie 2 i zarabia 169.4; zakup 20 chipów
    w okresie 1 daje 170.4. Żadna decyzja nie jest skorygowana, a każda luka jest
    poniżej 0.01.
  - `reference_optimizer(..., exact=True)` to kontrola dokładna: każdy wybór tak albo
    nie jest całkowity w każdym okresie jej programu. Gra programy o co najwyżej 100
    wyborach tak albo nie, więc służy tylko małym światom. Luka polityki odniesienia to
    zysk kontroli dokładnej minus zysk odniesienia: 1.0 w świecie powyżej. Bez minimum,
    z gotówką 10, limitem kredytowym 0, chipami za połowę ceny w okresie 2 i jeszcze
    jednym zamówieniem 1 monitora na okres 1 manifest jest liniowy, a luka polityki
    wynosi 212: odniesienie zarabia tyle, co brak decyzji.
  - Program okresu 1 daje też wartość programu zrelaksowanego. Nie jest ona granicą:
    przebieg może ją przekroczyć.
  - Program, który HiGHS uznaje za sprzeczny albo za nieograniczony lub sprzeczny, jest
    rozwiązywany jeszcze raz bez presolve. Program nadal sprzeczny albo nieograniczony
    zatrzymuje optymalizator z błędem, który podaje okres. Rozwiązanie zatrzymane na
    limicie bez rozwiązania zostawia swój okres bez decyzji, a przebieg idzie dalej.
  - HiGHS rozwiązuje program w binarnej arytmetyce zmiennoprzecinkowej, z pieniędzmi w
    jednostce: najmniejszej potędze dziesięciu, co najmniej 1, która sprowadza każdą
    kwotę programu do najwyżej 10 do potęgi 9. Decyzje zachowują swoje jednostki, a
    wartość programu jest w jednostkach 1. Przed każdym rozwiązaniem optymalizator
    zatrzymuje się z `UnsupportedScaleError`, błędem, który podaje okres, gdy program
    leży poza tą skalą: liczba jednostek, godzin albo miejsca przekracza 10 do potęgi 9
    albo koszt spada w jednostce pieniędzy do 10 do potęgi -9 lub niżej, gdzie HiGHS go
    pomija. W jednym okresie z jednym monitorem w zapasie i zamówieniem na niego po
    cenie 10 do potęgi 18 wysyłka zarabia 999999999999999999.0001: jednostka to 10 do
    potęgi 9, koszt 0.0005 zakupu 0.001 chipa spada poniżej 10 do potęgi -9, a
    odniesienie zatrzymuje się w okresie 1. Przy cenie 10 do potęgi 15 i chipach do 1 na
    okres jednostka to 10 do potęgi 7, a odniesienie zarabia 999999999999999.0001.
  - Przebieg odniesienia na `steady-market` fabryki przykładowej trwa około 83 minut,
    gdy 14 światów gra naraz na 14 logicznych procesorach.
- Skutek dla badania: Na fabryce przykładowej odniesienie to dobry zestaw decyzji, a nie
  zestaw udowodniony jako najlepszy. Agent może zarobić większy zysk niż odniesienie;
  jego znormalizowany wynik jest wtedy powyżej 1. Świat, w którym odniesienie nie daje
  większego zysku niż brak decyzji, nie ma znormalizowanego wyniku; test przeciążający
  go liczy, pomija w każdym wyniku i wypisuje z zyskami jego przebiegów. Odniesienie
  nigdy nie anuluje zamówienia u dostawcy i wykonuje przesunięcia okresu w kolejności
  swoich tras, więc w takim świecie anulowanie albo inna kolejność przesunięć może dać
  więcej. Interfejs HTTP przyjmuje kwoty do 10 do potęgi 24, więc przyjęty przez niego
  świat może leżeć poza skalą programu. Taki świat nie ma odniesienia ani
  znormalizowanego wyniku; test przeciążający wypisuje go wśród naruszeń z jego
  scenariuszem, ziarnem i błędem.
- Co zrobić: Przy każdym wyniku podawaj luki rozwiązań: `gap` każdego rozwiązania w
  `solves` optymalizatora, w pieniądzu, tak samo dla rozwiązania zatrzymanego na limicie
  luki, jak dla zatrzymanego na limicie węzłów. Lukę polityki, zmierzoną kontrolą
  dokładną na małych światach, podawaj osobno od nich. Zanim użyjesz znormalizowanego
  wyniku, sprawdź, czy odniesienie daje w każdym świecie większy zysk niż brak decyzji.
  Jednostki, godziny i miejsce świata trzymaj najwyżej na 10 do potęgi 9, a jego kwoty w
  granicach 10 do potęgi 18 razy jego najmniejsza cena, koszt albo wartość na jednostkę;
  badanie dużych cen liczy pieniądze w tysiącach albo milionach. Zobacz
  [Znormalizowany wynik](../benchmark/score.md#przykład).

## Przebiegi różnych wersji

- Czym jest: Każda zmiana reguł fabryki, obserwacji lub miar podnosi wersję pakietu.
  Taka zmiana może zmienić przebieg z tym samym manifestem, scenariuszem, ziarnem
  i decyzjami. Przebieg powtarza się tylko z wersjami, które go zapisały: tym samym
  pakietem i numpy oraz Pythonem z tymi samymi dwiema pierwszymi częściami wersji.
- Skutek dla badania: Dwa przebiegi różnych wersji mogą się różnić regułami, a nie
  tylko decyzjami. Badanie, które je porównuje, nie umie odróżnić jednego od drugiego.
- Co zrobić: Graj każdy przebieg jednego badania jedną wersją pakietu. Podawaj wersję
  przy każdym wyniku. Aby porównać z przebiegiem wcześniejszej wersji, zagraj tym
  agentem jeszcze raz w wersji badania. Zobacz
  [Losowość i uczciwość](../rules/randomness-and-fairness.md#wersje-i-odtwarzanie).

## Zyski różnych światów

- Czym jest: Świat jest ustalony przez manifest, scenariusz i ziarno. Jedno ziarno
  losuje większy popyt niż inne, a jeden scenariusz tnie dostawy tam, gdzie inny nie.
- Skutek dla badania: Zysków różnych światów nie można porównywać wprost. Średnia
  zysków po scenariuszach idzie za scenariuszem z największymi liczbami. Agent
  zagrany na ziarnie 1 w porównaniu z innym zagranym na ziarnie 2 jest porównywany
  w takim samym stopniu po szczęściu jak po decyzjach.
- Co zrobić: Porównuj agentów w obrębie jednego świata, ziarno po ziarnie. Między
  światami używaj znormalizowanego wyniku. Umieszcza on zysk między brakiem decyzji
  a odniesieniem jego własnego świata. Zobacz
  [Znormalizowany wynik](../benchmark/score.md#przykład).

## Ekonomia manifestu wygenerowanego

- Czym jest: W domyślnej ekonomii manifest wygenerowany losuje cenę każdego produktu
  klienta w zakresie cen fabryki przykładowej, niezależnie od kosztu jego produktu.
  Receptura ma do 4 wejść na każdym poziomie, więc produkt może kosztować więcej, niż
  płaci którykolwiek klient. Przy 4 materiałach, 4 komponentach i 1 obiekcie każdego
  innego rodzaju, ziarno 2, produkt kosztuje co najmniej 213.1738 za sztukę, a
  wysłana sztuka jest warta najwyżej 179.6824; od gotówki 0 i bez zapasu brak decyzji
  i odniesienie zarabiają tyle samo, a świat nie ma znormalizowanego wyniku.
- Skutek dla badania: W domyślnej ekonomii liczby obiektów zmieniają ekonomię, a nie
  tylko wielkość: przy większej liczbie obiektów większa część produktów klienta nie
  daje marży. Różnica między dwiema wielkościami miesza wtedy wielkość z tym, czy
  produkcja się opłaca.
- Co zrobić: W badaniu skali generuj manifesty z `"economy": "matched"`, podawaj
  profil ekonomiczny każdego manifestu obok jego wyników i zostawiaj w wynikach każdy
  świat bez znormalizowanego wyniku, z jego zyskami. Zobacz
  [Większe manifesty](../guides/larger-manifests.md#ekonomia-manifestu-wygenerowanego).

## Kalibracja biblioteki scenariuszy

- Czym jest: Biblioteka scenariuszy jest kalibrowana testem przeciążającym na trzy cele:
  każdy scenariusz da się ocenić, jest dość trudny i zmienia swoją nazwaną miarę
  w spodziewanym kierunku; zobacz
  [Test przeciążający](../benchmark/stress-test.md#kalibracja).
- Skutek dla badania: Scenariusz, który nie jest dość trudny, poszerza lukę buforowego
  optymalizatora kroczącego do odniesienia mniej, niż wymaga cel. Scenariusz, którego
  straty uniknie tylko polityka znająca zakłócenie, zanim się zacznie, nie ma werdyktu.
  Badanie na innych ziarnach, na innym manifeście albo na własnym scenariuszu nie jest
  skalibrowane.
- Co zrobić: Uruchom test przeciążający na scenariuszach i ziarnach badania i odczytaj
  jego tabelę `## Calibration`. Zobacz
  [Test przeciążający](../benchmark/stress-test.md#najmniejszy-przykład).

## Liczby fabryki przykładowej

- Czym jest: Liczby fabryki przykładowej to oszacowania, każde z zapisanym powodem,
  takim jak cena rynkowa albo zmiana 8 godzin. Nie są zmierzone w prawdziwej fabryce.
  Dla żadnej z nich nie jest cytowane badanie ani dokument.
- Skutek dla badania: Wynik dotyczy tej fabryki. Nie pokazuje, jak agent radzi sobie
  w prawdziwej fabryce albo w fabryce o innych proporcjach.
- Co zrobić: Przy każdym wyniku podawaj fabrykę. Aby sprawdzić, czy wynik dotyczy
  czegoś więcej, powtórz badanie na manifestach wygenerowanych z liczby obiektów albo
  na scenariuszach z innymi liczbami. Zobacz
  [Przykładowy zakład i gotówka](../library/example-plant-and-cash.md#źródła-liczb).

## Optymalizatory z ograniczoną wiedzą

- Czym jest: Optymalizatory z ograniczoną wiedzą znają tylko to, co zna agent. Liczą
  każdy zakres jedną wartością: zakres jednostajny środkiem `min` i `max`, zakres
  trójkątny średnią `min`, `mode` i `max`, a zakres normalny i logarytmicznie normalny
  średnią rozkładu obciętego do `min` i `max`, którą opis przebiegu podaje jako
  `cut_mean`. Ukryte parametry stosują założenia z
  [tabeli optymalizatorów](../benchmark/optimizers.md#optymalizatory). Nie trzymają
  zapasu na wypadek pecha poza wartością końcową na końcu swojego okna.
- Skutek dla badania: Planują tylko dla spodziewanego świata. Popyt logarytmicznie
  normalny, z długim ogonem powyżej mediany, jest planowany według swojego `cut_mean`.
- Co zrobić: Traktuj je jako punkty porównania, które planują z wartościami
  spodziewanymi, a nie jako najlepsze, co może zrobić agent z tą samą wiedzą. Zobacz
  [Optymalizatory](../benchmark/optimizers.md#optymalizatory).

## Utracone i odrzucone sztuki

- Czym jest: Sztuka utracona w drodze albo odrzucona przy kontroli nic nie kosztuje
  kupującego: dostawca ponosi koszt swoich odrzutów, tak samo każdy dostawca.
- Skutek dla badania: Kupujący może zamówić więcej, aby nadrobić przerwę w dostawach
  albo spadek jakości, do największego zamówienia dostawcy i swojej gotówki.
- Co zrobić: Czytaj `units_lost_in_delivery` i `units_rejected_at_inspection` każdego
  dostawcy obok zysku.

## Anulowanie zamówienia u dostawcy

- Czym jest: Część zamówienia u dostawcy, która nie dotarła, można anulować, dopóki nie
  dotrze, spóźniona lub nie. Opłata za anulowanie za sztukę to cena tej możliwości.
- Skutek dla badania: Agent może kupić wcześnie i anulować to, czego już nie
  potrzebuje, za opłatą. Badanie kupowania z wyprzedzeniem wlicza opłaty w koszt.
- Co zrobić: Czytaj `cancellation_fee` i `units_cancelled` każdego dostawcy obok zysku.

## Zysk do tej pory i wartość odzysku

- Czym jest: `profit_so_far` pomija wartość odzysku zapasu; zawiera ją tylko wynik
  przebiegu.
- Skutek dla badania: `profit_so_far` ostatniego okresu różni się od zysku przebiegu
  o wartość odzysku zapasu na końcu.
- Co zrobić: Oceniaj przebieg według `profit` jego wyniku przebiegu.

## Polskie tłumaczenie

- Czym jest: Strony po polsku to tłumaczenie stron po angielsku. Test porównuje poziomy
  nagłówków, bloki kodu, diagramy Mermaid i liczby każdej polskiej strony z jej
  angielską stroną; żadne sprawdzenie nie porównuje zdań.
- Skutek dla badania: Polskiej stronie może brakować zdania z jej angielskiej strony.
- Co zrobić: Gdy obie strony się różnią, obowiązuje strona angielska.
