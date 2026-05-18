# Demo Cheat-Sheet — Live Cache Replay

## Pre-flight (do this 5 minutes before the seminar)

1. Open a fresh PowerShell at the project root:
   ```powershell
   cd "D:\CODING ADAM\seminar-ada"
   ```
2. Verify the venv works:
   ```powershell
   .\.venv\Scripts\python.exe --version
   ```
   Expect: `Python 3.13.1`
3. Verify the cache exists:
   ```powershell
   (Get-ChildItem -Path "cache\llm" -Recurse -File).Count
   ```
   Expect: `1263` (or close to it).
4. Verify the previous results are committed (so the demo writes a fresh run, not overwriting):
   ```powershell
   git status
   ```
   Expect: clean working tree.
5. **Disable internet on your laptop** (turn off Wi-Fi). This guarantees the cache is doing the work and prevents a surprise budget charge or network hang.
6. Increase terminal font size to ~18pt for projector readability.

## The Demo Command

One line, spoken aloud as you type it:

```powershell
.\.venv\Scripts\python.exe main.py
```

Expected duration: **~30 seconds**.

## What to Point At On Screen

While the run executes, narrate in this order:

1. **Top of output** — config echo (model, symbol, window). Say: "Same data, same risk, same engine. The only variable is the strategy."
2. **Progress line** — bar counter advancing. Say: "Every bar is a decision. The cache returns the same answer the live LLM gave, so this run is bit-for-bit reproducible."
3. **Cache hit messages** (if visible). Say: "No network. No cost. This is the determinism we need for a fair comparison."
4. **Final summary table** — when it prints. Read the headline numbers aloud:
   - "Traditional, plus 3.07 percent."
   - "LLM, minus 6.20 percent."
   - Pause. Let it land.

5. **Show the results directory:**
   ```powershell
   Get-ChildItem -Path "results\runs" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   ```
   Then drill in:
   ```powershell
   Get-Content "results\runs\<latest-timestamp>\summary.json" | Out-String
   ```

## Contingency Plan

**If the command errors out (any reason):**
- Stay calm. Say: "I have the committed results from a prior run — let me show you those directly."
- Open `results/runs/20260516T215247Z/summary.json` in the editor or print it:
  ```powershell
  Get-Content "results\runs\20260516T215247Z\summary.json"
  ```
- Continue the script as if the demo had succeeded — the numbers are the same either way (deterministic cache).

**If the projector loses signal:**
- Verbalize the headline numbers from memory: Traditional +3.07%, LLM −6.20%.
- Move on to Slide 13. The demo is decoration, not load-bearing.

**If a lecturer interrupts during the demo:**
- Pause the narration, answer briefly, resume from where you left off.
- The cache replay finishes whether you talk over it or not.

## After the Demo

Do NOT close the terminal. You'll reference the printed summary table when you reach the Results section (Slide 13).

## Bar Artifacts (Optional Deep-Dive)

If `run.dump_bar_artifacts: true` was set in `config.yaml` for the run, every candle leaves a folder behind under `results\runs\<id>\BTC_USDT\bars\<NNNN>\` containing the exact prompts, chart PNG, raw analyst responses, and final decision for that bar. Use it to answer audit questions live:

```powershell
explorer.exe results\runs\<latest-timestamp>\BTC_USDT\bars\0123
```

Inside that folder: `input_indicators.json` + `output_signal.json` (traditional side), `visual_input.png` + `technical_input.txt` / `visual_input.txt` / `qabba_input.txt` + the matching `*_output.json` files, and `decision_output.json` (LLM side). See `docs/bar_artifacts.md` for the full schema.

## Files Worth Knowing By Heart

| Path | What's there |
|---|---|
| `config.yaml` | The exact run parameters — open this if asked "what window?" |
| `results/runs/20260516T215247Z/summary.json` | Backup numbers if live demo fails |
| `results/runs/20260516T215247Z/BTC_USDT/llm_trades.csv` | Per-trade detail if asked "show me the losing shorts" |
| `strategies/llm_agents/strategy.py` | Code if asked "show me the regime gate" — point at lines ~167–179 |
| `core/walkforward.py` | Code if asked "how do you handle errors" |
