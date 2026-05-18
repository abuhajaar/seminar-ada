# Naskah Penyampaian Bahasa Indonesia — 30 Menit (Fokus Data Pipeline)

Target: ~150 kata/menit; ~22 menit bicara + ~3 menit demo + transisi = 30 menit total.
Mengacu pada nomor slide di `slide_outline.md`.

Gaya bahasa: **conversational-akademik**, istilah teknis tetap dalam bahasa Inggris (contoh: *pipeline*, *prompt*, *signal*, *stop-loss*, *cache replay*). Analogi *single-thread*: **tiga analis di ruang trading**.

---

## Bagian 1 — Konteks, Masalah & Hipotesis (00:00 → 04:00)

[SLIDE 1: Judul]
[00:00]

Selamat pagi semua, terima kasih sudah hadir. Seminar hari ini tentang dua *trading bot*, dibandingin sisi-ke-sisi pakai data yang sama persis. Judulnya "Comparative Study: Classical TA vs LLM Multi-Agent on BTC/USDT," dan topiknya masuk Advanced Data Analysis. Jadi sebelum saya tunjukin kode apa pun, saya mau setup dulu masalahnya — dua *bot* ini apa, kenapa ada orang yang mau bikin *bot* berbasis LLM, dan apa sebenernya yang mau kami cari tahu.

[BULLETS]
- Comparative Study: Classical TA vs LLM Multi-Agent on BTC/USDT
- Topik seminar: Advanced Data Analysis
- Hari ini: setup masalah dulu, baru jalanin *pipeline*-nya

[NOTE TO PRESENTER] Pembukaan tenang. Jangan dulu masuk ke analogi tiga analis — itu masuk di slide 3.

[SLIDE 2: Masalahnya Apa]
[00:45]

Oke jadi gini. Pasar crypto itu jalan dua puluh empat jam sehari, tujuh hari seminggu, nggak ada libur. Nggak ada manusia yang bisa duduk di meja terus mutusin tiap lima belas menit selama lima hari nonstop. Makanya orang bikin *bot*. Cara klasiknya — saya sebut **traditional bot** ya — pakai *rulebook* tetap: kalau EMA-cepat *cross* di atas EMA-lambat dan MACD konfirmasi, beli. Logika *hard-coded*. *Input* sama, *output* sama, selalu. Cepat, murah, prediktabel, dan udah jadi standar industri selama dua dekade.

Tapi nah, di sini *catch*-nya. *Bot rulebook* itu cuma ngeliat apa yang aturannya pelototin. Kalau aturannya bilang "*EMA cross*", dia nggak akan sadar ada pola *candle* merah gede di sebelahnya. Dia nggak akan sadar bahwa pembeli udah "ngentak" *offer* sepuluh kali berturut-turut. Dia buta sama apa pun yang nggak masuk ke aturan itu. Jadi pertanyaan studi kita: **gimana kalau kita kasih *bot* ini "mata"?**

[BULLETS]
- Pasar crypto: 24/7, manusia nggak bisa nguikutin
- *Traditional bot* = *rulebook* tetap, cepat, prediktabel
- Keterbatasan: buta sama apa pun di luar aturan

[NOTE TO PRESENTER] Jeda sebelum "kasih *bot* ini mata" — itu titik pivotnya ke ide LLM.

[SLIDE 3: Ide — Tiga Analis di Ruang Trading]
[01:50]

Nah, inilah ide yang kami uji. Bayangin ada tiga analis duduk di satu ruang trading kecil. Yang pertama pelototin panel indikator — EMA, MACD, semua skalar angka. Yang kedua baca *candle chart* kayak baca radiograph, nyari bentuk dan pola. Yang ketiga pantau *buy-sell flow* — siapa yang lagi ngentak *bid*, siapa yang lagi narik *offer*, *real-time*. *Candle* Bitcoin lima belas menit yang sama, tiga pasang mata yang sama sekali beda. Tiap analis nulis catatan singkat — BUY, SELL, atau HOLD — geser ke meja bos, terus bos pakai rumus tertimbang tetap buat ngambil keputusan akhir.

**Itulah LLM bot kita.** Tiap analis adalah satu Large Language Model — *model*-nya sama, *engine*-nya sama, tapi tugasnya beda dan *view* datanya beda. Bosnya **bukan** LLM. Bosnya cuma penjumlahan tertimbang. LLM yang ngeliat, matematika yang mutusin. Pemisahan ini penting, nanti saya balik lagi ke sini.

[BULLETS]
- 3 analis LLM: indikator / chart / *order-flow*
- Tiap analis nulis BUY, SELL, atau HOLD plus skor *confidence*
- Si bos = rumus tertimbang tetap, bukan LLM
- LLM ngeliat, matematika mutusin

[SLIDE 4: Hipotesis & Hasil Jujur]
[02:55]

Jadi hipotesisnya simpel. Apakah tim tiga-analis LLM ini — baca data yang sama persis dengan *classical bot* — bisa kasih keputusan trading yang kompetitif? Saya jujur dari awal: **nggak, paling nggak di window uji kami.** LLM bot kami rugi. *Classical bot*-nya menang. Itu temuannya. Yang bikin studi ini bisa dipertanggungjawabin secara akademis adalah kami bangun *test bench* yang *byte-level reproducible*, dan kami laporin apa yang keluar — bukan yang kami harapkan.

Jadi tugas saya hari ini bukan jualan LLM. Tugas saya hari ini ngajak Anda jalanin *pipeline*-nya dari ujung ke ujung dan nunjukin di mana persisnya LLM kehilangan *edge*-nya. Sebagian besar waktu bakal duduk di *data layer*.

[BULLETS]
- Hipotesis: tim LLM bisa nyamain atau ngalahin *classical TA*
- Terukur: LLM rugi, *classical* menang
- Hari ini: jalanin *pipeline* yang ngasih hasil ini

[NOTE TO PRESENTER] Jeda dua detik setelah "rugi" — biarkan tertanam.

---

## Bagian 2 — Sumber Data & Input Mentah (04:00 → 07:00)

[SLIDE 5: Sumber Data]
[04:00]

Oke jadi sebelum ketiga analis kita bisa ngapa-ngapain, mereka butuh data. Dan data itu harus dari sumber nyata. Kami ambil data pasar dari **Binance Spot**, exchange crypto terbesar berdasarkan volume. Aset-nya BTC terhadap USDT, *timeframe* lima belas menit per *bar*, *window* uji lima hari — sepuluh sampai lima belas April 2025. Totalnya empat ratus delapan puluh *bar*. Bayangin tiap *bar* itu kayak satu "*snapshot*" pasar, satu per lima belas menit — itulah bahan baku yang bakal "dikunyah" sama tiga analis kita.

Kami pakai dua *endpoint*. Yang utama itu *endpoint* klines — `GET /api/v3/klines` — yang ngasih data *candlestick* plus satu field tambahan yang krusial, yaitu `taker_buy_volume`. Sebentar lagi saya jelasin kenapa field ini penting. Ada juga *endpoint* aggTrades yang ngasih tiap *tick* trade, tapi udah nggak kami pakai di *hot path* — pakai data kline aja udah dapet *speedup* enam puluh sampai dua ratus kali. Kode *fetching*-nya ada di `data/downloader.py:42`, lewat method `publicGetKlines` di ccxt.

[BULLETS]
- Binance Spot REST API
- BTC/USDT, 15m, 480 *bar* (2025-04-10 → 2025-04-15)
- Dua *endpoint*: klines (dipakai) + aggTrades (dilewat)
- `data/downloader.py:42`, *paginated* 1000 baris per *page*

[SLIDE 6: Apa yang Binance Kasih (Raw Kline)]
[05:00]

Inilah tampilan *kline* mentah dari Binance. Tiap *candle* dikasih sebagai array JSON dua belas elemen. Dari dua belas field itu, kami simpan tujuh: *timestamp*, OHLC, *volume*, dan `taker_buy_volume`. Yang lima — *close-time*, *quote-volume*, jumlah *trade*, *taker-buy-quote*, plus satu *slot* "ignore" — kami buang langsung pas *write*. Satu hal yang sering bikin orang ketipu: tiap harga dan volume datang sebagai JSON **string**, bukan angka. Jadi kami *cast* sendiri ke float di `downloader.py:113`. Detail kecil, tapi kalau kelewat, seluruh *pipeline* bisa rusak diam-diam.

[BULLETS]
- Array JSON 12 elemen per *candle*
- Simpan 7 field: *timestamp*, OHLC, *volume*, `taker_buy_volume`
- *Cast* string → float di `downloader.py:113`

[SLIDE 7: Kenapa `taker_buy_volume` Penting]
[05:45]

Jadi kenapa kami sebegitu peduli sama satu field tambahan itu? Karena field itulah yang ngasih analis ketiga kita — yang *order-flow* — apa yang dia butuhin buat kerja, **tanpa harus bayar data *tick* yang mahal**. Metriknya namanya *cumulative volume delta*, atau CVD. Bayangin kayak hitungan jalan: tiap kali pembeli agresif "narik" *offer*, hitungan naik; tiap kali penjual agresif "ngentak" *bid*, hitungan turun. Dari waktu ke waktu, kelihatan deh siapa yang menang — pembeli atau penjual.

Matematikanya cuma identitas dua baris. *Volume* sama dengan taker-buy plus taker-sell. *CVD-delta* sama dengan taker-buy minus taker-sell. Kurangi yang satu dari yang lain, dapet: `cvd_delta = 2 × taker_buy_volume − volume`. Selesai. Kami dapat CVD pada dasarnya gratis dari data yang udah ada. Kodenya di `data/cvd.py:50`, fungsi `cvd_from_klines`. *Shortcut* ini doang yang ngasih kami *speedup* 60-sampai-200-kali yang tadi disebut. Jadi analis *order-flow* kita sekarang udah punya hitungannya, murah.

[BULLETS]
- CVD = kumulatif (*aggressive-buy* − *aggressive-sell*)
- Identitas: cvd_delta = 2 × taker_buy_volume − volume
- 60–200× lebih cepat dibanding aggTrades; hasil numerik identik
- `data/cvd.py:50` `cvd_from_klines`

[SLIDE 8: Objek `Bar` Final]
[06:30]

Setelah *preprocessing*, *engine* makan *stream* dataclass `Bar` Python. Bayangin tiap `Bar` itu kayak satu baris rapi di buku log ruang trading — semua yang analis butuh tahu tentang satu irisan pasar lima belas menit. Sembilan field total: *timestamp*, OHLC, *volume*, *taker-buy volume*, CVD kumulatif, dan CVD delta *bar* ini. Satu `Bar` per *slot* lima belas menit. Total 480 objek `Bar`.

*Loader* di `data/loader.py:19` ngecek keselarasan *timestamp* secara ketat antara OHLCV CSV dan CVD CSV — kalau ada satu *timestamp* aja yang nggak sinkron, dia langsung *throw* `ValueError` dan *run* berhenti total. Kami nggak pernah ngebiarin data *silently misalign*. *Bug* macam itu — dua *bar* yang beda pura-pura jadi *bar* yang sama — bakal ngeracunin semua hilirnya. Mendingan *crash* keras daripada diam-diam ngasih jawaban yang salah.

[BULLETS]
- `Bar(timestamp, OHLC, volume, taker_buy_volume, cvd, cvd_delta)`
- Total 480 `Bar`
- *Strict timestamp alignment*; misalignment → ValueError

---

## Bagian 3 — Preprocessing & Transformasi Indikator (07:00 → 12:00)

[SLIDE 9: Disiplin Warmup]
[07:00]

Nah, ada satu aturan kecil tapi penting di sini. Sebelum salah satu *strategy* ngeluarin *signal* pertama, kami nunggu enam puluh *bar*. Kenapa enam puluh? Karena indikator paling lambat di *stack* kami — MACD parameter dua belas, dua puluh enam, sembilan — baru ngasih nilai valid pertamanya di *bar* ke-tiga puluh empat. SuperTrend butuh sekitar sepuluh *bar* buat *ATR seasoning*. EMA-50 jelas butuh lima puluh *bar*. Jadi enam puluh ngasih *ceiling* yang aman di atas semuanya.

Konstanta ini ditegakkan di kedua *strategy* — `strategies/traditional.py:38` dan `strategies/llm_agents/strategy.py:39`. Tanpa ini, analis-analis LLM kita bakal nerima *prompt* yang isinya literal string `"nan"` — itu "not a number" — dan mereka bakal halusinasi pede tentang data sampah. Kami belajar ini dari proses audit, susah payah. Jadi sekarang kami tinggal nunggu. Analis-analisnya bahkan nggak masuk ke ruang trading sebelum mereka punya angka beneran buat diliat.

[BULLETS]
- WARMUP = 60 *bar* sebelum *signal* apa pun
- Indikator terlambat: MACD(12,26,9), valid pertama di *bar* 34
- Ditegakkan di kedua *strategy*
- *Bug* pra-fix: *prompt* bocor `"nan"`, audit H1/H3

[SLIDE 10: Inventaris Indikator]
[08:00]

Oke, inilah inventaris lengkap indikatornya. Anggep aja ini *toolkit* di meja tiap analis. EMA periode dua puluh dan lima puluh buat *traditional bot*, dua belas dan dua puluh enam buat *LLM bot*. RSI periode empat belas. MACD dua belas atas dua puluh enam dengan *signal* sembilan. ADX periode empat belas sebagai *trend-strength filter*. SuperTrend *length* sepuluh, *multiplier* tiga — dipakai jadi *stop-loss* sekaligus indikator regim. Dan terakhir CVD, yang cuma analis *order flow* kita — *QABBA agent* — yang dapet.

Perhatikan divergensi EMA-nya. *Traditional bot* pakai 20/50, *cross* medium-term klasik. *LLM bot* pakai 12/26, yang lebih cepat dan reaktif — dan ini selaras sama periode MACD, jadi LLM dapat *signal* yang internally konsisten. Pilihan parameter yang sengaja. LLM dapet *signal* lebih cepat karena dia diharapin "mikir lebih keras" tentang *signal*-nya. Apakah itu bijak — ya, datanya bakal kasih tahu kita dua puluh menit lagi.

[BULLETS]
- EMA: 20/50 (Trad), 12/26 (LLM)
- RSI(14), MACD(12,26,9), ADX(14)
- SuperTrend(10, 3) — *stop* + regim
- CVD — hanya LLM

[SLIDE 11: SuperTrend Lebih Dekat]
[09:30]

SuperTrend layak dapet slide sendiri karena dia ngerjain dua tugas sekaligus — dan nanti dia bakal muncul lagi, jadi mendingan kita ngerti dia dulu sekarang. Matematikanya simpel: ambil titik tengah *high* dan *low* — namanya `hl2` — terus tambah atau kurangi tiga kali ATR. Dapet dua *band* dasar, satu di atas harga, satu di bawah. Aturan *carry-forward* bikin *band*-nya *trailing* — dia cuma melonggar, nggak pernah nyempit lawan tren. Jadi kalau harga lagi naik, *band* bawah ngikut naik; kalau harga turun, *band* atas ngikut turun.

Fungsinya ngembaliin dua kolom: `st`, harga garis *stop*-nya, dan `dir`, tanda regim. Pas `dir` plus satu, garisnya **di bawah** harga — itu *long-friendly*. Pas `dir` minus satu, garisnya **di atas** harga — itu *short-friendly*. Bayangin kayak lampu rambu lalu lintas yang sekaligus jadi *guardrail* — dia kasih tahu kamu boleh ke arah mana, dan di mana harus *stop* kalau salah. Kode: `indicators/ta.py:124`.

[BULLETS]
- `hl2 ± 3 × ATR(10)` dengan *carry-forward*
- *Returns*: `st` (*stop-line*), `dir` (+1 long, −1 short)
- Dua tugas: level *stop* **dan** *regime gate*
- `indicators/ta.py:124`

[SLIDE 12: Diagram Pipeline Transformasi]
[10:30]

Nyatuin semuanya, inilah *pipeline* ujung ke ujung. Binance REST ngasih kline JSON dua belas kolom. ccxt *paginate* seribu baris sekaligus. Kami tulis tujuh kolom ke OHLCV CSV. Kami turunkan CVD ke file CSV terpisah — format *plain-text* yang sama, gampang di-*diff*, gampang di-*inspect*. *Loader* gabungin keduanya di *timestamp* terus ngasih *stream* objek `Bar`. Dari *stream* itu, dua konsumen bercabang — *rulebook* tradisional di sini, *feature extractor* LLM plus *chart renderer* di sini.

Nah, ini poin kuncinya. Semua yang **di hilir** *Bar stream* itulah yang bikin kedua *bot* beda. Semua yang **di hulu** *Bar stream* adalah *shared*. Exchange sama, *bar* sama, indikator sama. Pemisahan itu sengaja — itulah yang bikin perbandingannya adil. Kedua *bot* dapat *window* ruang trading yang sama, pandangan pasar yang sama. Yang berubah cuma siapa yang duduk di meja dan cara mereka mutusin.

[BULLETS]
- *Shared upstream*: REST → OHLCV + CVD → *Bar stream*
- Hanya bercabang setelah `Bar`: *rules* vs *features+chart*
- Input sama, *processing* beda — itu perbandingan yang adil

---

## Bagian 4 — Traditional Bot: Data → Signal → Trade (12:00 → 16:00)

[SLIDE 13: Rulebook]
[12:00]

Kita mulai dari yang lebih sederhana dulu — *traditional bot*. Bayangin ini kayak satu analis senior yang kerja sendirian, ngikutin *checklist* tetap. Nggak ada diskusi, nggak ada *second opinion*, cuma *rulebook*. Seluruh aturannya muat di satu slide. Filter pertama: ADX di atas dua puluh — harus ada tren beneran, kalau nggak ya udah, kita diem aja. Terus: kalau EMA-20 di atas EMA-50, DAN histogram MACD positif, DAN RSI di bawah tujuh puluh, DAN arah SuperTrend plus satu — *go long*. Kondisi cermin buat *short*. Selain itu, HOLD.

Ini namanya *confluence rule* — empat indikator harus setuju semua. Seratus persen deterministik. Sama *bar*, sama *signal*, tiap kali. Kalau kamu *run* dua kali di data yang sama, kamu dapet jawaban *bit-for-bit* identik. Nggak ada kejutan, nggak ada kreativitas. Kode: `strategies/traditional.py:47`.

[BULLETS]
- Filter ADX > 20 (tren wajib ada)
- BUY: EMA20>EMA50 & MACD_hist>0 & RSI<70 & ST_dir=+1
- SELL: kondisi cermin
- 100% deterministik — sama *bar*, sama *signal*

[SLIDE 14: Objek Signal]
[13:30]

*Strategy*-nya ngeluarin dataclass `Signal` — pada dasarnya catatan terstruktur. Empat field: *action*, angka *confidence* yang diturunin dari seberapa kuat ADX-nya, *reasoning string* yang bisa dibaca manusia buat *logging*, dan yang krusial — harga *stop-loss*, yang isinya cuma garis SuperTrend pada *bar* ini.

Nah, perhatikan yang **nggak ada**-nya. Nggak ada *position size*. Itu sengaja. *Strategy*-nya kami bilang *sizing-agnostic*. Dia cuma bilang "saya pengen *long* di harga ini dengan *stop* ini." Dia nggak bilang "beli dua BTC." *Engine* yang urus *position size* terpisah. Pemisahan ini bikin kami bisa pakai ulang logika *risk-sizing* yang persis sama buat kedua *bot* nanti — jadi pas kami bandingin hasil, kami beneran ngebandingin *pengambilan keputusan*-nya, bukan *risk-management*-nya.

[BULLETS]
- `Signal(action, confidence, reasoning, stop_loss)`
- *stop_loss* = garis SuperTrend pada *bar* ini
- *Strategy* *sizing-agnostic* — *engine* yang urus risiko

[SLIDE 15: Signal → Trade]
[14:30]

Sekarang *engine*-nya — di sinilah *signal* jadi *trade* beneran. Lima langkah per *bar*, dalam urutan persis ini. Langkah satu — *check stops* di *bar* yang baru terbuka; kalau *intra-bar low* nyentuh *stop* kita di posisi *long*, kami tutup di harga *stop*. Langkah dua — *fill* order apa pun yang di-*queue* sama *bar* sebelumnya; harga *fill*-nya adalah **open *bar* ini**, plus atau minus *slippage*. Poin krusial — kami **nggak pernah** *fill* di *bar* tempat *signal*-nya dihasilkan. Kenapa? Karena itu *look-ahead bias* — pakai informasi yang seharusnya belum kita tahu pas *signal*-nya dibuat. Langkah tiga — *strategy* ngeluarin *signal* baru. Langkah empat — kalau bukan HOLD, kami *size* posisi pakai `size_position`, yang ngitung *fees* dan *slippage* dalam *worst-case stop-out loss*. Risiko per *trade* dua persen dari ekuitas. Langkah lima — *mark equity* di *bar close* buat kurva ekuitas.

Loop lima-langkah yang sama ini jalan buat **kedua** *bot*. Mereka cuma beda di langkah tiga — siapa yang lagi ngambil keputusan. Selebihnya identik. Kode: `core/engine.py:175`, *sizing* di `core/engine_sync.py:29`.

[BULLETS]
- 1) check_stops → 2) fill_pending(open + slip) → 3) on_bar → 4) size + queue → 5) mark
- *Fill* di *open bar* berikut — tanpa *look-ahead bias*
- risk_pct=0.02, fees=4 bps, slippage=2 bps
- *Loop* identik untuk kedua *bot* — hanya beda di langkah 3

---

## Bagian 5 — LLM Bot: Features → 3 Agents → Consensus → Trade (16:00 → 22:00)

[SLIDE 16: Kenapa Multi-Agent]
[16:00]

Oke, sekarang kita masuk ke jantung talk-nya — ruang trading tiga-analis itu. Begini intinya: kami **nggak** sekadar nanya satu LLM "haruskah saya BUY?" Itu naif. *Language model* itu halusinasi, dan lebih parah lagi, kamu nggak punya cara buat ngaudit satu jawaban *opaque*. Kalau dia salah, kamu nggak akan tahu kenapa dia salah.

Jadi sebagai gantinya, kami "sewa" tiga *specialised analyst*, masing-masing dengan informasi yang sengaja **disjoint** — nggak tumpang-tindih. *Technical agent* cuma liat skalar indikator — angka di layar. *QABBA agent* cuma liat skalar *order flow* — papan skor pembeli-vs-penjual. *Visual agent* cuma liat *image candlestick chart* — nggak ada angka, cuma gambar. Terus *decision node* deterministik — si bos — ngelakuin matematika *weighted* atas tiga suara mereka. LLM-nya nggak pernah disuruh nggabungin apa pun sendiri — bagian itu *closed-form arithmetic*, nggak ada ruang buat halusinasi. Topologinya kami rangkai pakai LangGraph: `START → {technical, visual, qabba} → decision → END`. Ketiga analisnya jalan paralel, kayak tim beneran yang lagi konferensi di *bar* yang sama. Kode: `strategies/llm_agents/graph.py:45`.

[BULLETS]
- 3 *agent*, input *disjoint* (angka / angka / *image*)
- *Decision* adalah **matematika deterministik**, bukan LLM
- LangGraph *parallel fan-out*
- `graph.py:45`

[SLIDE 17: Ekstraksi Fitur]
[17:30]

Lewat *warmup*, di tiap *bar* kami hitung *dict* fitur. Tujuh skalar: EMA-fast, EMA-slow, RSI, histogram MACD, ADX, CVD kumulatif, dan CVD delta *bar* ini. Tiap analis cuma dapet potongan yang relevan buat dia.

Kami juga *render* enam puluh *bar* terakhir jadi PNG *candlestick* pakai `mplfinance` di *Agg backend* — itu matplotlib mode *headless*, yang ngasih PNG *byte-stable* dalam satu *environment*. PNG itu di-*encode* base64 terus "dijepret" ke *prompt*-nya *Visual agent* — kayak digeser ke meja dia bareng catatannya. *Byte-stability*-nya penting karena itu yang ngebikin *cache replay* nanti bisa kerja — *chart* sama, *hash* sama, *cache hit*. Kode: `strategies/llm_agents/strategy.py:91`, *chart rendering* di `chart.py:26`.

[BULLETS]
- 7 fitur skalar per *bar*
- + PNG *candlestick* 60-*bar* (mplfinance, *Agg backend*)
- *base64-encoded* untuk agent Visual
- *Byte-stable* dalam satu *environment* → memungkinkan *cache replay*

[SLIDE 18: Prompt per Agent]
[19:00]

Ini *template prompt* yang **sebenernya**, langsung dari `prompts.py` — bukan parafrase. *Technical agent* dapat: "You are a technical analyst. Given these indicator readings... output one of BUY, SELL, HOLD followed by a confidence in zero-to-one and a one-line rationale. Format: ACTION CONFIDENCE RATIONALE. Features: ema_fast sekian, ema_slow sekian, rsi, macd_hist, adx." QABBA dapat struktur yang sama persis tapi cuma bacaan CVD — cuma itu yang ada di mejanya. Visual dapet deskripsi peran ditambah *image* terlampir — dan yang khas, nggak ada angka di teksnya sama sekali. Dia kudu baca gambarnya.

Tiga pilihan desain yang sengaja di sini. Satu — kami batasin format output secara agresif, `ACTION CONFIDENCE RATIONALE`, supaya *regex parser* bisa ngekstrak jawabannya bersih. Dua — kami *render* angka pakai *formatter* custom yang nggak pernah pakai notasi saintifik, karena regex-nya nggak ngerti `e+06`. Tiga — kami bikin *prompt*-nya singkat, sebagian buat kejelasan, sebagian buat tetap di dalam *budget cap* sepuluh dolar per *run*. Tiap token itu duit di skala besar.

[BULLETS]
- 3 *prompt*, *template* literal dari `prompts.py`
- Output dibatasi: `ACTION CONFIDENCE RATIONALE`
- Tanpa notasi saintifik (keterbatasan *regex parser*)
- Singkat → muat di *budget* $10/*run*

[SLIDE 19: Respons Cached Sungguhan]
[20:30]

Nah, slide ini — perhatikan baik-baik — inilah tampilan respons sungguhan buat satu *bar*. Diambil langsung dari *cache* yang kami *commit*, dari *run* Claude Haiku 4.5 nyata. *Technical agent* — yang liat angkanya — bilang HOLD dengan *confidence* 0.62, ngejelasin *signal* EMA *crossover*-nya lemah. QABBA — yang liat papan skor *order flow*-nya — bilang SELL 0.72, nge-flag CVD delta negatif sekitar minus lima puluh tujuh unit. *Visual agent* — yang melototin *chart*-nya — bilang SELL 0.72, mendeskripsiin *downtrend* yang jelas di gambar. Ketiga responsnya objek JSON di disk — *content*, *model*, *input tokens*, *output tokens*.

Token pertama sebelum *confidence* itu yang diekstrak *regex parser* kami di `nodes/_parse.py:16`. Dia sengaja toleran — ngambil token BUY-SELL-HOLD pertama yang dia temuin, *case-insensitive*, sama *word boundary* — jadi analis-analisnya boleh agak "berantakan" di prosanya, kami tetap dapet suara yang bersih.

[BULLETS]
- Respons Claude Haiku 4.5 nyata di disk (*cache replay*)
- Tiga suara untuk SATU *bar*: HOLD 0.62, SELL 0.72, SELL 0.72
- *Regex parser* toleran terhadap *noise* di sekitar token

[SLIDE 20: Matematika Decision]
[21:00]

Sekarang si bos ngambil keputusan. Dan ini menariknya — kamu mungkin ngira ada panggilan LLM lagi di sini, kan? Chairman yang mempertimbangkan opini analis-analisnya? Nope. Nggak ada LLM di sini sama sekali. Cuma matematika *closed-form* biasa. Bobotnya dari file config: QABBA 0.40, Visual 0.35, Technical 0.25 — *order flow* dapat bobot tertinggi karena dia cenderung *leading*, Technical paling rendah karena dia tumpang-tindih sama *SuperTrend gate* kita. Buat tiap sisi — BUY dan SELL — kami jumlahin *weighted confidence* dari analis yang memilih sisi itu. *Threshold*-nya 0.35. Sebuah sisi menang kalau dan hanya kalau skornya nyebrang *threshold* **dan** *strictly* lebih besar dari sisi lawan. Selain itu, HOLD.

Yuk kita pakai contoh dari slide sebelumnya di sini. Technical bilang HOLD, jadi dia nggak nyumbang ke sisi mana pun. QABBA bilang SELL 0.72 — itu 0.40 kali 0.72 sama dengan 0.288. Visual bilang SELL 0.72 — itu 0.35 kali 0.72 sama dengan 0.252. Skor SELL totalnya 0.540 — jauh di atas *threshold* 0.35. Jadi keputusan bos: SELL dengan *confidence* 0.540. *Reproducible*, *auditable*, nol halusinasi di tahap ini. Kode: `strategies/llm_agents/nodes/decision.py:33`.

[BULLETS]
- Bobot: Q=0.40, V=0.35, T=0.25; threshold=0.35
- Per sisi: `Σ wᵢ × confᵢ` atas analyst pemilih sisi itu
- Pemenang = max(buy, sell) jika > *threshold* dan > lawan
- Contoh: SELL menang 0.540

[SLIDE 21: Regime Gate + Stop Placement]
[21:30]

Satu *checkpoint* terakhir sebelum *signal*-nya keluar ruang trading. Bayangin ini kayak *risk manager* yang berdiri di pintu. Kalau konsensus bilang BUY tapi regim SuperTrend nunjukin kita lagi *downtrend* — garis di atas harga — *risk manager*-nya *override* ke HOLD. Sebaliknya juga: SELL di *uptrend* jadi HOLD. Kenapa repot-repot? Karena *engine* punya *stop-direction check* di `core/engine.py:121` yang **diam-diam** nolak order dengan *stop* di sisi yang salah. Sebelum *gate* ini ada, kami sebenernya ngeluarin *signal* ke kekosongan — muncul di log tapi nggak pernah beneran buka posisi. Kami nemu itu di *re-audit* dan kami patch sebagai fix C3.

Setelah *gate* ini, *LLM bot* ngeluarin dataclass `Signal` yang persis sama kayak *traditional bot*. Dan dari titik itu ke depan, alur eksekusi *trade*-nya **identik**. *Engine* sama, *broker* sama, *risk sizing* sama, *fees* sama. Satu-satunya yang beda antara kedua *bot* cuma apa yang menghasilkan *signal*-nya — *confluence rule* lawan tiga analis plus bos. Semuanya setelah `Signal` itu *shared*.

[BULLETS]
- BUY di regim turun → HOLD; SELL di regim naik → HOLD
- Tanpa ini: *signal* dibuang *silently* oleh *engine H4 gate*
- Patch C3 di `strategy.py:184`
- Dari `Signal` ke hilir: eksekusi identik dengan *traditional*

---

## Bagian 6 — Demo Live (22:00 → 25:00)

[SLIDE 22: Live Cache-Replay]
[22:00]

Oke, sekarang saya tunjukin ini jalan. Demo-nya adalah ***cache replay*** — dan ini penting. Kami **nggak** manggil OpenRouter live selama seminar, karena itu bakal beresiko masalah jaringan ngabisin waktu talk saya. Sebagai gantinya, kami udah *commit* seribu dua ratus enam puluh tiga respons LLM ter-*cache* ke disk. Bayangin ini kayak rekaman transkrip tiap *meeting* analis dari *window* uji — kami tinggal pencet "play" daripada nanya mereka lagi.

*Cache key*-nya tuple — *model*, nama agent, hash *prompt*, hash *image*, dan *timestamp bar* dalam milidetik. Jadi tiap panggilan LLM yang `main.py` lakuin masuk ke *cache* alih-alih jaringan. *Run end-to-end* selesai sekitar tiga puluh detik.

Satu hal lagi — buat pertanyaan audit *live*, kami bisa nyalain `run.dump_bar_artifacts: true` di `config.yaml`, terus tiap satu *candle* ninggalin folder di bawah `results\runs\<id>\BTC_USDT\bars\<NNN>\`. Di dalam tiap folder: *scalar* indikator persis yang *traditional bot* liat, *prompt* persis yang tiap analis LLM terima, *chart* PNG yang dikirim ke *visual agent*, balasan teks mentah, dan *decision* JSON final. Jadi kalau ada yang nanya di ruangan, "*chart analyst* tadi sebenernya liat apa di *bar* 217?" — kami tinggal buka folder itu dan tunjukin, *byte-for-byte*.

[NOTE TO PRESENTER] Pindah ke terminal. Jalankan `.\.venv\Scripts\python.exe main.py`. Berbicara sambil Rich TUI ter-update: *signal* per *bar*, kurva ekuitas, jumlah *trade*, *win percentage*, *max drawdown*. Total elapsed sekitar tiga puluh detik.

[NOTE TO PRESENTER] Setelah selesai, sebutkan *run summary* tersimpan di `results/runs/<timestamp>/summary.json`. Kembali ke slide.

---

## Bagian 7 — Hasil (25:00 → 28:00)

[SLIDE 23: Angka Headline]
[25:00]

Oke, papan skornya. *Traditional bot* — si analis senior solo — narik *return* plus 3.07 persen, *max drawdown* minus 6.46 persen, empat *trade*, *win rate* lima puluh persen, *profit factor* 1.72, *Sharpe* 0.40. *LLM bot* — ruang trading tiga-analis — narik *return* minus 6.20 persen, *max drawdown* minus 10.90 persen, sepuluh *trade*, *win rate* tiga puluh persen, *profit factor* 0.41, *Sharpe* minus 0.71. LLM-nya rugi. Dia *trade* lebih banyak, menang lebih sedikit, *drawdown* lebih dalam. *Run identifier* di disk: `20260516T215247Z` — siapa pun di ruangan ini bisa nge-*run* ulang sendiri dan dapet angka yang persis sama.

[BULLETS]
- Trad: +3.07% / DD −6.46% / 4 *trade* / PF 1.72
- LLM:  −6.20% / DD −10.90% / 10 *trade* / PF 0.41
- LLM rugi, *over-trade*, *drawdown* lebih dalam

[SLIDE 24: Atribusi Kerugian]
[26:00]

Jadi sebenernya kerugiannya dari mana? Yuk pisahin *trade* LLM-nya berdasarkan arah. Lima *trade* BUY total plus dua puluh dua dolar — pada dasarnya datar. Lima *trade* SELL total **minus enam ratus empat puluh dua dolar**. Itu hampir semua kerugiannya, di posisi *short*-nya. Sementara itu, pasar bertren dari 80,800 naik ke 85,500 — *uptrend* yang jelas, lima setengah persen. Jadi ruang trading tiga-analis kita terus-terusan nge-*fade uptrend* beneran. Mereka terlalu kebelet jualan.

Sebaliknya, si analis senior tradisional megang satu posisi BUY selama dua ratus *bar* dan nangkep plus 4.42 persen. *Average hold time* LLM cuma tiga puluh tujuh *bar* — dia *over-trade* sekitar dua setengah kali. Jadi LLM-nya salah arah *sekaligus* nggak sabar sama *time horizon*-nya.

[BULLETS]
- LLM BUY: 5 × +$22 total
- LLM SELL: 5 × **−$642 total**
- Pasar bertren +5.8%; LLM mem-*fade* tren
- LLM *avg hold* 37 *bar* vs Trad 96 *bar*

[SLIDE 25: Tiga Hipotesis Jujur]
[27:00]

Tiga hipotesis jujur kenapa ini terjadi — semua *testable* di *harness* yang sama. Pertama — bobot CVD 0.40 itu bobot terbesar di matematika *decision*, dan *order flow* di *timeframe* lima belas menit itu *noisy*. Kemungkinan besar kami terlalu *overweight* tekanan jual *short-term*. Kedua — SuperTrend *length* sepuluh, *multiplier* tiga, *flip* karena *intra-bar noise*. *Filter* regim *longer-horizon* — misal SuperTrend *daily overlay* yang berdiri di atas yang lima belas menit — kemungkinan bakal ngebersihin sebagian besar *short* yang buruk. Ketiga — dan ini menarik — LLM-nya nggak punya gambaran sama sekali bahwa *trade* itu ada biayanya. Dia *reasoning* seolah tiap *trade* gratis. *Engine* memang men-*fee-discount* *sizing*-nya, tapi LLM-nya nggak pernah *belajar* dari biaya itu. Dia ya *trade* aja terus. Ketiganya eksperimen lanjutan yang konkret — dan *harness cached-replay*-nya bikin mereka murah buat dicoba.

[BULLETS]
- H1: Bobot CVD 0.40 terlalu tinggi untuk *timeframe* 15m
- H2: SuperTrend(10,3) terlalu *jittery* — perlu *filter longer-horizon*
- H3: LLM tidak tahu biaya *fee*/*slippage*
- Ketiganya *testable* di *harness* yang sama

---

## Bagian 8 — Kesimpulan + Q&A (28:00 → 30:00)

[SLIDE 26: Kontribusi + Pertanyaan Terbuka]
[28:00]

Untuk menutup. Kontribusi kami **bukan** "LLM mengalahkan analisis teknis" — di *window* kami, nggak. Kontribusi kami adalah *comparison harness* yang *reproducible* dan *byte-deterministic*. Respons ter-*cache* di disk artinya siapa pun di sini bisa nge-*run* ulang eksperimen kami dan dapet angka yang persis sama. Matematika *decision*-nya *closed-form*. *Data pipeline*-nya terdokumentasi ujung ke ujung. Hasil LLM yang rugi itu temuan yang men-*scope* di mana LLM ngebantu — dan di mana dia nyakitin.

Tiga pertanyaan terbuka yang saya pengen denger masukan ruangan. Pertama — apakah *prompt-engineering* konteks regim secara eksplisit — ngasih tiap analis "pasar udah bertren naik enam persen minggu ini" — akan ngubah hasilnya? Kedua — apakah lima belas menit itu terlalu *noisy* sebagai *timeframe* buat ngebandingin *rules* deterministik sama LLM probabilistik secara apel-ke-apel? Ketiga — haruskah ***decision node* itu sendiri** jadi LLM, dengan *context window* yang tepat? Terima kasih — saya senang nerima pertanyaan.

[BULLETS]
- Kontribusi: *comparison harness* reproducible *byte-deterministic*
- Kerugian LLM adalah temuan *scoping*, bukan kegagalan
- Tiga pertanyaan terbuka untuk ruangan
- Terima kasih

[NOTE TO PRESENTER] Buka lantai. Anchor jawaban di referensi kode — `strategies/llm_agents/strategy.py`, `nodes/decision.py`, `prompts.py` — supaya pertanyaan tetap teknis.

---

## Apendiks Q&A (jawaban siap pakai)

**Q1: Kenapa Claude Haiku, bukan GPT-4 atau model lokal?**
J: Jujur? Biaya. Haiku 4.5 sekitar dua puluh kali lebih murah daripada Claude Sonnet, di satu dolar per juta *input token*. Buat studi dengan *bar* sebanyak ini — 480 *bar* kali 3 *agent* sama dengan 1.440 panggilan LLM per *run* — biaya jadi penting banget. Tapi kami bisa ganti model dengan mudah, kok — `config.yaml` baris 28 — dan *cache*-nya *invalidate* otomatis pas model berubah.

**Q2: Apakah 480 *bar* cukup buat kesimpulan statistik?**
J: Nggak, jujur. Dan kami nyatain itu di kesimpulan. *Harness*-nya dirancang buat pengulangan murah — kamu bisa nge-*run* setahun data dengan biaya kurang dari lima puluh dolar API. *Window* lima hari itu demo metodologi, bukan verdik definitif tentang LLM trading.

**Q3: Bagaimana soal *overfitting*?**
J: *Traditional bot* punya parameter tetap langsung dari `config.yaml` — nggak di-*tune* di *window* ini. *LLM bot* pakai SuperTrend yang sama, ADX yang sama, MACD yang sama. Nggak ada *hyperparameter search*. Kedua *bot* *out-of-sample* di *window* ini.

**Q4: Gimana cara tahu *cache replay*-nya cocok sama *run* live?**
J: *Cache key*-nya termasuk *timestamp bar* dalam milidetik. *Bar* sama, *prompt* sama, model sama → respons sama. Kami verifikasi ini di *live re-run* `20260516T215247Z` — kurva ekuitas *bit-for-bit* identik. Jadi *replay* yang tadi kalian lihat di demo itu setia ke apa yang bot bakal lakuin *live*.

**Q5: Gimana kalau LLM-nya kontradiktif di *bar* yang sama lintas *re-run*?**
J: Dengan `temperature=0` di config dan *prompt builder* deterministik, respons OpenRouter cukup stabil sehingga *cache hit*-nya sempurna. Kami belum pernah liat *drift* di praktiknya.

**Q6: Kenapa bobot konsensus spesifik itu — 0.40, 0.35, 0.25?**
J: Itu pilihan *spec* dari literatur tempat kami bangun. QABBA dapat bobot tertinggi karena *order flow* cenderung jadi indikator paling *leading* di pasar likuid — dia ngasih tahu kamu *siapa yang lagi trading beneran* sebelum harganya banyak bergerak. Visual kedua karena pola *chart* nangkep konteks *multi-scale* yang skalar indikator nggak bisa. Technical paling rendah karena informasinya paling banyak tumpang-tindih sama *SuperTrend gate* kita — dia sebagian ngomong hal yang *gate*-nya udah tahu. Apakah urutan ini bener — itulah persis yang Hipotesis 1 di bagian hasil tanyain.

**Q7: Bisa nggak *decision node* deterministik-nya diganti sama LLM lain?**
J: Bisa — arsitekturnya ngebolehin. *Template prompt* di `prompts.py:73` udah ada buat keperluan *logging*. Kami pilih matematika deterministik buat *auditability* — pas ada yang keliatan salah, kami bisa buktiin persis apa yang terjadi. Kalau LLM yang jadi bos juga, properti itu hilang. Buat studi perbandingan akademis, *tradeoff*-nya kami rasa nggak sepadan. Tapi buat produksi, mungkin beda cerita.
