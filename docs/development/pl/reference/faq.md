# Pytania

Krótkie stwierdzenia o częstych sprawach, każde ze stroną, która podaje jego regułę.

## Przebieg nie wymaga modelu językowego

Symulator nie używa modelu językowego. Agent to dowolny program albo człowiek,
który zwraca decyzje. Optymalizatory pakietu rozwiązują programy liniowe i mieszane
całkowitoliczbowe. Zobacz [Optymalizatory](../benchmark/optimizers.md#optymalizatory).

## To samo ziarno daje ten sam świat

Ten sam manifest, scenariusz i ziarno dają ten sam świat, cyfra w cyfrę, na Linuksie,
macOS i Windows, przy tych samych wersjach. Każdy agent spotyka wtedy ten sam popyt,
te same dostawy, uzyski, awarie i zakłócenia. Przebieg zależy też od decyzji: te same
decyzje w tym samym świecie dają ten sam zapis przebiegu, poza identyfikatorem
przebiegu i wersjami. Zobacz
[Losowość i uczciwość](../rules/randomness-and-fairness.md).

## Agent widzi przyszłość tylko w prognozach i zapowiedziach

Agent dostaje opis raz i obserwację w każdym okresie. Żadne z nich nie zawiera
ziarna, świata ani popytu, dostaw, uzysków i awarii nadchodzących okresów. Agent
widzi naprzód tylko przez prognozy i zakłócenia z zapowiedzią, które daje scenariusz.
Każdy, kto wywołuje interfejs HTTP, może przeczytać manifest i scenariusz razem z ich
zakłóceniami zapisanymi. Agent czyta tylko opis, swoje obserwacje, już zamknięte
okresy swojego przebiegu i wyniki swoich sprawdzeń. Zobacz
[Informacje](../rules/information.md#czego-nigdy-nie-widać).

## Odrzucona decyzja podaje przyczynę

Decyzja jest odrzucana, gdy łamie regułę fabryki, na przykład wysyłka większa niż zapas.
Jej wynik decyzji, w następnej obserwacji, podaje powód i, dla większości powodów,
liczby `asked` i `available`. Ścieżka `POST /api/v1/runs/{id}/checks` daje te same
wyniki decyzji przed zgłoszeniem. Zgłoszenie odrzucone z 409 lub 422 to inna rzecz: jego
treść łamie postać albo podaje inny okres, całe zgłoszenie jest odrzucane, a przebieg
zostaje w swoim okresie. Zobacz [Decyzje](../rules/decisions.md#powody-odrzucenia) i
[Interfejs HTTP](http-interface.md#błędy).

## Gotówka może spaść poniżej zera

Gotówka poniżej zera płaci odsetki od debetu do poziomu minus limit kredytowy, a poniżej
niego wyższe odsetki od przekroczenia limitu. Z powodu gotówki odrzucany jest tylko
zakup: gdy gotówka, pomniejszona o to, co są winne otwarte zamówienia u dostawców, i o
koszt zakupu, spadłaby poniżej minus limit kredytowy. Koszty, które nie są zakupami,
wciąż mogą zabrać gotówkę poniżej limitu. Zobacz
[Gotówka i zysk](../rules/cash-and-profit.md#limit-kredytowy-przy-zakupach).

## Agentów porównuje się na tych samych ziarnach

Zagraj obydwoma na tym samym manifeście, scenariuszu i ziarnach, aby każda para
przebiegów spotkała ten sam świat. Porównuj ich ziarno po ziarnie. Między scenariuszami
używaj znormalizowanego wyniku. Umieszcza on zysk między brakiem decyzji a odniesieniem
jego własnego świata. Zobacz
[Losowość i uczciwość](../rules/randomness-and-fairness.md#ten-sam-świat-dla-każdego-agenta),
[Znormalizowany wynik](../benchmark/score.md#przykład) i
[Ograniczenia](limits.md#zyski-różnych-światów).

## Wynik podaje wersje

Eksport przebiegu zawiera wersję pakietu oraz wersje numpy i Pythona: `package_version`,
`numpy_version` i `python_version` w `run.json`. Razem z nimi podaj nazwę i
identyfikator manifestu oraz scenariusza, ziarna i ustawienia każdego agenta. Przebiegów
różnych wersji się nie porównuje. Zobacz
[Miary i zapis przebiegu](measures-and-the-record.md#podawanie-wersji) i
[Ograniczenia](limits.md#przebiegi-różnych-wersji).
