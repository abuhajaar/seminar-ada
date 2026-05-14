# Spec: Penegakan Budget Guard — Pengaman Live OpenRouter

**Tanggal:** 2026-05-14
**Status:** Disetujui
**Mengganti:** Item tech-debt sub-plan C "BudgetGuard belum terpasang"

> Dokumen ini adalah pasangan Bahasa Indonesia dari
> `2026-05-14-budget-guard-enforcement-design.en.md`. Versi Inggris adalah
> sumber kebenaran apabila terjadi konflik.

## Masalah

`llm.max_usd` di `config.yaml` saat ini hanya berupa komentar. `BudgetGuard`
sudah ada di `llm/budget.py` dan teruji unit-test, tetapi tidak ada jalur
kode produksi yang menginstansiasinya. Akibatnya, run live OpenRouter bisa
melampaui cap tanpa pemutus sirkuit. Run mock-mode tidak terdampak karena
`MockClient` tidak melakukan panggilan jaringan, tetapi demo seminar akan
memakai API OpenRouter sungguhan dan cap harus benar-benar berfungsi.

`BudgetExceededError` saat ini hanya membawa pesan string;
`core/walkforward.py:112` sudah memakai `getattr(e, "spend_usd", None) or 0.0`
secara defensif, tetapi atribut tersebut tidak pernah di-set, sehingga
`spend_usd` yang dicatat selalu `0.0`.

## Tujuan

Menjadikan `llm.max_usd` sebagai plafon dolar per-run yang sungguhan untuk
panggilan live OpenRouter, sambil tetap menjaga replay dari cache tetap
gratis, mock-mode tidak berubah, dan kode engine/strategy lainnya tidak
berubah.

## Bukan-Tujuan

- Streaming `RunState.spend_usd` selama satu aset masih jalan. TUI footer
  di-update sekali per aset (di antara aset) dari `guard.spent_usd`. Streaming
  intra-aset memerlukan thread guard ref ke engine atau `RunState` dan di
  luar lingkup.
- Tokenisasi presisi via `tiktoken` atau tokenizer per-model. Heuristik
  `len(prompt) // 4` cukup pada skala seminar.
- Akuntansi token gambar. Visual node akan under-charge sebesar overhead
  gambar, dapat diterima pada cap $10.
- Pelacakan refund atau billing kegagalan parsial. OpenRouter membebankan
  per-respons sukses; kita mengikuti konvensi itu.

## Arsitektur

Tambahkan lapisan dekorator ketiga pada stack klien LLM:

```
BudgetGuardedClient   ← BARU: estimasi pra-panggilan + charge pasca-panggilan
  └── CachedClient    ← tidak berubah; cache hit short-circuit sebelum guard
        └── OpenRouterClient | MockClient
```

Guard membungkus cache (bukan sebaliknya). Konsekuensinya:

- **Cache miss** mengalir lewat guard → cache → inner. `check_can_afford`
  (pra) dan `charge` (pasca) dijalankan.
- **Cache hit** dilayani oleh `CachedClient` itu sendiri;
  `BudgetGuardedClient` tidak pernah melihatnya. Replay dari cache tetap
  gratis bahkan setelah cap tercapai.

Urutan ini *disengaja* dan merupakan invariant replay seminar: cache yang
sudah di-warm harus dapat diputar offline dengan biaya nol.

## Komponen

### `llm/budget.py` (modifikasi)

`BudgetExceededError` mendapat atribut `spend_usd: float`. `BudgetGuard.check_can_afford`
me-raise dengan `spend_usd=self._spent`.

### `llm/budget_client.py` (baru)

Klien dekorator membungkus `LLMClient` apa pun. Mengimplementasikan `complete()`
dengan tanda tangan yang sama seperti `CachedClient.complete()` (menerima
`bar_ts` kwarg opsional, diteruskan ke inner hanya bila inner adalah
`CachedClient`).

Alur per-panggilan: lookup `pricing[model]` → estimasi → `check_can_afford`
→ panggil inner → hitung biaya aktual dari `LLMResponse.input_tokens /
output_tokens` → `guard.charge(actual)` → return response.

### `core/config.py` (modifikasi)

`PricingCfg` baru dan tambahan pada `LlmCfg`:
- `pricing: dict[str, PricingCfg]`
- `expected_output_tokens: int = 300`
- Validator baru: setiap `agents[*].model` wajib hadir di `pricing`.

### `config.yaml` (modifikasi)

Tambah blok `pricing` (per-model harga in/out per 1 juta token) dan
`expected_output_tokens: 300`.

### `main.py` (modifikasi)

Bangun `BudgetGuardedClient(cached, guard, pricing)` pada jalur non-mock.
Update `rs_holder["rs"].spend_usd = guard.spent_usd` lewat callback
`on_progress` setelah tiap aset.

## Mode kegagalan

| Skenario | Perilaku |
|---|---|
| Cap tercapai pra-panggilan | `BudgetExceededError(spend_usd=guard.spent_usd)` me-raise; walkforward tangkap, catat `{"status": "budget_exceeded", "spend_usd": ...}`, lanjut ke aset berikutnya. |
| Cap tercapai mid-aset | Sama. Portfolios aset tersebut dibuang. |
| Cache hit setelah cap habis | Mengembalikan response cache. Disengaja — replay seminar harus gratis. |
| Model tidak terdaftar di pricing | Mustahil saat runtime: validator `LlmCfg` menolak misconfig pada `load_config`. |
| `cfg.llm.max_usd = 0.0` | Panggilan non-cached pertama langsung me-raise. |
| Klien inner raise (HTTP error) | Naik melewati guard tanpa charge — `charge` hanya berjalan pada response sukses. |
