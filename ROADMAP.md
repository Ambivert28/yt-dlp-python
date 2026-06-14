# Roadmap — następny release

Lista rzeczy **niezrobionych** w release `v1.2.0` (audyt), do realizacji w kolejnych
wydaniach. Pogrupowane wg priorytetu; przy każdym punkcie powód i korzyść.

## 0. Dług techniczny do sprzątnięcia (najpierw)

- [x] **Usunięto tymczasowy wyzwalacz `push` z `.github/workflows/release.yml`.**
  W v1.2.0 dodano build na push do brancha `claude/audit-update-recommendations-42j70w`,
  żeby zbudować EXE bez taga (środowisko blokowało push tagów i `workflow_dispatch`).
  Powodował on padanie CI przy każdym kolejnym pushu (release `v1.2.0` jest immutable,
  nie da się nadpisać assetu). Release powstaje teraz tylko z pushu taga `v*`.
- [ ] **Spójny schemat wersjonowania.** Zsynchronizować `version` w `pyproject.toml`
  z tagiem release’u (np. wstrzykiwać wersję w CI). *Korzyść:* brak rozjazdu wersji
  w metadanych vs. release.

## 1. Bezpieczeństwo / niezawodność

- [ ] **Weryfikacja SHA-256 ffmpeg** (obecnie weryfikowany jest tylko yt-dlp).
  *Korzyść:* pełna ochrona supply-chain dla wszystkich pobieranych binariów.
- [ ] **Przypięcie wersji ffmpeg** zamiast wykrywania po nagłówku `Last-Modified`
  z gyan.dev. *Korzyść:* powtarzalne, przewidywalne buildy; brak cichego pominięcia
  aktualizacji, gdy serwer nie zwróci nagłówka.
- [ ] **Pinowanie akcji GitHub do SHA** (zamiast tagów `@v4`). *Korzyść:* odporność
  na podmianę tagu akcji (supply-chain CI).
- [ ] **Podpisywanie EXE (code signing)** dla Windows. *Korzyść:* mniej ostrzeżeń
  SmartScreen/AV, większe zaufanie użytkowników.
- [ ] **Poprawa self-update yt-dlp**: rozważyć `--update-to stable@latest`; `-U`
  potrafi nie zadziałać dla buildów spoza kanału release. *Korzyść:* pewniejsza
  aktualizacja silnika pobierania.

## 2. Architektura (większe zmiany)

- [ ] **#8 — Użyć yt-dlp jako biblioteki PyPI** zamiast pobierać `.exe`.
  *Korzyść:* eliminuje cały kod zarządzania binarką, działa wieloplatformowo,
  aktualizacja przez `pip`, łatwiejsze testy.
- [ ] **#13 — Podział monolitu `downloader.py`** na moduły (bootstrap binariów /
  budowa komendy / GUI) + **testy jednostkowe** (`build_command`,
  `read_urls_from_text`, `png_to_ico`, `expected_sha256`). *Korzyść:* czytelność,
  testowalność, mniejsze ryzyko regresji.
- [ ] **#11 — Parsowanie postępu przez JSON / `--progress-template`** zamiast
  dopasowywania fraz w `infer_status`. *Korzyść:* stabilny postęp (procenty,
  prędkość, ETA), odporny na zmiany komunikatów i język.

## 3. Funkcje / UX

- [ ] **#15 — Konfigurowalne w GUI**: liczba równoległych pobrań (`MAX_WORKERS`),
  liczba fragmentów, jakość. *Korzyść:* dopasowanie do łącza/sprzętu bez edycji kodu.
- [ ] **Wybór formatu per URL** (zamiast jednego globalnego). *Korzyść:* elastyczność.
- [ ] **Drag & drop URL-i** i auto-wykrywanie linków ze schowka. *Korzyść:* wygoda.
- [ ] **Retry/wznawianie przy błędach sieci** (z backoffem). *Korzyść:* odporność
  na chwilowe problemy z siecią.
- [ ] **Sprzątanie plików częściowych** po nieudanym/anulowanym pobraniu.
  *Korzyść:* brak śmieci `.part` w katalogu wyjściowym.
- [ ] **Lokalizacja UI (PL/EN)**. *Korzyść:* szersza dostępność.
- [ ] **Lepsze raportowanie błędów w statusie GUI** (krótki powód obok „failed").
  *Korzyść:* szybsza diagnoza bez zaglądania do logów.

## 4. CI / dokumentacja

- [ ] **Uczynić lint blokującym** (obecnie `ruff check . || true`) po posprzątaniu
  ostrzeżeń. *Korzyść:* utrzymanie jakości kodu.
- [ ] **Dodać uruchamianie testów w CI** (po pkt. #13). *Korzyść:* ochrona przed
  regresją przy każdym PR.
- [ ] **Przykładowy `urls.txt`** (np. `urls.example.txt`). *Korzyść:* łatwiejszy
  start w trybie CLI.
