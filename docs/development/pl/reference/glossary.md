# Glosariusz

Każda strona używa tych słów w tych znaczeniach. Kolumna "Termin angielski" podaje
słowo z angielskiej wersji dokumentacji. Słowo w ostatniej kolumnie znaczy to samo
w innych narzędziach lub pracach; dokumentacja go nie używa.

## Przebiegi i dane wejściowe

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| przebieg | run | Jeden agent planujący jeden świat od pierwszego do ostatniego okresu. | episode, game, session, simulation |
| okres | period | Jeden krok czasu w przebiegu, numerowany od 1. Nie ma daty w kalendarzu. | week, tick, round, turn |
| horyzont | horizon | Liczba okresów w przebiegu. | length, duration |
| manifest | manifest | Dokument opisujący fabrykę: jej pozycje, partnerów, linie, magazyny, grupy i ich parametry. | config, world config, factory config |
| scenariusz | scenario | Dokument opisujący, jak przebieg zmienia się w czasie: horyzont, stan początkowy, kształty popytu, prognozy, zakłócenia i ukryte grupy parametrów. | case, setting |
| ziarno | seed | Liczba całkowita podana na początku przebiegu. Z niej losowana jest każda losowa wartość świata. | random state, world seed, run seed |
| świat | world | Wszystkie wartości wylosowane z ziarna dla przebiegu, ustalone przed pierwszym okresem. | tape, realization, sample |
| parametr | parameter | Liczba w manifeście lub scenariuszu, która zmienia to, co dzieje się w przebiegu. Jest stałą liczbą albo zakresem. | setting, knob, constant |
| zakres | range | Najniższa i najwyższa wartość z rozkładem między nimi, z którego losuje się parametr. | interval, spread, bounds |
| pole opisowe | descriptive field | Nazwa, jednostka lub opis, który pomaga człowiekowi czytać manifest lub scenariusz. Nie zmienia przebiegu. | label, metadata, comment |
| grupa | group | Zbiór obiektów jednego typu, które mają wspólne wartości domyślne, mogą być celem zakłócenia i mają własne miary, na przykład region dostawców albo segment produktów. | tag, label, class, cluster |
| manifest liniowy | linear manifest | Manifest, w którym żaden wpis katalogu nie podaje minimalnej ilości ani rabatów i żaden wpis linii nie podaje czasu ani kosztu przezbrojenia. Nazwa opisuje tylko katalog i linie: jego program nadal ma wybór kredytowy w każdym okresie z zakupem. | LP mode, simple manifest |
| manifest z korzyściami skali | economies-of-scale manifest | Manifest, w którym wpis katalogu podaje minimalną ilość lub rabaty albo wpis linii podaje czas lub koszt przezbrojenia. Jego program ma dla nich wybory tak albo nie, obok wyborów kredytowych. Wartość 0 nie dodaje żadnej zmiennej całkowitoliczbowej. | nonlinear manifest, integer manifest, MILP mode, complex manifest |
| manifest wygenerowany | generated manifest | Manifest utworzony przez symulator z liczby obiektów i ziarna. Te same liczby i to samo ziarno dają ten sam manifest. | random manifest, synthetic factory |
| ekonomia dopasowana | matched economy | Ekonomia manifestu wygenerowanego, w której cena każdego produktu klienta to najniższy koszt jego produktu razy stosunek od 1.8124 do 2.4250, więc każdy produkt klienta daje marżę przy każdej liczbie obiektów. Domyślna ekonomia, `unrestricted`, losuje ceny w zakresie cen fabryki przykładowej. | productive mode, balanced economy |
| profil ekonomiczny | economic profile | To, co tekst manifestu wygenerowanego mówi o jego ekonomii przed jakimkolwiek przebiegiem: najniższy koszt, najlepsza marża i wartość obsługi każdego produktu klienta, pokrycie użytecznego popytu, udział marży i klasa `profitable`, `penalty-driven` albo `unproductive`. | economic controls, economic qualification |
| ukryta grupa parametrów | hidden parameter group | Parametr, w każdym obiekcie, który go ma, którego wartość lub zakres scenariusz ukrywa przed agentem. | secret, masked field |
| ścieżka klucza | key path | Klucze od góry manifestu lub scenariusza do jednej wartości, połączone kropkami, na przykład `materials.*.space`. | JSON path, pointer |

## Pozycje i receptury

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| pozycja | item | Wszystko, co fabryka przechowuje: materiał, komponent lub produkt. | SKU, part, good, stock keeping unit |
| materiał | material | Pozycja kupowana od dostawcy. | raw material, input, commodity |
| komponent | component | Pozycja wytwarzana na linii z materiałów. | part, subassembly, intermediate |
| produkt | product | Pozycja wytwarzana na linii z komponentów i sprzedawana klientom. | finished good, SKU, article |
| receptura | recipe | Nazwana lista pozycji wejściowych i ich ilości potrzebnych do wytworzenia jednej sztuki komponentu lub produktu. Pozycja może mieć kilka receptur. | bill of materials, BOM, formula |

## Partnerzy

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| dostawca | supplier | Firma, która sprzedaje fabryce materiały. | vendor, source |
| katalog | catalogue | Materiały, które sprzedaje jeden dostawca, każdy z ceną i parametrami dostaw. | offer, price list |
| wpis katalogu | catalogue entry | Jeden materiał w katalogu dostawcy, z ceną i parametrami dostaw. | offer line, SKU |
| klient | customer | Firma, która kupuje od fabryki produkty. | client, buyer, account |
| produkt klienta | customer product | Jeden produkt, który kupuje klient, z ceną, popytem i karami. Jego miary są pod kluczem `pairs.<customer>/<product>`. | account product, pair |

## Fabryka

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| linia | line | Linia produkcyjna, która wytwarza komponenty lub produkty w jednym magazynie. | machine, workstation, resource |
| wpis linii | line item | Jedna pozycja, którą wytwarza linia, z godzinami, kosztem i uzyskiem na sztukę. | routing, operation |
| zdolność (linii), pojemność (magazynu) | capacity | Godziny produkcji, które linia ma w jednym okresie; dla magazynu miejsce, które ma. | throughput, availability |
| godziny dostępne | hours available | Zwykłe godziny linii w okresie: jej zdolność razy cięcie razy jej stan. | uptime, free hours |
| wykorzystanie | utilisation | Zwykłe godziny produkcji i przezbrojeń linii podzielone przez jej zdolność. | load, occupancy, efficiency |
| stan | condition | Stan linii, od 0 do 1. Linia może użyć do produkcji swojej zdolności razy swój stan; przy 0 nic nie wytwarza. | health, quality, wear level |
| zużycie | wear | Utrata stanu w okresie, przez upływ czasu i przez godziny produkcji. | degradation, ageing |
| awaria | breakdown | Nagła utrata części stanu linii. | failure, fault |
| naprawa | repair | Przywrócenie stanu linii, wybrane przez agenta. | maintenance, fix |
| nadgodziny | overtime | Dodatkowe godziny produkcji linii w okresie, za koszt za godzinę. | extra shift, overload |
| przezbrojenie | changeover | Godziny i koszt ustawienia linii na pozycję, z innej pozycji albo z żadnej. | setup, switch, retooling |
| produkcja | production | Ilość pozycji rozpoczęta na linii w jednym okresie, aż trafi do zapasu. | run, job, work in progress |
| partia | batch | Produkcje jednej linii i pozycji rozpoczęte w jednym okresie. Ich dobre sztuki są zaokrąglane raz, razem. | lot, production run |
| pobór pozycji wejściowych | input use | Sztuki pozycji, które produkcja zabiera z zapasu jako swoje pozycje wejściowe. | consumption, usage |
| plan | plan | Produkcja zdecydowana w jednym okresie, która ma ruszyć w późniejszym okresie. | schedule, booking |
| uzysk | yield | Część rozpoczętych sztuk, które wychodzą dobre. | quality, efficiency |
| braki | scrap | Rozpoczęte sztuki, które wychodzą złe. Ich pozycje wejściowe przepadają. | waste, defects, rejects |
| czas realizacji | lead time | Liczba okresów, jaką coś trwa: od złożenia zamówienia u dostawcy do dostawy, od zamówienia klienta do okresu terminu, od rozpoczęcia produkcji do zapasu albo wzdłuż trasy. | latency, cycle time |

## Magazynowanie

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| magazyn | warehouse | Miejsce składowania z pojemnością, które przechowuje pozycje, jakie przyjmuje. | inventory, storage, stock room, location |
| miejsce | space | Miejsce, jakie pozycja zajmuje w magazynie, i miejsce, jakie ma magazyn. | volume, size |
| zapas | stock | Ilość pozycji w magazynie. | inventory, on hand |
| trasa | route | Jednokierunkowe połączenie dwóch magazynów z kosztem za sztukę i czasem realizacji. | lane, link, path |
| współczynnik składowania | storage factor | Czynnik magazynu, który mnoży koszt składowania jego zapasu. | storage multiplier |
| współczynnik transportu | transport factor | Czynnik magazynu, który mnoży koszt transportu wysyłek z niego. | transport multiplier |
| przesunięcie | transfer | Ilość pozycji przeniesiona trasą z jednego magazynu do innego. | move, shipment, relocation |

## Zamówienia i przepływy

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| zamówienie u dostawcy | supplier order | Zamówienie materiału złożone u dostawcy. | purchase order, PO, procurement |
| zamówienie ekspresowe | express order | Zamówienie u dostawcy z krótszym czasem realizacji za dodatkową cenę za sztukę. Jego wartości dostawy losuje się osobno od wartości zwykłych zamówień tego samego okresu. | rush order, expedite |
| minimalna ilość | minimum quantity | Najmniejsza ilość, jaką dostawca przyjmuje w jednym zamówieniu materiału. | MOQ, minimum order |
| rabat | discount | Niższa cena za sztukę dla każdej sztuki zamówienia, które osiąga daną ilość. | rebate, volume price, price break |
| próg rabatu | discount tier | Ilość, od której zamówienie materiału płaci niższą cenę za każdą sztukę. | price break, bracket |
| dostawa | delivery | Zamówienie u dostawcy albo jego brakująca część, która dociera do swojego magazynu. | receipt, shipment |
| punktualność | punctuality | Szansa, że dostawa dotrze na czas. | reliability, on-time rate |
| kompletność | completeness | Część otwartej ilości zamówienia u dostawcy, która dociera. | fill share |
| przyjęcie | acceptance | Część ilości dostawy, która przechodzi kontrolę; tylko przyjęte sztuki trafiają do zapasu i są płacone. | pass rate, quality rate |
| opóźnienie | delay | Dodatkowe okresy, jakie spóźniona dostawa trwa po swoim czasie realizacji. | lag, slip |
| dosłanie | backfill | Późniejsza dostawa części zamówienia u dostawcy, którą wstrzymała kompletność. | back order, redelivery |
| partia dostawy | delivery batch | Zwykłe albo ekspresowe zamówienia u dostawcy jednego dostawcy, materiału i magazynu złożone w jednym okresie, które docierają w jednym okresie, albo ich dosłania. Ich sztuki wysłane, które dotarły, i przyjęte są zaokrąglane raz, razem. | shipment, consignment |
| anulowanie | cancellation | Koniec planu albo tej części zamówienia u dostawcy, która nie dotarła; to drugie za opłatą za sztukę. | withdrawal, abort |
| popyt bazowy | base demand | Ilość produktu, jaką klient zamówiłby w okresie przed kształtami popytu i zakłóceniami. | mean demand, baseline |
| kształt popytu | demand shape | Czynnik w czasie, który mnoży popyt bazowy: trend, sezon, skok, rampa lub krzywa S. | pattern, profile, curve |
| trwałość popytu | persistence | Część popytu bazowego poprzedniego okresu, która przechodzi na następny. | autocorrelation, memory, inertia |
| część wspólna | common share | Dla jednego produktu część zmienności popytu, którą wszyscy jego klienci mają wspólną w okresie, od 0 do 1, przy tej samej całkowitej zmienności. Przy 0 popyt każdego klienta zmienia się osobno. | correlation, common factor, shared shock |
| zamówienie klienta | customer order | Zamówienie produktu złożone przez klienta. | sales order, demand, request |
| okres terminu | due period | Okres, do którego zamówienie klienta powinno zostać wysłane. | deadline, due date, promise date |
| cierpliwość | patience | Liczba okresów po okresie terminu, przez które klient czeka, zanim reszta zamówienia przepadnie. | grace period, tolerance |
| wysyłka | shipment | Sztuki produktu wysłane z magazynu do klienta dla jednego zamówienia klienta. Wysyłka dociera do klienta w okresie, w którym zostaje wysłana; droga do klienta nie zajmuje czasu. | delivery, dispatch, fulfilment |
| utracona sprzedaż | lost sale | Część zamówienia klienta, która nigdy nie zostaje wysłana, bo skończyła się cierpliwość albo przebieg skończył się w okresie terminu lub po nim. | cancellation, backlog, stockout |

## Decydowanie

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| agent | agent | Ten, kto wybiera decyzje przebiegu: program lub człowiek, który gra przez HTTP, albo optymalizator benchmarku. Dostaje opis i obserwacje i może sprawdzać decyzje bieżącego okresu. | player, policy, controller, user |
| program badania | harness | Program badania, który rozpoczyna przebieg, przekazuje agentowi opis i obserwacje oraz zgłasza jego decyzje. | runner, driver, wrapper |
| decyzja | decision | Jedno polecenie agenta: wysyłka, anulowanie, przesunięcie, naprawa, produkcja lub zakup. | action, command, move |
| zgłoszenie | submission | Decyzje jednego okresu, wysłane przez program badania w jednym żądaniu z numerem okresu. | batch, action list, turn |
| sprawdzenie | check | Żądanie, które podaje, jaki wynik miałaby teraz każda decyzja zgłoszenia, bez zmiany przebiegu. | dry run, preview |
| wynik decyzji | outcome | Co stało się z jedną decyzją zgłoszenia: przyjęta z identyfikatorem tego, co utworzyła, albo odrzucona z powodem i liczbami, które za nim stoją. | response, feedback, verdict |
| zdarzenie | event | Coś, co stało się w przebiegu, podane z krokiem i identyfikatorem obiektu, którego dotyczy, na przykład dostawa, awaria lub kara. | log entry, message, notification |
| stan przebiegu | state | Wszystko, co symulator wie o przebiegu po kroku, także to, czego agent nie może zobaczyć. | status, snapshot |
| obserwacja | observation | To, co agent widzi w jednym okresie przed decyzją. | view, prompt |
| opis | description | To, co agent dostaje raz na początku przebiegu: manifest i scenariusz oraz to, czy manifest jest liniowy. Pomija ukryte grupy parametrów, zapisane zakłócenia oraz nazwę i opis scenariusza. | world view, briefing |
| zapowiedź | notice | Liczba okresów przed początkiem zakłócenia, od której jest ono widoczne. | warning, announcement lead |
| prognoza | forecast | Oszacowanie popytu nadchodzącego okresu dane agentowi, z szumem ustawionym w scenariuszu. | prediction, outlook, projection |
| zakłócenie | disruption | Zdarzenie, które zmienia część fabryki lub jej partnerów na kilka okresów, zapisane w scenariuszu albo wylosowane z ziarna. | incident, perturbation |
| zakłócenie zapisane | written disruption | Zakłócenie zapisane w scenariuszu z rodzajem, celem, początkiem i czasem trwania. | scripted disruption, fixed disruption |
| zakłócenie losowe | random disruption | Zakłócenie wylosowane z ziarna według nazwanej reguły scenariusza, z szansą na okres i cel albo od początku zapisanego w regule. Każde zakłócenie trafia w jeden cel. | stochastic event, random event |
| kaskada | cascade | Podniesienie szansy jednej reguły zakłóceń losowych o czynnik na kilka okresów, po tym jak zaczyna się zakłócenie innej reguły. Podniesiona reguła nie podnosi kolejnej. | chain reaction, knock-on effect, contagion |
| cel | target | Obiekty, na które działa zakłócenie: lista identyfikatorów, wszystkie obiekty jednego rodzaju albo grupa. | scope, subject |

## Pieniądze i wyniki

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| gotówka | cash | Pieniądze, które ma fabryka. Mogą spaść poniżej zera i wtedy płacą odsetki. | balance, budget, funds |
| limit kredytowy | credit limit | Kwota L taka, że gotówka poniżej -L płaci odsetki według wyższej stopy przekroczenia. Zakup nie może zabrać gotówki poniżej -L, gdy liczy się otwarte zamówienia u dostawców. | budget, spending limit |
| interakcja | interaction | Sprawdzenie decyzji albo odrzucone zgłoszenie, przechowywane w zapisie przebiegu osobno od przebiegu. | probe, attempt, request log |
| odniesienie | reference | Zysk, jaki optymalizator odniesienia osiąga w świecie, gdy gra przez symulator; liczba, z którą porównuje się agentów. | optimum, upper bound |
| należność | receivable | Pieniądze, które klient jest winien za wysyłkę i jeszcze ich nie zapłacił. | invoice, debt |
| wartość odzysku | salvage value | Pieniądze, jakie pozycja w zapasie jest warta na końcu przebiegu. | residual value, scrap value |
| wartość końcowa | terminal value | Pieniądze, jakie optymalizator z oknem liczy za zapas na końcu swojego okna, przed końcem przebiegu. | end value, closing value |
| zysk | profit | Jedyna liczba, która ocenia przebieg: przychód, zapłacony lub nie, minus koszty i kary, plus wartość odzysku zapasu na końcu. | score, reward, objective |
| wynik przebiegu | result | To, co zapis przebiegu przechowuje o zakończonym przebiegu jako całości: ziarno, liczbę okresów, zysk i jego składniki, gotówkę na początku i na końcu, należności i miary całego przebiegu. | summary, totals |
| miara | measure | Liczba zapisana o przebiegu obok zysku, na przykład część sztuk wysłanych na czas. | metric, KPI, statistic |
| zapis przebiegu | record | Wszystko, co symulator przechowuje o przebiegu: co zrobił w każdym okresie, świat, do odczytu po końcu przebiegu, oraz wynik przebiegu. | log, telemetry, trace, output |
| księga kasowa | ledger | Lista każdego ruchu gotówki w przebiegu. | journal, account, cash book |
| przychód | revenue | Cena razy sztuki wysyłki; przychód powstaje w chwili wysyłki. | sales, income |
| kara | penalty | Pieniądze, które kosztuje zamówienie klienta spóźnione (kara za spóźnienie, za sztukę i okres) albo utracone (kara za utraconą sprzedaż, za sztukę). | fine, charge |
| odsetki | interest | Pieniądze zarobione od gotówki powyżej 0 albo zapłacone od gotówki poniżej 0, przy zamknięciu każdego okresu. | financing cost |
| poziom realizacji | fill rate | Sztuki wysłane podzielone przez sztuki zamówione, w całym przebiegu albo do danego okresu. | service level |
| wartość programu zrelaksowanego | value of the relaxed program | Wartość programu okresu 1, w którym każdy wybór tak albo nie może przyjąć dowolną wartość od 0 do 1. Nie ogranicza zysku przebiegu. | upper bound, ceiling |
| znormalizowany wynik | normalized score | Zysk przebiegu jako część drogi od zysku braku decyzji do odniesienia w tym samym świecie. Świat, w którym odniesienie nie daje więcej zysku niż brak decyzji, nie ma go; nie da się go ocenić. | relative score, regret |

## Usługa i badanie

| Termin | Termin angielski | Znaczenie | Inne nazwy |
| --- | --- | --- | --- |
| odgałęzienie | fork | Nowy przebieg, który powtarza zakończony przebieg do wybranego okresu z tymi samymi zgłoszeniami i dalej idzie z innymi decyzjami. | branch, copy |
| eksport | export | Jeden plik zakończonego przebiegu, który zawiera jego zapis przebiegu, manifest, scenariusz i fakty przebiegu. | dump, backup, archive |
| ponowne uruchomienie | restart | Nowe uruchomienie symulatora; niezakończony przebieg idzie wtedy dalej od swojego zapisu przebiegu. | reload, recovery |
| manifest przykładowy | example manifest | Jedyny manifest, fabryki elektroniki z korzyściami skali, który przychodzi z symulatorem. | sample factory, default manifest |
| biblioteka scenariuszy | scenario library | Scenariusze, które przychodzą z symulatorem dla manifestu przykładowego; każdy sprawdza jeden mechanizm, a kilka łączy kilka mechanizmów. | test suite, scenario set |
| stabilny rynek | steady market | Scenariusz biblioteki bez zakłóceń i kształtów popytu. Każdy inny scenariusz podaje miarę, która różni się od niego w spodziewanym kierunku. | baseline scenario, control, base case |
| benchmark | benchmark | Część pakietu, która gra przebiegi przez HTTP: klient i optymalizatory. | study package, test bench |
| optymalizator | optimizer | Agent, który rozwiązuje program zysku na nadchodzące okresy z tego, co wie, i zgłasza decyzje bieżącego okresu. | planner, LP model |
| optymalizator odniesienia | reference optimizer | Optymalizator, który dostaje cały świat przebiegu, planuje do końca przebiegu programem liniowym albo mieszanym całkowitoliczbowym i gra swoje decyzje przez symulator; narzędzie oceny. | oracle, solver |
| kontrola dokładna | exact control | Optymalizator odniesienia, w którego programie każdy wybór tak albo nie jest całkowity w każdym okresie, tylko dla małych światów. Mierzy lukę polityki odniesienia. | exact reference, oracle, optimum |
| luka polityki | policy gap | Zysk kontroli dokładnej minus zysk odniesienia w tym samym świecie. | optimality gap, regret |
| wybór kredytowy | credit choice | Wybór tak albo nie programu w okresie z zakupem: okres kupuje w granicach limitu kredytowego albo nie składa zakupu. Sprawdzenie kredytu odrzuca tylko zakup, więc decyzje, które je przechodzą, nie tworzą zbioru wypukłego, a każdy manifest potrzebuje tego wyboru. | credit binary, solvency flag |
| optymalizator z ograniczoną wiedzą | limited optimizer | Optymalizator, który wie tylko to, co wie agent, i co okres na nowo rozwiązuje swój program na oknie: optymalizator na cały horyzont, kroczący, buforowy kroczący, dopasowany i krótkowzroczny. | receding-horizon planner |
| optymalizator na cały horyzont | full-horizon optimizer | Optymalizator z ograniczoną wiedzą, którego okno sięga do horyzontu przebiegu. | |
| optymalizator kroczący | rolling optimizer | Optymalizator z ograniczoną wiedzą, którego okno to najdłuższy łańcuch czasów realizacji od zakupu do sprzedaży plus 2 okresy, z wartością końcową zapasu przy współczynniku wartości końcowej 1.01; planuje na nowo co okres. | |
| buforowy optymalizator kroczący | buffered rolling optimizer | Optymalizator kroczący ze współczynnikiem wartości końcowej 1.2 zamiast 1.01, więc kończy każde okno z większym zapasem. | safety-stock optimizer |
| optymalizator dopasowany | aligned optimizer | Optymalizator z ograniczoną wiedzą na oknie optymalizatora kroczącego, którego popyt to tylko otwarte zamówienia klientów i prognozy, które widzi. | |
| optymalizator poinformowany | informed optimizer | Optymalizator kroczący, przy współczynniku wartości końcowej 1.01 albo 1.2, który zna też zakres każdej ukrytej grupy parametrów poza czasem trwania zakłóceń, tak jak pokazuje go opis przebiegu bliźniaka bez niczego ukrytego. Nigdy nie widzi wartości losowanej na okres. Diagnostyka, a nie optymalizator z ograniczoną wiedzą. | oracle |
| efekt ujawnienia | disclosure effect | W scenariuszu, który ukrywa grupę parametrów inną niż czas trwania zakłóceń, średnia po ziarnach znormalizowanego wyniku optymalizatora poinformowanego przy współczynniku wartości końcowej 1.2 w świecie minus wynik buforowego optymalizatora kroczącego w tym samym świecie, z jej błędem standardowym oraz dolną i górną granicą jej 95-procentowego przedziału, przedziału Studenta z poprawką na skośność według Halla (1992). To odpowiedź tej polityki na zakresy ujawnione przed przebiegiem, diagnostyka, i może być ujemny. | value of learning, value of information |
| zabieg informacyjny | information treatment | Jeden klucz scenariusza, który ustala, co agent wie, i nie zmienia żadnego losowania: jego prognozy, jego ukryte grupy parametrów albo zapowiedź jego zakłóceń. | information level |
| kontrola informacyjna | information control | Scenariusz bez jednego zabiegu informacyjnego scenariusza biblioteki, taki sam w każdym innym kluczu, grany na tym samym manifeście i tych samych ziarnach. | baseline |
| efekt zabiegu | effect of a treatment | Średnia po ziarnach znormalizowanego wyniku buforowego optymalizatora kroczącego w scenariuszu minus jego znormalizowany wynik w kontroli informacyjnej tego samego ziarna, z jej błędem standardowym oraz dolną i górną granicą jej 95-procentowego przedziału, przedziału Studenta z poprawką na skośność według Halla (1992). | value of information |
| scenariusz złożony | compound scenario | Scenariusz biblioteki, który różni się od stabilnego rynku w więcej niż jednym kluczu, na przykład `forecasts` albo `hidden-groups`. Jego różnica wobec stabilnego rynku nie jest efektem zabiegu. | mixed scenario |
| optymalizator krótkowzroczny | myopic optimizer | Optymalizator z ograniczoną wiedzą, którego okno to tylko bieżący okres, z wartością końcową zapasu i zamówień w drodze. | greedy optimizer |
| brak decyzji | no decisions | Agent, który w każdym okresie zgłasza pustą listę decyzji. Jego zysk to dolny punkt znormalizowanego wyniku. | do nothing, null agent |
| okno | window | Nadchodzące okresy, na które planuje optymalizator: do horyzontu, najdłuższy łańcuch czasów realizacji od zakupu do sprzedaży plus 2 okresy albo tylko bieżący okres. | lookahead |
| portfel zamówień | order book | Otwarte zamówienia klientów przebiegu w okresie. | backlog |
| spodziewane użycie | expected use | Ilość pozycji, jaką optymalizator spodziewa się użyć w tylu okresach po swoim oknie, ile liczy najdłuższy łańcuch czasów realizacji, ale nie po końcu przebiegu, ze średniego popytu bazowego razy kształty popytu i widoczne szoki popytu każdego okresu. Ogranicza wartość końcową. | forecast use |
| koszt odtworzenia | replacement cost | Ile kosztuje zdobycie jednej sztuki pozycji: najniższa cena katalogowa materiału albo, dla pozycji wytwarzanej, koszt jej pozycji wejściowych i jej linii podzielony przez jej uzysk. | unit cost |
| rozwiązanie całkowitoliczbowe | integer solve | Jedno rozwiązanie programu mieszanego całkowitoliczbowego, z limitem, na którym się zatrzymało, jeśli jest, wartością jego rozwiązania, ograniczeniem jego programu i jego luką. | MILP call |
| luka rozwiązania | gap of a solve | Ograniczenie programu rozwiązania całkowitoliczbowego minus wartość jego rozwiązania, w pieniądzu, co najmniej 0: najwięcej, o ile jego rozwiązanie może być poniżej najlepszego rozwiązania tego programu. | MIP gap, relative gap |
| limit luki | gap limit | Luka, przy której rozwiązanie całkowitoliczbowe się zatrzymuje: 0.01 w jednostce pieniądza jego programu, niezależnie od części zysku, której żadna decyzja nie zmienia. | tolerance |
| decyzja pominięta | dropped decision | Decyzja planu, którą ostatnie sprawdzenie odrzuciło i której optymalizator nie zgłosił. | skipped decision |
| decyzja skorygowana | fitted decision | Decyzja planu, której ilość korekta zmieniła po tym, jak sprawdzenie ją odrzuciło. | adjusted decision |
| przebieg zamrożony | frozen run | Przebieg, którego decyzje i skróty jego odpowiedzi i wierszy są przechowane, aby powtarzać go w późniejszych wersjach. | reference run, golden run |
| test przeciążający | stress test | Test uruchamiany ręcznie, który gra brak decyzji i agentów benchmarku na scenariuszach biblioteki z wieloma ziarnami, sprawdza każdy przebieg i podaje wyniki oraz werdykty kalibracji. | load test, benchmark run |
| kalibracja | calibration | Pomiar, który mówi dla każdego scenariusza biblioteki, czy da się go ocenić, czy jest dość trudny i czy jego nazwana miara zmienia się w spodziewanym kierunku. O tym, czy jest dość trudny, rozstrzyga się dla scenariusza, którego odczyt nie zawiera wiedzy z góry. | tuning |
| najlepszy wynik z ograniczoną wiedzą | best limited score | Najwyższy znormalizowany wynik pięciu optymalizatorów z ograniczoną wiedzą w jednym świecie. Wartość decyzji uśrednia go po ziarnach. | envelope |
| wynik kalibracji | calibration score | W jednym świecie 1 minus luka buforowego optymalizatora kroczącego, czyli zysk odniesienia minus jego zysk, przez mianownik stabilnego rynku w tym samym ziarnie. Scenariusz jest dość trudny, gdy obniża wynik kalibracji o co najmniej 0.03 wobec stabilnego rynku. | rescaled score |
| mianownik | denominator | Zysk odniesienia minus zysk braku decyzji w jednym świecie; znormalizowany wynik dzieli się przez niego. | range, spread |
| wartość decyzji | decision value | To, co decyzje scenariusza mogą jeszcze zmienić: bezwzględne wyniki jego światów obok jego znormalizowanych wyników oraz jego odczyt, który podaje, co polityka może jeszcze zrobić, i stratę, której żadna polityka nie uniknie. | difficulty, severity |
| ziarno rozwojowe | development seed | Ziarno poniżej 1000. Każde uruchomienie testu przeciążającego bez `--stress-evaluation` gra ziarna rozwojowe. | training seed, tuning seed |
| ziarno ewaluacyjne | evaluation seed | Jedno z ziaren od 1000 do 1019, grane tylko przez ewaluację potwierdzającą. | test seed, holdout seed |
| ewaluacja potwierdzająca | confirmatory evaluation | Jedyne uruchomienie testu przeciążającego z `--stress-evaluation`: każdy scenariusz biblioteki i jego zbudowane kontrole informacyjne na ziarnach ewaluacyjnych, 520 światów, przy definicjach zamrożonych w `tests/stress/protocol.py`. | validation run, final calibration |
| raport | report | Dokument z tabelami i wykresem, który test przeciążający pisze o swoich przebiegach. | dashboard, summary, output |
| szablon | template | Manifest lub scenariusz, który pokazuje każdy klucz raz, z liczbami zastępczymi. | skeleton, sample |
