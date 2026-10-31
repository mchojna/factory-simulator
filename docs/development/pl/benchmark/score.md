# Znormalizowany wynik

Znormalizowany wynik porównuje agenta z odniesieniem w tym samym świecie.

## Znaczenie wyniku

- Znormalizowany wynik to część drogi od braku decyzji do odniesienia w jednym
  świecie. Porządkuje agentów w tym świecie.
- Odniesienie to polityka heurystyczna, a jego rozwiązania ograniczają tylko własne
  programy (zobacz
  [Ograniczenia](../reference/limits.md#odniesienie-limity-pracy-i-luka)). Wynik powyżej
  1 to agent, który zarabia więcej niż odniesienie. 1 minus wynik nie jest częścią
  najlepszego zysku, której agent nie osiąga.
- Świat bez znormalizowanego wyniku to świat, w którym odniesienie nic nie zyskuje
  względem braku decyzji; lepsza polityka może tam jednak istnieć. W świecie
  5 okresów od gotówki 10 z limitem kredytowym 0 zamówienie 1 monitora utracone
  w okresie 1 zabiera gotówkę, a chipy na zamówienie 4 monitorów kosztują w okresie 2
  połowę ceny. Odniesienie czeka na tę cenę, a potem nie może kupić: zarabia -50, tak
  jak brak decyzji. Zakup w okresie 1 daje 162.
- Odniesienie nigdy nie anuluje zamówienia u dostawcy. W świecie 3 okresów bez popytu
  zamówienie startowe 10 chipów po 0.5000 przychodzi w okresie 2, a chip jest wart
  na końcu 0.1000. Brak decyzji i odniesienie zatrzymują chipy i zarabiają -4, więc
  świata nie da się ocenić. Anulowanie zamówienia w okresie 1 kosztuje tylko opłatę
  za anulowanie: bez opłaty daje 0.
- Odniesienie wykonuje przesunięcia okresu w kolejności swoich tras, według nazwy
  źródła, a potem celu. W świecie 1 okresu bez popytu pełny magazyn `main`
  o pojemności 0.020 trzyma 2 chipy o miejscu 0.010, a pełny magazyn `annex` trzyma
  1 płytkę o miejscu 0.020, której składowanie kosztuje tam 100 na okres, a w `main` 1.
  Darmowe trasy o czasie realizacji 0 prowadzą z `annex` do `main` i z `main` do
  pustego `buffer` o pojemności 0.020. Trasa z `annex` idzie pierwsza, do pełnego
  `main`, więc odniesienie zostawia płytkę w `annex` i zarabia -99.3, tak jak brak
  decyzji. Wysłanie najpierw chipów do bufora, a potem płytki daje -0.3.
- Odniesienie liczy przezbrojenia okresu dla jednej kolejności swoich produkcji.
  W świecie 3 okresów pełny magazyn o pojemności 1 trzyma 60 chipów o miejscu 0.010
  i 4 płytki o miejscu 0.100. Linia o 3 godzinach, ustawiona na płytki, robi
  w okresie 1 2 płytki i 1 monitor o miejscu 0.020, 1 godzinę na sztukę, z kosztem
  przezbrojenia 0.1000 na każdą pozycję. Program liczy 1 przezbrojenie, dla płytek
  najpierw. 2 płytki dodają 0.16, a monitor zwalnia 0.18, więc odniesienie robi
  najpierw monitor, płaci 2 przezbrojenia i zarabia 144.3. Z przezbrojeniem na płytki
  trwającym 0.5 godziny płytki potrzebują potem 2.5 z 2 pozostałych godzin,
  sprawdzenie je odrzuca, a odniesienie zarabia 89.9.

## Przykład

Zysków z różnych światów nie da się porównać: jedno ziarno losuje większy popyt niż
inne. Znormalizowany wynik umieszcza zysk między dwoma przebiegami tego samego świata,
czyli tego samego manifestu, scenariusza i ziarna:

```text
normalized score = (profit - profit of no decisions)
                   / (profit of the reference - profit of no decisions)
```

- Brak decyzji ma znormalizowany wynik 0, a odniesienie 1. Znormalizowany wynik
  poniżej 0 oznacza mniejszy zysk niż brak decyzji, a wynik powyżej 1 większy zysk niż
  odniesienie.
- Znormalizowany wynik to `Decimal`, zaokrąglony połówkowo do parzystej do 12 miejsc
  po przecinku.
- Świat, w którym odniesienie nie daje więcej zysku niż brak decyzji, nie ma
  znormalizowanego wyniku: nie da się go ocenić.
- W kalibracji biblioteki scenariuszy na ziarnach 0 do 4 odniesienie daje więcej zysku
  niż brak decyzji w każdym świecie.
- Odniesienie gra swoje decyzje przez symulator. Jego optymalizator przechowuje też
  wartość programu zrelaksowanego okresu 1, w `relaxed_program_value`: programu, w
  którym każdy wybór tak albo nie może przyjąć dowolną wartość od 0 do 1. Nie jest to
  ograniczenie: przebieg może dać większy zysk.

W przebiegu `steady-market` na fabryce przykładowej z ziarnem 0 brak decyzji daje
-675663.4617, odniesienie 1144661.93211454, a optymalizator kroczący 1007491.89663264.
Znormalizowany wynik optymalizatora kroczącego to:

```text
(1007491.89663264 + 675663.4617) / (1144661.93211454 + 675663.4617)
= 1683155.35833264 / 1820325.39381454
= 0.924645321134
```
