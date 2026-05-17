# CVD: Parquet → CSV Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `cvd_parquet_path` with `cvd_csv_path` so bar-level data (OHLCV + CVD) uses a single consistent format. CVD is ~480 rows × 4 columns per run — parquet is a legacy holdover from the aggTrades-derivation pipeline that is no longer the primary computation path (`cvd_from_klines` derives CVD directly from `taker_buy_volume`).

**Architecture:** Single-format bar data. After this change: OHLCV and CVD both live as CSV under `data/cache/{ohlcv,cvd}/<SYMBOL>_<TF>.csv`. aggTrades (which can be millions of rows per symbol) stays parquet — that justification is real and remains documented in `data/downloader.py:128`. Loader merges two CSVs on timestamp instead of CSV + parquet.

**Tech Stack:** pandas (`read_csv` / `to_csv`), pytest.

---

## File Structure

**Modify:**
- `data/paths.py:26-27` — rename `cvd_parquet_path` → `cvd_csv_path`, change extension `.parquet` → `.csv`.
- `data/loader.py:1,12,32,41` — update import, path call, reader (`read_parquet` → `read_csv` with `parse_dates`), docstring.
- `scripts/fetch_data.py:28,57,63` — update import, path call, writer (`to_parquet` → `to_csv`).
- `tests/test_paths.py:3,17-18` — update import + assertion.
- `tests/test_loader.py:1,13,43-45,84-87,127-129` — update imports, file extensions, writers/readers, docstrings.
- `tests/test_live_smoke.py:20,38-40` — update imports, writers.
- `tests/test_traditional_e2e.py:14,45-47` — update imports, writers.

**No new files.** Cache regeneration: delete `data/cache/cvd/BTCUSDT_15m.parquet`, re-run `scripts/fetch_data.py` to emit `BTCUSDT_15m.csv`.

---

### Task 1: Rename path helper

**Files:**
- Modify: `data/paths.py:26-27`
- Test: `tests/test_paths.py:3,17-18`

- [ ] **Step 1: Update the failing test**

Edit `tests/test_paths.py`:

```python
from data.paths import aggtrades_parquet_path, cvd_csv_path, ohlcv_csv_path


def test_cvd_csv_path(tmp_path):
    p = cvd_csv_path("ETH/USDT", "4h", root=tmp_path)
    assert p == tmp_path / "cvd" / "ETHUSDT_4h.csv"
```

(Rename `test_cvd_parquet_path` → `test_cvd_csv_path` and update both the import and the expected suffix.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paths.py -v`
Expected: FAIL with `ImportError: cannot import name 'cvd_csv_path'`.

- [ ] **Step 3: Rename in `data/paths.py`**

```python
def cvd_csv_path(symbol: str, timeframe: str, root: Path = DEFAULT_ROOT) -> Path:
    return root / "cvd" / f"{_norm(symbol)}_{timeframe}.csv"
```

(Replace lines 26-27. Function name and extension both change.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_paths.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Verify no other callers remain**

Run: `rg -n "cvd_parquet_path"`
Expected: matches in `data/loader.py`, `scripts/fetch_data.py`, `tests/test_loader.py`, `tests/test_live_smoke.py`, `tests/test_traditional_e2e.py` only. These are fixed in subsequent tasks. (Do NOT commit yet — the codebase is broken until Task 4.)

---

### Task 2: Update loader

**Files:**
- Modify: `data/loader.py:1,12,32,41`
- Test: `tests/test_loader.py`

- [ ] **Step 1: Update tests to write CSV instead of parquet**

In `tests/test_loader.py`, every fixture-setup line that currently does:

```python
from data.paths import cvd_parquet_path, ohlcv_csv_path
...
cp = cvd_parquet_path("BTC/USDT", "1h", root=tmp_path)
cvd.to_parquet(cp, index=False)
```

becomes:

```python
from data.paths import cvd_csv_path, ohlcv_csv_path
...
cp = cvd_csv_path("BTC/USDT", "1h", root=tmp_path)
cvd.to_csv(cp, index=False)
```

The same substitution applies to lines 13, 43-45, 84-87, 127-129. Also update line 1 docstring "OHLCV CSV + CVD parquet" → "OHLCV CSV + CVD CSV", and any line that reads back the CVD file via `pd.read_parquet(cp)` (line 85) → `pd.read_csv(cp, parse_dates=["timestamp"])`.

- [ ] **Step 2: Run loader tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_loader.py -v`
Expected: FAIL with `ImportError: cannot import name 'cvd_csv_path'` from `data.loader` (because loader.py still imports the old name).

- [ ] **Step 3: Update `data/loader.py`**

Line 1 docstring:
```python
"""Stream Bar objects by joining OHLCV + CVD CSVs on timestamp."""
```

Line 12 import:
```python
from data.paths import DEFAULT_ROOT, cvd_csv_path, ohlcv_csv_path
```

Line 32:
```python
cvd_path = cvd_csv_path(symbol, timeframe, root=root)
```

Line 41 (replace `read_parquet` with `read_csv` + parse_dates so tz handling at line 42-43 still works):
```python
cvd = pd.read_csv(cvd_path, parse_dates=["timestamp"])
```

- [ ] **Step 4: Run loader tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_loader.py -v`
Expected: PASS (all loader tests).

- [ ] **Step 5: Commit the path + loader rename together**

```bash
git add data/paths.py data/loader.py tests/test_paths.py tests/test_loader.py
git commit -m "refactor(data): rename cvd_parquet_path -> cvd_csv_path"
```

---

### Task 3: Update fetch_data script

**Files:**
- Modify: `scripts/fetch_data.py:28,57,63`

- [ ] **Step 1: Update `scripts/fetch_data.py`**

Line 28:
```python
from data.paths import DEFAULT_ROOT, cvd_csv_path, ohlcv_csv_path  # noqa: E402
```

Line 57:
```python
        cvd_out = cvd_csv_path(sym, timeframe, root=root)
```

Line 63 (writer):
```python
        cvd_df.to_csv(cvd_out, index=False)
```

- [ ] **Step 2: Smoke-run the script against an existing OHLCV cache**

Run:
```powershell
.\.venv\Scripts\python.exe scripts/fetch_data.py --symbols BTC/USDT --timeframe 15m --start 2025-04-10 --end 2025-04-15 --skip-aggtrades
```

(If `--skip-aggtrades` isn't a flag, just let aggTrades regen — it's idempotent.)

Expected: produces `data/cache/cvd/BTCUSDT_15m.csv`. Verify with:
```powershell
Get-ChildItem data\cache\cvd\ ; Get-Content data\cache\cvd\BTCUSDT_15m.csv -TotalCount 3
```
Expected output: header `timestamp,cvd_delta,cvd,taker_buy_volume` plus 2 rows.

- [ ] **Step 3: Delete the old parquet artifact**

```powershell
Remove-Item -LiteralPath "data\cache\cvd\BTCUSDT_15m.parquet" -ErrorAction SilentlyContinue
```

- [ ] **Step 4: Commit**

```bash
git add scripts/fetch_data.py data/cache/cvd/BTCUSDT_15m.csv
git rm --cached data/cache/cvd/BTCUSDT_15m.parquet 2>$null
git commit -m "refactor(data): fetch_data.py emits CVD as CSV"
```

(If `BTCUSDT_15m.parquet` isn't tracked, the `git rm --cached` is a no-op — that's fine.)

---

### Task 4: Update remaining test fixtures

**Files:**
- Modify: `tests/test_live_smoke.py:20,38-40`
- Modify: `tests/test_traditional_e2e.py:14,45-47`

- [ ] **Step 1: Update `tests/test_live_smoke.py`**

Line 20:
```python
from data.paths import aggtrades_parquet_path, cvd_csv_path
```

Lines 38-40 (writer call):
```python
    cvd_path = cvd_csv_path(symbol, tf, root=tmp_path)
    ...
    cvd_df.to_csv(cvd_path, index=False)
```

(Substitute `to_parquet` → `to_csv` for any CVD writer; leave aggtrades writers alone.)

- [ ] **Step 2: Update `tests/test_traditional_e2e.py`**

Line 14:
```python
from data.paths import cvd_csv_path, ohlcv_csv_path
```

Lines 45-47:
```python
    cp = cvd_csv_path("BTC/USDT", "1h", root=tmp_path)
    ...
    cvd_df.to_csv(cp, index=False)
```

- [ ] **Step 3: Run the full test suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: all tests pass (no `cvd_parquet_path` references remain).

- [ ] **Step 4: Verify no stragglers**

Run: `rg -n "cvd_parquet_path|cvd.parquet"`
Expected: no matches outside of git history.

- [ ] **Step 5: Commit**

```bash
git add tests/test_live_smoke.py tests/test_traditional_e2e.py
git commit -m "test(data): update fixtures to write CVD as CSV"
```

---

### Task 5: Update presentation copy

**Files:**
- Modify: `presentation/script_en.md` (Section 2 — slide 8 "Final Bar Object Schema")
- Modify: `presentation/script_id.md` (Bagian 2 — slide 8 "Objek Bar Final")
- Modify: `presentation/slide_outline.md` (slide 8 bullet)

- [ ] **Step 1: Locate the parquet mention**

Run: `rg -n "parquet" presentation/`
Expected: matches in EN script, ID script, slide_outline (mentioning CVD parquet on slide 8).

- [ ] **Step 2: Replace parquet → CSV in slide 8 EN script**

Edit the bullet that currently mentions reading CVD from parquet so it reads "CSV" instead. Keep the aggTrades mention (it stays parquet) if present.

- [ ] **Step 3: Replace parquet → CSV in slide 8 ID script**

Same substitution in Bahasa Indonesia copy.

- [ ] **Step 4: Replace parquet → CSV in slide_outline.md**

Same substitution.

- [ ] **Step 5: Commit**

```bash
git add presentation/
git commit -m "docs(seminar): slide 8 reflects CVD-as-CSV refactor"
```

---

## Self-Review

- **Spec coverage:** Goal = "Replace cvd_parquet_path with cvd_csv_path so OHLCV and CVD share a single format." Tasks 1-4 cover all 7 modified files. Task 5 syncs the seminar narrative. ✓
- **Placeholders:** None — every step shows the actual replacement code.
- **Type consistency:** `cvd_csv_path` signature identical to old `cvd_parquet_path` (same args, same return type `Path`) — only the suffix differs.
- **Cache invalidation:** LLM cache keyed on prompt content (sha256), not file format. Bar values are bit-identical (CSV → DataFrame → identical Bar objects). Cache survives.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-cvd-parquet-to-csv.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, two-stage review.
2. **Inline Execution** — batch tasks 1-5 with checkpoints in this session.

Tasks are small and mostly mechanical (rename + format swap), so inline execution is probably fine. ~30 minutes end-to-end.
