# Naskah Penyampaian Bahasa Indonesia — 30 Menit (Fokus Data Pipeline)

Target: ~150 kata/menit; ~22 menit bicara + ~3 menit demo + transisi = 30 menit total.
Mengacu pada nomor slide di `slide_outline.md`.

Gaya bahasa: **semi-formal BI baku**, istilah teknis tetap dalam bahasa Inggris (contoh: *pipeline*, *prompt*, *signal*, *stop-loss*, *cache replay*).

---

## Bagian 1 — Pendahuluan & Masalah (00:00 → 03:00)

[SLIDE 1: Judul]
[00:00]

Selamat pagi semua, terima kasih sudah hadir di seminar hari ini. Judul penelitian ini adalah "Comparative Study: Classical Technical Analysis versus an LLM Multi-Agent Trading System on BTC/USDT". Karena ini forum Advanced Data Analysis, sebagian besar tiga puluh menit ke depan akan saya gunakan untuk masuk langsung ke dalam *data pipeline*-nya — bukan filosofi, bukan hype, tapi tepat byte apa yang datang dari exchange, tepat bagaimana byte itu ditransformasi, tepat apa yang dilihat masing-masing agent, dan tepat bagaimana sebuah keputusan menjadi *trade* yang ter-*fill*.

[BULLETS]
- Comparative Study: Classical TA vs LLM Multi-Agent on BTC/USDT
- Fokus seminar: Advanced Data Analysis
- Hari ini ceritanya tentang *data pipeline*

[NOTE TO PRESENTER] Bangun *tone*: ini talk *data engineering* yang kebetulan tentang *trading bot*, bukan talk *trading* yang kebetulan pakai data.

[SLIDE 2: Pertanyaan Penelitian]
[00:50]

Pertanyaan penelitiannya lugas. Apakah sebuah sistem LLM *multi-agent*, yang membaca data pasar mentah yang sama dengan *rulebook* analisis teknis deterministik, mampu menghasilkan keputusan *trading* yang kompetitif? Saya ingin jujur dari menit pertama: jawaban yang kami ukur bukan jawaban yang kebanyakan orang harapkan. Bot LLM kami **mengalami kerugian** dalam *window* uji. Itu adalah temuannya. Itulah yang membuat studi ini dapat dipertanggungjawabkan secara akademis — kami membangun *comparison harness* yang *byte-deterministic* dan reproducible, dan kami melaporkan apa yang keluar darinya.

[BULLETS]
- Input data sama, dua sistem keputusan
- Bot LLM rugi di *window* uji — itulah temuannya
- Hari ini: fokus pada *pipeline* yang menghasilkan angka tersebut

[NOTE TO PRESENTER] Beri jeda dua detik setelah "mengalami kerugian" — biarkan tertanam. Lanjutkan dengan percaya diri.

---

## Bagian 2 — Sumber Data & Format API Mentah (03:00 → 07:00)

[SLIDE 3: Sumber Data]
[03:00]

Kita mulai dari tempat setiap studi kuantitatif dimulai: sumbernya. Data pasar kami ambil dari **Binance Spot**, exchange crypto terbesar berdasarkan volume. Aset-nya BTC terhadap USDT, *timeframe* lima belas menit per *bar*, dan *window* uji lima hari — sepuluh April sampai lima belas April 2025. Total empat ratus delapan puluh *bar*.

Kami memanggil dua endpoint REST. Pertama, `GET /api/v3/klines`, yang mengembalikan data candlestick dengan satu field tambahan yang krusial — `taker_buy_volume`. Saya akan kembali ke alasannya sembilan puluh detik lagi. Kedua, `GET /api/v3/aggTrades`, yang mengembalikan setiap tick *trade*. Sebenarnya kami tidak lagi memakai endpoint aggTrades di jalur panas, karena kami menemukan *speedup* enam puluh sampai dua ratus kali dengan hanya menggunakan data kline. Kode yang melakukan *fetching* ada di `data/downloader.py` baris 42 — lewat library ccxt, method `publicGetKlines`.

[BULLETS]
- Binance Spot REST API
- BTC/USDT, 15m, 480 *bar* (2025-04-10 → 2025-04-15)
- Dua endpoint: klines + aggTrades (yang kedua opsional)
- ccxt `publicGetKlines`, *paginated* 1000 baris per *page*

[SLIDE 4: Respons Kline Mentah]
[03:50]

Inilah tampilan respons API mentahnya, byte-per-byte. Binance mengembalikan setiap *candle* sebagai array JSON dua belas elemen. Elemen ke-nol adalah *open timestamp* dalam milidetik. Lalu empat string harga — open, high, low, close. Lalu volume, close timestamp, quote-asset volume, jumlah trade, dan field yang paling kami butuhkan: `taker_buy_base_volume`. Ditambah dua field lagi yang kami abaikan.

Dua hal yang perlu diperhatikan. Pertama, semua harga dan volume datang sebagai **JSON string**, bukan angka — kami *cast* ke float di `downloader.py` baris 113. Kedua, dari dua belas field kami hanya menyimpan tujuh: timestamp, OHLCV, dan `taker_buy_volume`. Sisanya dibuang saat *write*.

[BULLETS]
- Array 12 elemen per *candle*, harga/volume sebagai JSON string
- Yang disimpan: timestamp, OHLCV, taker_buy_volume
- Yang dibuang: close_time, quote_vol, n_trades, taker_buy_quote, ignore

[NOTE TO PRESENTER] Tunjuk array di slide; tekankan "ini yang diberikan network, ini yang kami simpan."

[SLIDE 5: Pentingnya `taker_buy_volume`]
[04:50]

Kenapa kami sangat memperhatikan field tunggal itu? Karena ia memungkinkan kami menurunkan **cumulative volume delta** — CVD — tanpa perlu data tick. CVD adalah saldo berjalan dari volume *aggressive-buy* dikurangi volume *aggressive-sell*. Ini salah satu indikator *order-flow* yang paling sering dirujuk di *quant trading* modern.

Matematikanya adalah identitas dua baris. *Volume* sama dengan taker-buy ditambah taker-sell. *cvd_delta* sama dengan taker-buy dikurangi taker-sell. Kurangi yang satu dari yang lain: `cvd_delta sama dengan dua kali taker_buy_volume dikurangi volume`. Selesai. Kami dapat CVD gratis dari data yang sudah kami punya. Referensi kode: `data/cvd.py` baris 50, fungsi `cvd_from_klines`. Perubahan ini saja memberi kami *speedup* enam puluh sampai dua ratus kali dibanding mengunduh aggTrades per *bar*.

[BULLETS]
- CVD = kumulatif (*aggressive-buy* − *aggressive-sell*)
- Identitas: cvd_delta = 2 × taker_buy_volume − volume
- 60–200× lebih cepat dibanding aggTrades; hasil numerik identik
- `data/cvd.py:50` `cvd_from_klines`

[SLIDE 6: Objek `Bar` Final]
[06:00]

Setelah *preprocessing*, *engine* mengkonsumsi *stream* dataclass `Bar` Python. Setiap `Bar` punya sembilan field — *timestamp*, OHLC, *volume*, *taker_buy_volume*, *cvd* kumulatif, dan *cvd_delta* untuk *bar* ini. Satu `Bar` per interval lima belas menit. Total empat ratus delapan puluh objek `Bar`. *Loader* di `data/loader.py` baris 19 secara ketat menegakkan keselarasan timestamp antara OHLCV CSV dan CVD parquet — kalau ada satu timestamp yang tidak sinkron, ia *raise* `ValueError`. Kami tidak pernah *silently misalign* data.

[BULLETS]
- `Bar(timestamp, OHLC, volume, taker_buy_volume, cvd, cvd_delta)`
- Total 480 `Bar`
- *Strict timestamp alignment*; misalignment *raise* ValueError

---

## Bagian 3 — Preprocessing & Transformasi Indikator (07:00 → 12:00)

[SLIDE 7: Disiplin Warmup]
[07:00]

Sebelum kedua *strategy* mengeluarkan *signal* pertama, kami menunggu enam puluh *bar*. Kenapa enam puluh? Karena indikator paling lambat di *stack* kami — MACD dengan parameter dua belas, dua puluh enam, sembilan — baru menghasilkan nilai non-NaN pertamanya di *bar* ke-tiga puluh empat. SuperTrend butuh sekitar sepuluh *bar* untuk *ATR seasoning*. EMA-50 jelas butuh lima puluh *bar*. Enam puluh memberi *ceiling* yang nyaman di atas semuanya. Konstanta ini ditegakkan di kedua *strategy* — `strategies/traditional.py:38` dan `strategies/llm_agents/strategy.py:39`. Tanpa disiplin ini, LLM akan menerima *prompt* yang berisi literal string `"nan"` dan menghasilkan output sampah. Kami belajar itu dari proses audit.

[BULLETS]
- WARMUP = 60 *bar* sebelum *signal* apa pun
- Indikator terlambat: MACD(12,26,9), valid pertama di *bar* 34
- Ditegakkan di kedua *strategy*
- *Bug* pra-fix: *prompt* bocor `"nan"`, audit H1/H3

[SLIDE 8: Inventaris Indikator]
[08:00]

Inilah inventaris lengkap indikator. EMA di periode dua puluh dan lima puluh untuk *traditional bot*, dua belas dan dua puluh enam untuk *LLM bot*. RSI periode empat belas. MACD dua belas atas dua puluh enam dengan *signal* sembilan. ADX periode empat belas sebagai *trend-strength filter*. SuperTrend dengan *length* sepuluh dan *multiplier* tiga — dipakai sebagai *stop-loss* sekaligus indikator regim. Dan terakhir CVD, yang hanya dikonsumsi *LLM bot* lewat agent QABBA.

Perhatikan divergensi EMA. *Traditional bot* memakai 20/50, *cross* medium-term klasik. *LLM bot* memakai 12/26, yang lebih cepat dan reaktif — selaras dengan periode MACD. Ini pilihan parameter yang sengaja dari *spec*; LLM mendapat *signal* lebih cepat karena ia diharapkan berpikir lebih keras tentangnya. Apakah itu bijak, data akan memberi tahu kita dua puluh menit lagi.

[BULLETS]
- EMA: 20/50 (Trad), 12/26 (LLM)
- RSI(14), MACD(12,26,9), ADX(14)
- SuperTrend(10, 3) — *stop* + regim
- CVD — hanya LLM

[SLIDE 9: SuperTrend Lebih Dekat]
[09:30]

SuperTrend layak diberi slide tersendiri karena ia melakukan dua tugas. Matematikanya sederhana: ambil titik tengah *high* dan *low* — `hl2` — lalu tambah atau kurangi tiga kali ATR. Itu memberi dua *band* dasar, atas dan bawah. Aturan *carry-forward* membuat *band* menjadi *trailing* — ia hanya melonggar, tidak pernah menyempit melawan tren. Fungsi mengembalikan dua kolom: `st`, level harga *stop-line*, dan `dir`, tanda regim. Saat `dir` sama dengan plus satu, garis berada **di bawah** harga — *long-friendly*. Saat `dir` sama dengan minus satu, garis **di atas** harga — *short-friendly*. Kami pakai garis sebagai *stop* dan tandanya sebagai *gate*. Kode: `indicators/ta.py:124`.

[BULLETS]
- `hl2 ± 3 × ATR(10)` dengan *carry-forward*
- *Returns*: `st` (*stop-line*), `dir` (+1 long, −1 short)
- Dua tugas: level *stop* **dan** *regime gate*
- `indicators/ta.py:124`

[SLIDE 10: Diagram Pipeline Transformasi]
[10:30]

Menyatukan semuanya, inilah *pipeline* ujung-ke-ujung. Binance REST mengembalikan kline JSON 12 kolom. ccxt *paginate* seribu baris sekaligus. Kami tulis tujuh kolom ke OHLCV CSV. Kami turunkan CVD ke file parquet. *Loader* menggabungkan keduanya pada *timestamp* dan menghasilkan *stream* objek `Bar`. Dari *stream* itu, dua konsumen bercabang — *rulebook* tradisional dan *feature extractor* LLM dengan *chart renderer*-nya. Semua yang ada di hilir *Bar stream* itulah yang membedakan kedua *bot*. Semua di hulu *Bar stream* adalah *shared*. Pemisahan itu disengaja — itulah yang membuat perbandingannya adil.

[BULLETS]
- *Shared upstream*: REST → OHLCV + CVD → *Bar stream*
- Hanya bercabang setelah `Bar`: *rules* vs *features+chart*
- Input sama, *processing* beda — itu perbandingan yang adil

---

## Bagian 4 — Traditional Bot: Data → Signal → Trade (12:00 → 16:00)

[SLIDE 11: Rulebook]
[12:00]

*Traditional bot* sengaja sederhana dan sengaja transparan. *Decision rule*-nya muat di satu slide. Filter pertama: ADX di atas dua puluh — harus ada tren. Lalu: jika EMA-20 di atas EMA-50, dan histogram MACD positif, dan RSI di bawah tujuh puluh, dan arah SuperTrend plus satu — *go long*. Kondisi cermin untuk *short*. Selain itu, HOLD. Ini *confluence rule* — empat indikator harus setuju. Seratus persen deterministik. Sama *bar*, sama *signal*, setiap kali. Kode: `strategies/traditional.py:47`.

[BULLETS]
- Filter ADX > 20 (tren wajib ada)
- BUY: EMA20>EMA50 & MACD_hist>0 & RSI<70 & ST_dir=+1
- SELL: kondisi cermin
- 100% deterministik — sama *bar*, sama *signal*

[SLIDE 12: Objek Signal]
[13:30]

*Strategy* mengeluarkan dataclass `Signal` dengan empat field: *action*, angka *confidence* yang diturunkan dari seberapa kuat ADX, *reasoning string* yang bisa dibaca manusia untuk *logging*, dan yang krusial — harga *stop-loss*, yaitu garis SuperTrend pada *bar* ini. Perhatikan yang tidak ada: tidak ada *position size*. *Strategy* sengaja *sizing-agnostic*. Ia bilang "saya ingin *long* di harga ini dengan *stop* ini." *Engine* yang memutuskan seberapa besar. Pemisahan ini memungkinkan kami pakai ulang *risk-sizing* yang sama untuk kedua *bot* nanti.

[BULLETS]
- `Signal(action, confidence, reasoning, stop_loss)`
- *stop_loss* = garis SuperTrend pada *bar* ini
- *Strategy* *sizing-agnostic* — *engine* yang urus risiko

[SLIDE 13: Signal → Trade]
[14:30]

Sekarang *engine*. Lima langkah per *bar*, dalam urutan persis ini. Langkah satu — *check stops* pada *bar* yang baru terbuka; kalau *intra-bar low* menyentuh *stop* kita di posisi *long*, kami tutup di harga *stop*. Langkah dua — *fill* order apa pun yang di-*queue* *bar* sebelumnya; harga *fill* adalah **open *bar* ini** plus atau minus *slippage*. Kami tidak pernah *fill* di *bar* tempat *signal* dihasilkan — itu *look-ahead bias*. Langkah tiga — *strategy* mengeluarkan *signal* baru. Langkah empat — kalau bukan HOLD, kami *size* posisi pakai `size_position`, yang memperhitungkan *fees* dan *slippage* dalam *worst-case stop-out loss*. Risiko per *trade* dua persen dari ekuitas. Langkah lima — *mark equity* di *bar close* untuk kurva ekuitas. *Loop* yang sama jalan untuk kedua *bot* — hanya beda di langkah tiga. Kode: `core/engine.py:175`, *sizing* di `core/engine_sync.py:29`.

[BULLETS]
- 1) check_stops → 2) fill_pending(open + slip) → 3) on_bar → 4) size + queue → 5) mark
- *Fill* di *open bar* berikut — tanpa *look-ahead bias*
- risk_pct=0.02, fees=4 bps, slippage=2 bps
- *Loop* identik untuk kedua *bot* — hanya beda di langkah 3

---

## Bagian 5 — LLM Bot: Features → 3 Agents → Consensus → Trade (16:00 → 22:00)

[SLIDE 14: Kenapa Multi-Agent]
[16:00]

*LLM bot* tidak menanyakan satu LLM "haruskah saya BUY?" Itu naif — *language model* berhalusinasi, dan tidak ada cara mengaudit satu jawaban opaque. Sebagai gantinya, kami pakai tiga *specialised analyst*, masing-masing dengan informasi yang sengaja **disjoint**. Agent Technical hanya melihat skalar indikator. Agent QABBA hanya melihat skalar *order-flow*. Agent Visual hanya melihat *image candlestick chart*. Lalu *decision node* deterministik melakukan matematika *weighted* atas tiga suara mereka. LLM tidak pernah diminta menggabungkan apa pun — itu *closed-form arithmetic*. Topologinya dibangun dengan LangGraph: `START → {technical, visual, qabba} → decision → END`. Ketiga analyst berjalan paralel. Kode: `strategies/llm_agents/graph.py:45`.

[BULLETS]
- 3 *agent*, input *disjoint* (angka / angka / *image*)
- *Decision* adalah **matematika deterministik**, bukan LLM
- LangGraph *parallel fan-out*
- `graph.py:45`

[SLIDE 15: Ekstraksi Fitur]
[17:30]

Lewat *warmup*, di setiap *bar* kami hitung dict fitur. EMA-fast, EMA-slow, RSI, histogram MACD, ADX, CVD kumulatif, dan CVD delta *bar* ini. Tujuh skalar. Kami juga me-*render* enam puluh *bar* terakhir sebagai PNG *candlestick* pakai `mplfinance` di *Agg backend* — itu matplotlib mode *headless*, yang memberi PNG *byte-stable* dalam satu *environment*. PNG di-*encode* base64 dan dilampirkan ke *prompt* agent Visual. Kode: `strategies/llm_agents/strategy.py:91`, *chart rendering* di `chart.py:26`.

[BULLETS]
- 7 fitur skalar per *bar*
- + PNG *candlestick* 60-*bar* (mplfinance, *Agg backend*)
- *base64-encoded* untuk agent Visual
- *Byte-stable* dalam satu *environment* → memungkinkan *cache replay*

[SLIDE 16: Prompt per Agent]
[19:00]

Ini *template prompt* yang **sebenarnya**, langsung dari `prompts.py`. Agent Technical menerima: "You are a technical analyst. Given these indicator readings... output one of BUY, SELL, HOLD followed by a confidence in zero-to-one and a one-line rationale. Format: ACTION CONFIDENCE RATIONALE. Features: ema_fast sekian, ema_slow sekian, rsi, macd_hist, adx." QABBA menerima struktur yang sama tapi hanya CVD. Visual menerima deskripsi peran ditambah *image* terlampir — tanpa angka di teks.

Perhatikan tiga pilihan desain yang sengaja. Satu, kami batasi format output secara agresif — `ACTION CONFIDENCE RATIONALE` — supaya *regex parser* bisa mengekstrak jawaban. Dua, kami *render* angka pakai formatter custom yang tidak pernah pakai notasi saintifik, karena regex tidak mengerti `e+06`. Tiga, kami buat *prompt* singkat untuk tetap di dalam *budget cap* sepuluh dolar per *run*.

[BULLETS]
- 3 *prompt*, *template* literal dari `prompts.py`
- Output dibatasi: `ACTION CONFIDENCE RATIONALE`
- Tanpa notasi saintifik (keterbatasan *regex parser*)
- Singkat → muat di *budget* $10/*run*

[SLIDE 17: Respons Cached Sungguhan]
[20:30]

Dan inilah respons satu *bar* sungguhan — diambil dari *cache* yang kami *commit*, dari *run* Claude Haiku 4.5 nyata. Agent Technical bilang HOLD dengan *confidence* 0.62, menjelaskan *signal* EMA *crossover*-nya lemah. QABBA bilang SELL 0.72, menandai CVD delta negatif sekitar minus lima puluh tujuh unit. Visual bilang SELL 0.72, mendeskripsikan *downtrend* yang jelas di *chart*. Ketiga respons adalah objek JSON di disk — *content*, *model*, *input tokens*, *output tokens*. Token pertama sebelum *confidence* adalah yang diekstrak *regex parser* kami di `nodes/_parse.py:16`. Ia toleran — mengambil token BUY-SELL-HOLD pertama yang ditemukan, *case-insensitive*, dengan *word boundary*.

[BULLETS]
- Respons Claude Haiku 4.5 nyata di disk (*cache replay*)
- Tiga suara untuk SATU *bar*: HOLD 0.62, SELL 0.72, SELL 0.72
- *Regex parser* toleran terhadap *noise* di sekitar token

[SLIDE 18: Matematika Decision]
[21:00]

Sekarang *decision node*. Di sini Anda mungkin mengira ada panggilan LLM lain — dan tidak ada. Ini matematika *closed-form*. Bobotnya dari file config: QABBA 0.40, Visual 0.35, Technical 0.25. Untuk setiap sisi — BUY dan SELL — kami hitung *weighted sum* *confidence* dari analyst yang memilih sisi itu. *Threshold* 0.35. Sebuah sisi menang jika dan hanya jika skornya melebihi *threshold* **dan** *strictly* melebihi sisi lawan; selain itu, keputusannya HOLD.

Pada contoh dari slide sebelumnya: Technical memilih HOLD, jadi tidak berkontribusi ke sisi mana pun. QABBA SELL 0.72 berkontribusi 0.40 kali 0.72 = 0.288. Visual SELL 0.72 berkontribusi 0.35 kali 0.72 = 0.252. Total skor SELL 0.540 — jauh di atas *threshold* 0.35. Jadi keputusannya SELL dengan *confidence* 0.540. Reproducible, auditable, tidak ada kemungkinan halusinasi di tahap ini. Kode: `strategies/llm_agents/nodes/decision.py:33`.

[BULLETS]
- Bobot: Q=0.40, V=0.35, T=0.25; threshold=0.35
- Per sisi: `Σ wᵢ × confᵢ` atas analyst pemilih sisi itu
- Pemenang = max(buy, sell) jika > *threshold* dan > lawan
- Contoh: SELL menang 0.540

[SLIDE 19: Regime Gate + Stop Placement]
[21:30]

Satu *gate* lagi sebelum *signal* meninggalkan *strategy*. Kalau konsensus bilang BUY tapi arah SuperTrend minus satu — garis di atas harga — kami *override* ke HOLD. Kebalikannya juga: SELL di regim naik jadi HOLD. Kenapa? Karena *engine* punya *stop-direction check* di `core/engine.py:121` yang *silently* menolak order dengan *stop* di sisi yang salah. Tanpa *regime gate* ini, kami sebelumnya mengeluarkan *signal* ke kekosongan — muncul di log tapi tidak pernah membuka posisi. Kami menemukan itu di *re-audit* dan memperbaikinya di patch C3. Setelah *gate* ini, *LLM bot* mengeluarkan dataclass `Signal` yang persis sama dengan *traditional bot* — dan dari titik itu, alur eksekusi *trade*-nya **identik**. Engine sama, broker sama, *risk sizing* sama, *fees* sama. Satu-satunya yang berbeda antara kedua *bot* adalah apa yang menghasilkan *signal*-nya.

[BULLETS]
- BUY di regim turun → HOLD; SELL di regim naik → HOLD
- Tanpa ini: *signal* dibuang *silently* oleh *engine H4 gate*
- Patch C3 di `strategy.py:184`
- Dari `Signal` ke hilir: eksekusi identik dengan *traditional*

---

## Bagian 6 — Demo Live (22:00 → 25:00)

[SLIDE 20: Live Cache-Replay]
[22:00]

Mari saya tunjukkan ini berjalan. Demo-nya adalah ***cache replay*** — kami tidak memanggil OpenRouter live selama seminar, karena itu berisiko masalah jaringan. Sebagai gantinya, kami sudah *commit* seribu dua ratus enam puluh tiga respons LLM ter-cache ke disk. *Cache key*-nya adalah *tuple* dari *model*, nama *agent*, hash *prompt*, hash *image*, dan *timestamp bar* dalam milidetik. Saat `main.py` jalan, setiap panggilan LLM masuk ke *cache* alih-alih jaringan. *Run end-to-end* selesai dalam sekitar tiga puluh detik.

[NOTE TO PRESENTER] Pindah ke terminal. Jalankan `.\.venv\Scripts\python.exe main.py`. Berbicara sambil Rich TUI ter-update: *signal* per *bar*, kurva ekuitas, jumlah *trade*, *win percentage*, *max drawdown*. Total elapsed sekitar tiga puluh detik.

[NOTE TO PRESENTER] Setelah selesai, sebutkan *run summary* tersimpan di `results/runs/<timestamp>/summary.json`. Kembali ke slide.

---

## Bagian 7 — Hasil (25:00 → 28:00)

[SLIDE 21: Angka Headline]
[25:00]

Inilah angkanya. *Traditional bot*: return plus 3.07 persen, *max drawdown* minus 6.46 persen, empat *trade*, *win rate* lima puluh persen, *profit factor* 1.72, *Sharpe* 0.40. *LLM bot*: return minus 6.20 persen, *max drawdown* minus 10.90 persen, sepuluh *trade*, *win rate* tiga puluh persen, *profit factor* 0.41, *Sharpe* minus 0.71. LLM rugi. Ia *trade* lebih banyak, menang lebih sedikit, *drawdown* lebih dalam. *Run identifier* di disk: `20260516T215247Z`.

[BULLETS]
- Trad: +3.07% / DD −6.46% / 4 *trade* / PF 1.72
- LLM:  −6.20% / DD −10.90% / 10 *trade* / PF 0.41
- LLM rugi, *over-trade*, *drawdown* lebih dalam

[SLIDE 22: Atribusi Kerugian]
[26:00]

Dari mana kerugiannya berasal? Memisah *trade* LLM berdasarkan arah: lima *trade* BUY total plus dua puluh dua dolar. Lima *trade* SELL total **minus enam ratus empat puluh dua dolar**. Pasar bertren dari 80,800 naik ke 85,500 — *uptrend* yang jelas. LLM berulang kali mem-*fade* tren itu. Sementara *traditional bot* memegang satu posisi BUY selama dua ratus *bar* dan menangkap plus 4.42 persen. *Average hold time* LLM tiga puluh tujuh *bar* — ia *over-trade* dua setengah kali.

[BULLETS]
- LLM BUY: 5 × +$22 total
- LLM SELL: 5 × **−$642 total**
- Pasar bertren +5.8%; LLM mem-*fade* tren
- LLM *avg hold* 37 *bar* vs Trad 95 *bar*

[SLIDE 23: Tiga Hipotesis Jujur]
[27:00]

Tiga hipotesis kenapa ini terjadi, semua *testable*. Pertama — bobot CVD 0.40 adalah bobot terbesar di matematika *decision*, dan *order flow* di *timeframe* lima belas menit itu *noisy*. Tekanan jual *short-term* terlalu di-*overweight*. Kedua — *SuperTrend regime gate* di *length* sepuluh, *multiplier* tiga, *flip* karena *intra-bar noise*. *Filter* regim *longer-horizon* — misal *SuperTrend daily overlay* — kemungkinan besar akan menghilangkan sebagian besar *short* yang buruk. Ketiga — LLM tidak melihat *fee* atau *slippage* di *prompt*-nya. Ia *reasoning* seolah *trade* gratis; *engine* memang men-*fee-discount* *sizing*-nya, tapi LLM tidak pernah belajar dari biayanya. Ketiga hipotesis adalah eksperimen lanjutan yang konkret.

[BULLETS]
- H1: Bobot CVD 0.40 terlalu tinggi untuk *timeframe* 15m
- H2: SuperTrend(10,3) terlalu *jittery* — perlu *filter longer-horizon*
- H3: LLM tidak tahu biaya *fee*/*slippage*
- Ketiganya *testable* di *harness* yang sama

---

## Bagian 8 — Kesimpulan + Q&A (28:00 → 30:00)

[SLIDE 24: Kontribusi + Pertanyaan Terbuka]
[28:00]

Untuk menutup. Kontribusi kami bukan "LLM mengalahkan analisis teknis" — di *window* kami, tidak. Kontribusi kami adalah *comparison harness* yang reproducible dan *byte-deterministic*. Respons ter-cache di disk berarti siapa pun bisa menjalankan ulang eksperimen kami dan mendapatkan angka yang persis sama. Matematika *decision*-nya *closed-form*. *Data pipeline*-nya terdokumentasi ujung-ke-ujung. Hasil LLM yang rugi adalah temuan yang men-*scope* di mana LLM membantu dan di mana ia menyakiti.

Pertanyaan terbuka yang saya senang dengar masukannya dari ruangan: Apakah *prompt-engineering* konteks regim secara eksplisit — "pasar sudah bertren naik enam persen minggu ini" — akan mengubah hasilnya? Apakah lima belas menit terlalu *noisy* sebagai *timeframe* untuk membandingkan *rules* deterministik dan LLM probabilistik secara apel-ke-apel? Haruskah ***decision node* itu sendiri** menjadi LLM, dengan *context window* yang tepat? Terima kasih — saya senang menerima pertanyaan.

[BULLETS]
- Kontribusi: *comparison harness* reproducible *byte-deterministic*
- Kerugian LLM adalah temuan *scoping*, bukan kegagalan
- Tiga pertanyaan terbuka untuk ruangan
- Terima kasih

[NOTE TO PRESENTER] Buka lantai. Anchor jawaban di referensi kode — `strategies/llm_agents/strategy.py`, `nodes/decision.py`, `prompts.py` — supaya pertanyaan tetap teknis.

---

## Apendiks Q&A (jawaban siap pakai)

**Q1: Kenapa Claude Haiku dan bukan GPT-4 atau model lokal?**
J: Biaya — Haiku 4.5 kira-kira dua puluh kali lebih murah dibanding Claude Sonnet di satu dolar per juta *input token*. Untuk studi dengan jumlah *bar* sebanyak ini (480 *bar* × 3 *agent* = 1.440 panggilan LLM per *run*), biaya penting. Kami bisa ganti model dengan mudah — `config.yaml` baris 28 — dan *cache* akan *invalidate* saat model berganti.

**Q2: Apakah 480 *bar* cukup untuk kesimpulan statistik?**
J: Tidak. Dinyatakan jujur di kesimpulan. *Harness*-nya dirancang untuk pengulangan murah — Anda bisa menjalankannya selama setahun data dengan biaya kurang dari lima puluh dolar API. *Window* lima hari adalah demo metodologi, bukan verdik definitif.

**Q3: Bagaimana dengan *overfitting*?**
J: *Traditional bot* punya parameter tetap dari `config.yaml` — tidak di-*tune* di *window* ini. *LLM bot* punya SuperTrend, ADX, MACD yang sama. Tidak ada *hyperparameter search*. Kedua *bot* *out-of-sample* di *window* ini.

**Q4: Bagaimana Anda tahu *cache replay* cocok dengan *run* live?**
J: *Cache key* termasuk *timestamp bar* dalam milidetik. Sama *bar*, sama *prompt*, sama *model* → sama respons. Kami verifikasi ini di *live re-run* `20260516T215247Z` — kurva ekuitas *bit-for-bit* identik.

**Q5: Bagaimana kalau LLM kontradiktif di *bar* yang sama lintas *re-run*?**
J: Dengan `temperature=0` di config dan *prompt builder* deterministik, respons OpenRouter cukup stabil sehingga *cache* *hit* sempurna. Kami belum pernah melihat *drift*.

**Q6: Kenapa bobot konsensus spesifik itu — 0.40, 0.35, 0.25?**
J: Pilihan *spec* dari literatur asal kami bangun. QABBA mendapat bobot tertinggi karena *order flow* adalah indikator paling *leading* di pasar likuid. Visual kedua karena pola *chart* menangkap konteks *multi-scale*. Technical terendah karena informasinya paling redundan dengan *SuperTrend gate*. Apakah urutan ini benar adalah persis pertanyaan yang ditanyakan Hipotesis 1 di bagian hasil.

**Q7: Bisakah Anda mengganti *decision node* deterministik dengan LLM lain?**
J: Bisa — arsitekturnya memungkinkan. *Template prompt* di `prompts.py:73` sudah ada untuk keperluan *logging*. Kami memilih matematika deterministik untuk *auditability* — saat sesuatu terlihat salah, kami bisa membuktikan apa yang terjadi. Kalau LLM yang memutuskan, properti itu hilang.
