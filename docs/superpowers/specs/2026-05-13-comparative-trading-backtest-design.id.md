# Kerangka Backtest Trading Kripto Komparatif — Spesifikasi Desain

**Tanggal:** 2026-05-13
**Proyek:** seminar-ada
**Judul seminar:** *Analisis Komparatif Sistem Multi-Agen Heuristik vs. Kognitif dalam Trading Kripto*

> Dokumen ini adalah terjemahan Bahasa Indonesia dari versi Bahasa Inggris (`...design.en.md`). Jika ada perbedaan, versi Bahasa Inggris dianggap sebagai sumber kebenaran (source of truth).

---

## 1. Tujuan

Mendesain kerangka kerja (framework) backtesting Python yang **modular, asinkron, dan andal** untuk menghasilkan perbandingan **head-to-head yang adil dan dapat direproduksi** antara:

- **Bot Tradisional** — strategi heuristik berbasis indikator (RSI, MACD, ADX, EMA, SuperTrend).
- **Bot LLM Multi-Agen** — orkestrasi LangGraph dari 4 agen terspesialisasi (Technical, Visual, QABBA, Decision) yang dirutekan melalui OpenRouter, digabungkan via aturan konsensus berbobot tetap (QABBA 40% / Visual 35% / Technical 25%).

Skala framework ini sesuai untuk seminar universitas: metodologi yang dapat dipertahankan, artefak yang dapat direproduksi, data nyata (bukan disintesis), dan TUI berbasis Rich yang memvisualisasikan kedua bot berjalan secara paralel.

---

## 2. Keputusan terkunci (dari brainstorming Q1–Q5)

| # | Keputusan | Pilihan |
|---|---|---|
| Q1 | Timeframe bar | Dapat dikonfigurasi (default `1h`); kedua bot berjalan pada timeframe yang sama → perbandingan adil. |
| Q2 | Reproduksibilitas LLM | Cache JSON wajib di disk, key = `(model, agent, prompt_hash, image_hash, bar_ts)`; `temperature=0`. |
| Q3 | Visual Analyst | Window PNG bergulir 100-bar (dapat dikonfigurasi); model vision default `anthropic/claude-3.5-sonnet`. |
| Q4 | Data QABBA | CVD nyata dihitung dari Binance `aggTrades`. **Tanpa OBI** dalam backtest. Window dijaga pendek (2–4 minggu, default ~3 minggu) untuk membatasi ukuran download dan biaya LLM. |
| Q5 | Eksekusi & rigor | Fill di open bar berikutnya, fee taker Binance 0.04% per sisi + slippage konfigurabel, sizing fixed-fractional 2%-risk dari stop SuperTrend, walk-forward atas **BTC/USDT, ETH/USDT, SOL/USDT** dengan pelaporan mean ± std. |

---

## 3. Gambaran arsitektur

```
                  ┌─────────────────────────────────────────┐
                  │              main.py                    │
                  │   (CLI, load config, runner asyncio)    │
                  └────────────────────┬────────────────────┘
                                       │
                       ┌───────────────┴────────────────┐
                       │                                │
                ┌──────▼────────┐                ┌──────▼──────┐
                │ BacktestEngine│◄──── feeds ────│ DataLoader  │
                │ (core/engine) │                │(CSV+parquet)│
                └──────┬────────┘                └─────────────┘
                       │   bar-per-bar (await)
        ┌──────────────┼──────────────┐
        │              │              │
   ┌────▼─────┐   ┌────▼─────┐   ┌────▼─────┐
   │Tradisional│  │ Strategi  │   │   TUI    │
   │ Strategy  │  │ LLM Agent │   │  (Rich)  │
   └──────────┘   └────┬──────┘   └──────────┘
                       │ LangGraph: Tech ┐
                       │              Visual ┼─► Decision
                       │              QABBA  ┘
                       ▼
               ┌────────────────┐
               │ LLMClient      │
               │ + cache JSON   │
               │ → OpenRouter   │
               └────────────────┘
```

**Properti arsitektur kunci:**

- **Event loop asyncio tunggal** menjalankan engine + TUI; panggilan LLM di-`await` → TUI tidak pernah membeku.
- **Antarmuka strategi** adalah protokol async tipis (`async on_bar(bar, context) -> Signal`). Kedua bot mengimplementasikan secara identik → engine bersifat strategy-agnostic.
- **Lapisan portofolio + eksekusi adalah infrastruktur bersama** (`core/portfolio.py`, `core/broker.py`). Kedua bot menggunakan logika fee/slippage/sizing yang sama → perbandingan adil.
- **Provider LLM bersifat pluggable**: protokol `LLMClient` dengan implementasi `OpenRouterClient`, `MockClient`, dan dekorator `CachedClient`.
- **Reproduksibilitas adalah perhatian utama**: indikator deterministik, cache LLM beku, semua artefak run dipersistensi di `results/runs/<timestamp>/`.

---

## 4. Struktur folder

```
seminar-ada/
├── main.py                          # Entrypoint CLI, runner asyncio
├── config.yaml                      # Semua parameter
├── pyproject.toml                   # Dependensi + konfigurasi tool (ruff, pytest)
├── .env.example                     # Placeholder OPENROUTER_API_KEY
├── README.md
│
├── core/
│   ├── engine.py                    # BacktestEngine async (loop bar-per-bar)
│   ├── portfolio.py                 # Equity, posisi, kurva equity
│   ├── broker.py                    # Simulasi fill order (open bar berikutnya + slippage + fee)
│   ├── metrics.py                   # Total Return, MDD, Win Rate, Profit Factor, Sharpe
│   ├── ui.py                        # TUI Rich (Layout: header/kiri/kanan/footer)
│   └── types.py                     # Dataclass Bar, Signal, Order, Trade, AgentReport
│
├── data/
│   ├── loader.py                    # Load OHLCV CSV + parquet CVD, sinkronkan timestamp
│   ├── downloader.py                # Downloader CCXT OHLCV + Binance aggTrades
│   ├── cvd.py                       # Agregator aggTrades → CVD per-bar
│   └── cache/                       # Data yang diunduh (gitignored)
│
├── indicators/
│   └── ta.py                        # RSI, MACD, ADX, EMA, SuperTrend (vektorisasi)
│
├── strategies/
│   ├── base.py                      # Protokol Strategy
│   ├── traditional.py               # Bot heuristik
│   └── llm_agents/
│       ├── strategy.py              # LLMAgentStrategy (mengimplementasikan base.Strategy)
│       ├── graph.py                 # Definisi LangGraph (4 node + edge)
│       ├── state.py                 # GraphState TypedDict
│       ├── prompts.py               # System prompt untuk semua 4 agen
│       ├── chart.py                 # Renderer PNG mplfinance (window 100-bar)
│       └── nodes/
│           ├── technical.py         # Agen 1
│           ├── visual.py            # Agen 2 (vision)
│           ├── qabba.py             # Agen 3 (CVD + taker buy ratio)
│           └── decision.py          # Agen 4 (konsensus berbobot 40/35/25)
│
├── llm/
│   ├── client.py                    # Protokol LLMClient + OpenRouterClient + MockClient
│   ├── cache.py                     # Dekorator CachedClient (JSON di disk)
│   └── budget.py                    # Pelacak penggunaan token + USD
│
├── cache/llm/                       # Cache JSON per panggilan (commit untuk reproduksibilitas seminar)
│
├── results/
│   ├── runs/                        # Artefak per-run (trades.csv, equity.csv, summary.json)
│   └── plots/                       # Kurva equity, drawdown, chart perbandingan
│
└── tests/                           # Lihat §10
```

---

## 5. Model data inti (`core/types.py`)

```python
@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float; high: float; low: float; close: float
    volume: float
    taker_buy_volume: float            # field kline Binance, disimpan untuk referensi
    cvd: float                         # kumulatif, dari aggTrades
    cvd_delta: float                   # kontribusi bar ini

class Action(Enum): BUY = "BUY"; SELL = "SELL"; HOLD = "HOLD"

@dataclass
class Signal:
    action: Action
    confidence: float                  # 0–1, hanya untuk logging (sizing tetap)
    reasoning: str                     # string pendek yang ditampilkan di TUI
    stop_loss: float | None            # stop SuperTrend; None untuk HOLD

@dataclass
class AgentReport:                     # Output tiap node analyst LLM
    action: Action
    confidence: float                  # 0–1
    rationale: str
```

---

## 6. Backtest engine (`core/engine.py`)

```python
async def run():
    prev_bar = None
    for bar in data_iter:                       # semua bar dalam window
        ui.update_header(bar)

        # Kedua strategi melihat bar identik; di-await secara concurrent.
        sig_trad, sig_llm = await asyncio.gather(
            traditional.on_bar(bar, ctx_trad),
            llm_agent.on_bar(bar, ctx_llm),
        )

        # Fill terjadi di open bar BERIKUTNYA (tanpa look-ahead).
        broker_trad.queue(sig_trad, bar)
        broker_llm.queue(sig_llm, bar)
        if prev_bar is not None:
            broker_trad.fill_pending(bar)       # menggunakan bar.open
            broker_llm.fill_pending(bar)

        ui.update_panels(portfolio_trad, portfolio_llm, sig_llm.reasoning)
        prev_bar = bar

    metrics_trad = compute_metrics(portfolio_trad)
    metrics_llm  = compute_metrics(portfolio_llm)
    persist_results(...)
```

**Mengapa `asyncio.gather`:** Bot tradisional kembali dalam <1 ms (CPU-bound). Bot LLM bisa memakan 5–30 detik per bar (4 agen, jaringan). Gathering berarti total wall-clock didominasi bot LLM; bot tradisional praktis gratis, dan TUI tetap repaint karena event loop yield selama HTTP await LLM.

**Invarian tanpa look-ahead:** Indikator pada bar `t` dihitung hanya dari bar `[0..t]`. Sinyal pada bar `t` di-queue dan di-fill pada `bar[t+1].open`. Test (§10) memverifikasi ini.

---

## 7. Subsistem LLM Agent (`strategies/llm_agents/`)

### 7.1 Topologi LangGraph

```
            ┌─────────────┐
            │   START     │
            └──────┬──────┘
                   │ (fan out paralel)
       ┌───────────┼───────────┐
       ▼           ▼           ▼
  ┌────────┐  ┌────────┐  ┌────────┐
  │Technical│  │ Visual │  │ QABBA  │
  │  Agen  │  │  Agen  │  │  Agen  │
  └───┬────┘  └───┬────┘  └───┬────┘
      └───────────┼───────────┘
                  ▼
            ┌──────────┐
            │ Decision │  ← konsensus berbobot
            │  Agen    │
            └────┬─────┘
                 ▼
              END → Signal
```

Tiga node analyst dieksekusi konkuren via fan-out edge LangGraph (masing-masing adalah `await client.chat(...)`). Decision menunggu ketiganya. Biaya LLM per-bar ≈ `max(t_tech, t_visual, t_qabba) + t_decision`, bukan jumlahnya.

### 7.2 Konsensus Berbobot (Agen 4)

Decision Agent menerima ketiga `AgentReport` plus system prompt yang mengkode kebijakan. Perhitungan yang sama **juga dilakukan secara deterministik di Python** sebagai pengaman; jika LLM tidak setuju dengan matematika, kita catat ketidaksetujuan dan menggunakan matematika. Ini perilaku terdokumentasi (peran LLM adalah generasi rasional, bukan aritmetika).

```
buy_score  = 0.40 * I[QABBA=BUY]   * QABBA.conf
           + 0.35 * I[Visual=BUY]  * Visual.conf
           + 0.25 * I[Tech=BUY]    * Tech.conf

sell_score = 0.40 * I[QABBA=SELL]  * QABBA.conf
           + 0.35 * I[Visual=SELL] * Visual.conf
           + 0.25 * I[Tech=SELL]   * Tech.conf

if buy_score  > 0.50 and buy_score  > sell_score: BUY
if sell_score > 0.50 and sell_score > buy_score:  SELL
else:                                              HOLD
```

(`I[...]` adalah fungsi indikator: 1 jika benar, 0 jika tidak. `*.conf` adalah self-reported confidence agen di `[0, 1]`.)

### 7.3 Input dan output agen

| Agen | Input | Output (JSON) |
|---|---|---|
| Technical | Dict indikator pada bar `t` (RSI, MACD hist, ADX, EMA20, EMA50, SuperTrend) | `{action, confidence, rationale}` |
| Visual | PNG 100-bar (base64) di-render via mplfinance | `{action, confidence, rationale, patterns_detected, key_levels}` |
| QABBA | Window 50-bar dari `cvd`, `cvd_delta`, `taker_buy_ratio`, trade besar terkini | `{action, confidence, rationale, flow_regime}` |
| Decision | Tiga report di atas + formula konsensus | `{action, confidence, rationale}` |

Semua prompt menerapkan mode JSON + `temperature=0`. Pydantic memvalidasi respons; satu repair retry pada JSON malformed; pada kegagalan kedua → emit `HOLD` dan log.

---

## 8. Klien LLM + cache (`llm/`)

```python
class LLMClient(Protocol):
    async def chat(self, messages, *, model, response_format=None, image=None) -> Response: ...

class CachedClient:
    """Dekorator: cek cache sebelum memanggil client di bawahnya."""
    def __init__(self, inner: LLMClient, cache_dir: Path): ...

    async def chat(self, messages, *, model, **kw):
        key = sha256(json.dumps({
            "model": model,
            "messages": messages,
            "image_hash": sha256(kw.get("image") or b"").hexdigest(),
            "response_format": kw.get("response_format"),
        }, sort_keys=True))
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return Response(**json.loads(path.read_text()))
        resp = await self.inner.chat(messages, model=model, **kw)
        path.write_text(json.dumps(asdict(resp)))
        return resp
```

- Flag CLI `--mock` menukar `OpenRouterClient` dengan `MockClient` yang mengembalikan report kalengan — engine, TUI, dan test berjalan tanpa panggilan API.
- Budget guard membungkus client untuk melacak `prompt_tokens`, `completion_tokens`, dan USD dari metadata respons OpenRouter; membatalkan run jika `llm.max_usd` terlampaui.

---

## 9. Layout TUI (`core/ui.py`)

```
┌─────────────────────────────────────────────────────────────────────┐
│ BTC/USDT  1h  |  Bar 412/720  |  2025-04-12 14:00 UTC  |  $63,142   │  Header
├──────────────────────────────────┬──────────────────────────────────┤
│ BOT TRADISIONAL                  │ BOT LLM MULTI-AGEN               │
│ Saldo:      $10,420              │ Saldo:      $10,310              │
│ Equity:     $10,512              │ Equity:     $10,290              │
│ Trade:      14   Win%: 57%       │ Trade:       6   Win%: 67%       │
│ MDD:        -4.2%                │ MDD:        -2.1%                │
│ ▁▂▂▃▃▄▅▆▇█ (sparkline)           │ ▁▂▃▃▃▄▄▅▆▆ (sparkline)           │
│                                  │                                  │
│ Sinyal terakhir: HOLD            │ Log Reasoning:                   │
│   EMA20<EMA50, ADX=22            │  T:HOLD(0.4) V:BUY(0.6)          │
│                                  │  Q:BUY(0.8) → BUY (skor 0.62)    │
│                                  │  "CVD naik, bull flag…"          │
├──────────────────────────────────┴──────────────────────────────────┤
│ [12:01] OpenRouter OK  cache hit 87%  spend $0.42/$5.00  RPS 2.1   │  Footer
└─────────────────────────────────────────────────────────────────────┘
```

Implementasi: Rich `Live` + region `Layout`, di-feed dari objek `RunState` bersama yang ditulisi strategi + engine. Tanpa lock — asyncio single-threaded. Refresh ticker pada 4 Hz via `asyncio.create_task`.

---

## 10. Konfigurasi (`config.yaml`)

```yaml
run:
  assets: [BTC/USDT, ETH/USDT, SOL/USDT]   # walk-forward atas aset ini
  timeframe: 1h
  start: 2025-04-01
  end:   2025-04-21                         # ~3 minggu (keputusan Q4)
  initial_balance: 10000

execution:
  fill: next_bar_open
  taker_fee_bps: 4                          # 0.04% per sisi
  slippage_bps: 2                           # 0.02% flat
  risk_pct: 0.02                            # 2% per trade, ukuran dari stop SuperTrend

indicators:
  rsi: 14
  macd: [12, 26, 9]
  adx: 14
  ema_fast: 20
  ema_slow: 50
  supertrend: [10, 3]

llm:
  cache_dir: cache/llm
  max_usd: 10.00
  agents:
    technical: { model: anthropic/claude-3.5-sonnet, temperature: 0 }
    visual:    { model: anthropic/claude-3.5-sonnet, temperature: 0, chart_window: 100 }
    qabba:     { model: anthropic/claude-3.5-sonnet, temperature: 0, lookback: 50 }
    decision:  { model: anthropic/claude-3.5-sonnet, temperature: 0 }
  consensus_weights: { qabba: 0.40, visual: 0.35, technical: 0.25 }
  consensus_threshold: 0.50

data:
  source: binance
  qabba_mode: aggtrades                     # satu-satunya mode yang didukung per Q4
```

`OPENROUTER_API_KEY` ada di `.env`, dimuat via `python-dotenv`. `.env.example` disertakan dengan placeholder.

---

## 11. Strategi pengujian

| Lapisan | Test | Mengapa |
|---|---|---|
| Indikator | RSI/MACD/SuperTrend pada fixture vs nilai referensi `ta-lib` | Tangkap off-by-one di rolling window |
| Broker | Matematika fee + slippage pada order sintetis; semantik fill bar berikutnya | Keadilan perbandingan bergantung pada ini |
| Metrics | MDD pada kurva equity buatan tangan; Profit Factor dengan edge case zero-loss | Edge case menggigit |
| Cache LLM | Input identik → key sama; stabilitas image hash | Jaminan reproduksibilitas |
| Engine end-to-end | Run pada 50 bar fixture dengan `MockClient`; assert equity deterministik | Smoke test seluruh loop |
| Strategi tradisional | Bar kalengan di mana kondisi terpenuhi/tidak | Dokumentasikan heuristik |

Target: ~70% line coverage pada `core/`, `indicators/`, `llm/cache.py`. Node LLM sendiri di-integration-test via Mock client.

---

## 12. Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Rate-limit / outage OpenRouter di tengah run | Retry `tenacity` dengan exponential backoff; cache membuat re-run gratis |
| Token vision membengkakkan budget | Budget guard membatalkan; PNG 100-bar pada DPI moderat ≈ ~50 KB |
| Download aggTrades gagal / parsial | `downloader.py` idempotent, resumable, validasi jumlah row vs volume yang dilaporkan Binance |
| LLM mengembalikan JSON malformed | Validasi Pydantic + 1 repair retry; kegagalan kedua → HOLD + log |
| Glitch interleaving engine + TUI | Single asyncio loop, tanpa thread; redraw TUI pada ticker 4 Hz `asyncio.create_task` |
| Perbandingan tidak adil karena trade LLM jarang | Walk-forward atas 3 aset memberi N≈30–60 trade per bot total → cukup untuk statistik deskriptif |
| Bias look-ahead dari indikator | Semua indikator dihitung hanya dari data sampai bar `t`; assertion di test |

---

## 13. Urutan implementasi

1. Scaffold folder + `pyproject.toml` + `.env.example` + `config.yaml`.
2. `core/types.py`, `data/loader.py`, `data/downloader.py`, `data/cvd.py` + test.
3. `indicators/ta.py` + test terhadap referensi TA-Lib.
4. `core/portfolio.py`, `core/broker.py`, `core/metrics.py` + test.
5. `strategies/base.py`, `strategies/traditional.py` + test.
6. `llm/client.py`, `llm/cache.py`, `llm/budget.py` + `MockClient` + test.
7. `strategies/llm_agents/` (chart, prompts, 4 node, graph, strategy) — gunakan `MockClient` dulu.
8. `core/engine.py` end-to-end dengan LLM mock — verifikasi TUI tidak membeku.
9. `core/ui.py` layout Rich asli.
10. `main.py` CLI + walk-forward runner.
11. Integrasi OpenRouter live test pada 1 hari BTC.
12. Run seminar penuh 3-minggu × 3-aset; export `results/runs/<timestamp>/`.

---

## 14. Di luar lingkup (YAGNI)

- Mode live trading (hanya backtest — proyek terpisah).
- Dashboard web (TUI Rich adalah UI).
- Analisis multi-timeframe dalam satu run (timeframe adalah knob konfigurasi).
- Optimasi hyperparameter / tuning strategi (bukan pertanyaan seminar).
- Database — file flat (CSV/parquet/JSON) sudah cukup.
- Sintesis OBI (keputusan Q4: nyata atau tidak sama sekali).
- Sizing posisi yang ditentukan LLM (keputusan Q5: sizing identik untuk perbandingan adil).

---

## 15. Catatan terbuka untuk paper

- Bobot 40% pada QABBA harus dijustifikasi di seksi metodologi, karena QABBA dalam build ini melihat CVD + taker-buy flow (bukan L2 OBI penuh). Direkomendasikan diparafrase sebagai "bobot mikrostruktur trade-flow" alih-alih "bobot order-book".
- Cross-check Python deterministik pada formula konsensus harus diungkapkan: peran LLM Decision Agent adalah rasional, bukan aritmetika.
- Reproduksibilitas: commit direktori `cache/llm/` bersama hasil run seminar agar reviewer dapat re-run dan mendapat metrik bit-identik.
