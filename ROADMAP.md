# Roadmap

Status prac po audycie. `[x]` = zrobione, `[ ]` = do zrobienia.

## 0. Dług techniczny

- [x] **Usunięto tymczasowy wyzwalacz `push` z `.github/workflows/release.yml`.**
  Release powstaje teraz tylko z pushu taga `v*` (+ `workflow_dispatch`).
- [x] **Spójne wersjonowanie.** `__version__` w `downloader.py` (z możliwością
  nadpisania przez `APP_VERSION`), pokazywane w tytule okna; release build
  „stempluje” wersję z taga.

## 1. Bezpieczeństwo / niezawodność

- [x] **Weryfikacja SHA-256 ffmpeg** wobec publikowanego pliku `.sha256`.
- [x] **Możliwość przypięcia wersji ffmpeg** przez `FFMPEG_PINNED_VERSION`
  (domyślnie najnowszy „release-essentials”, zawsze z weryfikacją sumy).
- [x] **Lepszy self-update yt-dlp** — `--update-to stable@latest` zamiast `-U`.
- [x] **Retry pobierania binariów** z wykładniczym backoffem (2s/4s/8s) + timeout.
- [ ] **Pinowanie akcji GitHub do SHA** (zamiast tagów `@v4`). *Niezrobione:*
  w tym środowisku nie dało się wiarygodnie pobrać SHA tagów akcji (publiczne
  API GitHub zwraca 403, a dostęp MCP jest ograniczony do tego repo). Do zrobienia
  ręcznie: zamienić `uses: actions/...@vN` na `@<pełny-sha>  # vN`.
- [ ] **Podpisywanie EXE (code signing)** dla Windows. *Wymaga* certyfikatu
  do podpisywania kodu (sekret w repo) — nie da się zrobić bez niego.

## 2. Architektura

- [ ] **#8 — yt-dlp jako biblioteka PyPI.** *Rekomendacja: nie robić.* Obecny
  model pobiera i **samo-aktualizuje** binarkę yt-dlp, dzięki czemu naprawy
  YouTube działają bez przebudowy aplikacji. Wbudowanie biblioteki odebrałoby tę
  zaletę (nowy yt-dlp wymagałby nowego release’u). Zostawiamy do decyzji.
- [~] **#13 — Testy jednostkowe** dodane (`tests/test_downloader.py`:
  `build_command`, `read_urls_from_text`, `expected_sha256`, `png_to_ico`).
  Pełny podział monolitu na moduły — wciąż do zrobienia (na razie odsprzężono
  import tkinter, by moduł był testowalny headless).
- [ ] **#11 — Parsowanie postępu przez JSON / `--progress-template`** zamiast
  dopasowywania fraz w `infer_status`. *Niezrobione* (większa zmiana).

## 3. Funkcje / UX

- [x] **#15 — Konfigurowalne w GUI**: liczba równoległych pobrań i liczba
  fragmentów (spinboxy). Jakość audio jest już sterowana presetami formatu.
- [x] **Retry/wznawianie przy błędach sieci** — `--continue`, `--retries`,
  `--fragment-retries` w komendzie yt-dlp.
- [x] **Sprzątanie plików częściowych** (`.part`, `.ytdl`) po anulowaniu.
- [x] **Lepsze raportowanie błędów w statusie GUI** — ostatnia linia błędu obok
  „failed”.
- [ ] **Wybór formatu per URL** (zamiast jednego globalnego). *Niezrobione*
  (większa zmiana UX).
- [ ] **Drag & drop URL-i.** *Niezrobione* — wymaga zależności `tkinterdnd2`
  (poza biblioteką standardową) i dołączenia jej do builda EXE.
- [ ] **Lokalizacja UI (PL/EN).** *Niezrobione* (większa zmiana).

## 4. CI / dokumentacja

- [x] **Lint blokujący** (`ruff check .` bez `|| true`) — kod jest czysty.
- [x] **Testy w CI** (`pytest`).
- [x] **Przykładowy `urls.txt`** → `urls.example.txt`.
