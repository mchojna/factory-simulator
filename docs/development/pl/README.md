# Symulator fabryki

Symulator fabryki to narzędzie badawcze do porównywania agentów, którzy planują pracę
jednej fabryki okres po okresie. Symulator działa przez HTTP i zapisuje każdy przebieg.

## Ścieżka czytania

Czytaj sześć sekcji po kolei albo zacznij od szybkiego startu i przejdź do zasad.

```mermaid
flowchart LR
    start[Start] --> rules[Zasady]
    rules --> library[Biblioteka]
    library --> benchmark[Benchmark]
    benchmark --> guides[Poradniki]
    guides --> reference[Dokumentacja techniczna]
```

## Start

- [Przegląd](start/overview.md): działanie symulatora i jego zawartość.
- [Szybki start](start/quick-start.md): instalacja, uruchomienie serwera i pierwszy
  przebieg.
- [Pojęcia](start/concepts.md): fabryki, światy, przebiegi, agenci i programy badania.

## Zasady

- [Okres](rules/period.md): sześć kroków okresu.
- [Decyzje](rules/decisions.md): decyzje, kolejność wykonania i powody odrzucenia.
- [Informacje](rules/information.md): obserwacje, prognozy i ukryte parametry.
- [Dostawcy](rules/suppliers.md): katalogi, zamówienia i dostawy.
- [Klienci i popyt](rules/customers-and-demand.md): popyt, zamówienia, wysyłki i kary.
- [Produkcja](rules/production.md): receptury, linie, czas pracy, zużycie i naprawy.
- [Magazyny i trasy](rules/warehouses-and-routes.md): składowanie i przesyłanie zapasów.
- [Gotówka i zysk](rules/cash-and-profit.md): limit kredytowy, płatności i zysk.
- [Zakłócenia](rules/disruptions.md): zakłócenia zapisane i losowe.
- [Grupy](rules/groups.md): wspólne wartości domyślne, cele i miary.
- [Losowość i uczciwość](rules/randomness-and-fairness.md): ziarna, światy i
  odtwarzanie.

## Biblioteka

- [Fabryka przykładowa](library/example-factory.md): pozycje, receptury, dostawcy,
  klienci i grupy fabryki.
- [Przykładowy zakład i gotówka](library/example-plant-and-cash.md): produkcja,
  magazyny, trasy, gotówka i szacunki.
- [Biblioteka scenariuszy](library/scenario-library.md): scenariusze dołączone do
  pakietu.

## Benchmark

- [Rozgrywanie przebiegu](benchmark/playing-a-run.md): klient HTTP, pętla przebiegu i
  odgałęzienia.
- [Optymalizatory](benchmark/optimizers.md): siedem optymalizatorów benchmarku
  i diagnostyczny optymalizator poinformowany.
- [Znormalizowany wynik](benchmark/score.md): porównywanie zysku w obrębie jednego
  świata.
- [Test przeciążający](benchmark/stress-test.md): sprawdzenia przebiegów, kalibracja
  i bieżące wyniki.

## Poradniki

- [Pisanie manifestu](guides/writing-a-manifest.md): mały manifest, walidacja i błędy.
- [Większe manifesty](guides/larger-manifests.md): generowanie manifestów i skala.
- [Pisanie scenariusza](guides/writing-a-scenario.md): popyt, prognozy i zakłócenia.

## Dokumentacja techniczna

- [Interfejs HTTP](reference/http-interface.md): ścieżki HTTP, treści żądań i błędy.
- [Pola manifestu](reference/manifest-fields.md): wszystkie klucze manifestu i ich
  wartości domyślne.
- [Pola scenariusza](reference/scenario-fields.md): wszystkie klucze scenariusza i ich
  wartości domyślne.
- [Glosariusz](reference/glossary.md): terminy używane w dokumentacji.
- [Ograniczenia](reference/limits.md): ograniczenia i kwalifikacje badań.
- [Miary i zapis przebiegu](reference/measures-and-the-record.md): zapisane miary,
  tabele i eksporty.
- [Zapis operacji](reference/operational-record.md): operacje HTTP, starty i zamknięcia
  zapisane obok zapisu przebiegu.
- [Pytania](reference/faq.md): często zadawane pytania.
