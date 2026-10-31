# Większe manifesty

Grupy, rabaty, szablony i manifesty wygenerowane tworzą większe fabryki.

## Najmniejszy przykład

Grupa daje swoim członkom wartości domyślne. Dzięki temu liczbę wspólną dla wielu
obiektów zapisuje się raz. Tutaj grupa `asia` daje swoim dostawcom czas realizacji
i punktualność, a `chip-maker` nie zapisuje żadnego z nich:

```json
{
  "groups": {
    "asia": {
      "kind": "region",
      "defaults": {
        "catalogue": {"lead_time": {"min": 2, "max": 4}, "punctuality": 0.85}
      }
    }
  },
  "suppliers": {
    "chip-maker": {
      "groups": ["asia"],
      "catalogue": {
        "chip": {"price": 2, "max_quantity": 1000, "delay": 1, "completeness": 1, "acceptance": 1}
      }
    }
  }
}
```

- Grupa ma `kind`, dowolne słowo takie jak `region`, i opcjonalne `defaults`. Członek
  wymienia swoje grupy w `groups`, najwyżej jedną z każdego rodzaju.
- `defaults` ma jeden klucz na typ parametru: `items`, `catalogue`, `line_items`,
  `customer_products`, `customers` i `lines`. Grupa daje wartości domyślne tylko pod
  kluczami, których używają jej członkowie.
- Wygrywa wartość zapisana w obiekcie. Potem idą grupy w kolejności, w jakiej obiekt
  je wymienia, a potem wbudowana wartość domyślna. Wpis katalogu pyta najpierw grupy
  dostawcy, a potem grupy materiału. Wymagany klucz bez wartości z żadnego z tych
  miejsc jest odrzucany przy kluczu członka.
- Zakres dany przez grupę jest losowany osobno dla każdego członka.
- Grupa ma członków jednego typu, co najmniej jednego członka i identyfikator inny niż
  `materials`, `components`, `products`, `all`, `written` i `default`.

Zobacz [Grupy](../rules/groups.md), gdzie jest każda reguła grup.

## Manifesty liniowe i z korzyściami skali

Manifest jest liniowy, gdy żaden wpis katalogu nie podaje minimalnej ilości ani rabatów
i żaden wpis linii nie podaje czasu ani kosztu przezbrojenia. Jego program jest
liniowy w każdej regule poza sprawdzeniem kredytu przy zakupie, które dodaje jeden
wybór tak albo nie w każdym okresie z zakupem. Manifest z minimalną ilością albo
rabatami, albo z czasem lub kosztem przezbrojenia, jest manifestem z korzyściami skali,
a jego program ma więcej wyborów tak albo nie. Odpowiedź
`POST /api/v1/manifests` i `GET /api/v1/manifests/{id}` podaje `linear`: `true` albo
`false`.

Ten wpis katalogu dla `chip` robi z najmniejszego manifestu manifest z korzyściami
skali:

```json
{
  "price": 2,
  "lead_time": 2,
  "max_quantity": 1000,
  "punctuality": 0.9,
  "delay": 1,
  "completeness": 1,
  "acceptance": 1,
  "min_quantity": 200,
  "discounts": [
    {"from": 500, "price": 1.9},
    {"from": 800, "price": 1.8}
  ]
}
```

- Wpis katalogu z `min_quantity`, nawet równym 0, albo z co najmniej jednym rabatem
  daje `linear` równe false.
- To samo robi wpis linii z `changeover_time` lub `changeover_cost`, nawet równym 0, na
  przykład `"changeover_time": 2, "changeover_cost": 300`.
- Program optymalizatora ma wybory tak albo nie dla tego, czy okres kupuje, dla
  minimalnej ilości powyżej 0, rabatu oraz czasu lub kosztu przezbrojenia powyżej 0.
  Gdy każdy taki klucz to 0, jego jedynymi wyborami tak albo nie jest to, czy każdy
  okres kupuje.
- Fabryka przykładowa jest manifestem z korzyściami skali:
  `Electronics factory with economies of scale` ma minimalne ilości, rabaty i
  przezbrojenia. Zobacz [Fabryka przykładowa](../library/example-factory.md).

## Szablony

Pakiet zawiera dwa szablony: manifest, który używa każdego klucza manifestu co
najmniej raz, i scenariusz do niego, który używa każdego klucza scenariusza. Używają
każdego rodzaju zakresu, zakłócenia i kształtu popytu. Ich liczby są tylko
przykładowe.

- W kopii repozytorium to `src/factory_simulator/api/examples/templates/manifest.json`
  i `scenario.json` w tym samym folderze.
- W zainstalowanym pakiecie to pliki `factory_simulator`:

```python
from importlib.resources import files

templates = files("factory_simulator") / "api" / "examples" / "templates"
manifest = (templates / "manifest.json").read_text()
scenario = (templates / "scenario.json").read_text()
```

- Żadna ścieżka interfejsu HTTP ich nie podaje. Serwer nie ładuje ich przy starcie.
  `POST /api/v1/manifests` przyjmuje szablon manifestu, a szablon scenariusza jest do
  niego przyjmowany.
- Szablon manifestu jest manifestem z korzyściami skali.

## Manifest wygenerowany

`POST /api/v1/manifests/generated` pisze manifest z liczby obiektów i ziarna, sprawdza
go i zapisuje, tak jak `POST /api/v1/manifests`:

```json
{
  "counts": {
    "materials": 4,
    "components": 3,
    "products": 2,
    "suppliers": 2,
    "customers": 2,
    "lines": 2
  },
  "seed": 0
}
```

- Liczby obiektów są całkowite, jako liczby JSON albo jako tekst: `materials` od 1 do
  200, `components` od 1 do 100, `products`, `suppliers` i `customers` od 1 do 50,
  `lines` od 1 do 20 i najwyżej `components` + `products`.
- Ziarno to liczba całkowita od 0 do 2 do potęgi 128 minus 1. Decyduje tylko
  o manifeście. Ziarno przebiegu to osobna liczba.
- Te same liczby obiektów i to samo ziarno dają ten sam manifest, bajt w bajt, na
  każdym komputerze.
- Obiekty mają nazwy z rodzaju i numeru: `material-1`, `component-2`, `line-1`. Jest
  jeden magazyn, `plant`, który przyjmuje każdą pozycję.
- Każdy komponent ma jedną recepturę, `standard`, z 1 do 4 materiałów; każdy produkt
  jedną z 1 do 4 komponentów. Każdy materiał ma jednego lub dwóch dostawców, każdy
  komponent i produkt jedną linię, a każdy klient kupuje co najmniej jeden produkt.
- Większość liczb jest losowana od najmniejszej do największej wartości tego samego
  parametru w fabryce przykładowej. Parametr, który przykład zapisuje jako
  zakres, taki jak `demand` lub `yield`, jest tu też zakresem.
- Niektóre liczby wynikają z innych: zdolność linii, największa ilość wpisu katalogu,
  koszty składowania, wartości odzysku, pojemność `plant` i limit kredytowy. Zdolność
  linii to godziny, których potrzebuje środek popytu, podzielone przez 0.85. Trzy
  stopy odsetek są takie jak w fabryce przykładowej.
- Manifest wygenerowany jest liniowy. Nie ma grupy, trasy ani opcjonalnego klucza poza
  tymi powyżej. Jego `name` to `Generated factory`, a jego `description` podaje liczby
  obiektów i ziarno.

Odpowiedź to zapisany manifest, z 201 lub 200 tak jak dla `POST /api/v1/manifests`.
Scenariusz pisze się do niego tak jak do każdego manifestu.

## Ekonomia manifestu wygenerowanego

Klucz `economy` treści ustala, jak losowana jest cena każdego produktu klienta, na
przykład `"economy": "matched"` obok `counts` i `seed`.

- `unrestricted`, domyślnie: cena jest losowana od 108.0000 do 199.5000, z cen fabryki
  przykładowej, niezależnie od kosztu produktu. Produkt z wielu materiałów może
  kosztować więcej, niż płaci za niego którykolwiek klient.
- `matched`: cena to najniższy koszt produktu razy stosunek losowany od 1.8124 do
  2.4250, najniższy i najwyższy stosunek ceny do kosztu jej produktu w fabryce
  przykładowej, zaokrąglona do 4 miejsc. Każdy produkt klienta daje wtedy marżę, przy
  każdej liczbie obiektów.
- Obie ekonomie czytają to samo losowanie ceny, więc każda inna liczba jest w obu taka
  sama poza limitem kredytowym, który wynika z cen. `description` manifestu ekonomii
  dopasowanej kończy się `and matched prices.` i jest on zapisany pod własnym
  identyfikatorem.

## Profil ekonomiczny

`build_economic_profile` z `factory_simulator.engine` czyta manifest wygenerowany jako
JSON i podaje jego ekonomię przed jakimkolwiek przebiegiem:

```python
from factory_simulator.engine import build_economic_profile, generate_manifest

counts = {
    "materials": 4,
    "components": 4,
    "products": 1,
    "suppliers": 1,
    "customers": 1,
    "lines": 1,
}
profile = build_economic_profile(generate_manifest(counts, 2))
print(profile.economic_class)  # unproductive
```

- Najniższy koszt materiału to jego najniższa cena we wpisach katalogu. Najniższy koszt
  pozycji wytwarzanej to suma najniższych kosztów jej pozycji wejściowych i kosztu jej
  wpisu linii, przy uzysku 1, bez składowania, odsetek i strat.
- Dla każdego produktu klienta podaje najniższy koszt produktu, najlepszą marżę, czyli
  cenę minus koszt transportu i najniższy koszt, wartość obsługi, czyli cenę minus
  koszt transportu plus karę za utraconą sprzedaż i cierpliwość razy karę za
  spóźnienie, oraz środek popytu.
- Pokrycie użytecznego popytu to część środka popytu w produktach klienta, których
  wartość obsługi jest wyższa niż ich najniższy koszt. Udział marży to najlepsze
  marże przez ceny, każde ważone środkiem popytu.
- Klasa to `profitable`, gdy jakaś najlepsza marża jest powyżej 0, `penalty-driven`,
  gdy żadna nie jest, ale jakaś wartość obsługi jest wyższa niż jej najniższy koszt,
  i `unproductive` w pozostałych przypadkach.
- W przykładzie produkt kosztuje co najmniej 213.1738 za sztukę, a sztuka wysłana na
  czas jest warta najwyżej 179.6824, więc klasa to `unproductive`, a pokrycie 0: żadna
  sztuka zrobiona z kupionych pozycji wejściowych się nie opłaca, nawet gdy fabryka
  unika każdej kary.
- Każdy manifest ekonomii dopasowanej jest `profitable` z pokryciem 1. Profil niczego
  nie odrzuca: manifest każdej klasy przechodzi sprawdzenia.

## Błędy

Manifest, który łamie regułę, dostaje odpowiedź 422 z miejscem pierwszego problemu, tak
jak na stronie [Pisanie manifestu](writing-a-manifest.md#błędy). Treść żądania
`POST /api/v1/manifests/generated` jest odrzucana tak samo, przy swoim kluczu:

| Problem | Odpowiedź |
| --- | --- |
| Liczba obiektów spoza swoich wartości. | `counts.materials: Input should be greater than or equal to 1` |
| Więcej linii niż komponentów i produktów. | `counts.lines: is above components + products` |
| Ekonomia inna niż `unrestricted` i `matched`. | `economy: Input should be 'unrestricted' or 'matched'` |
