# Bell Content Dashboard

Dashboard jadwal upload konten Bell Digital Agency. Pilih tanggal → daftar
konten yang harus dipost hari itu per klien (platform, tipe, judul, link
konten/cover, caption).

- `index.html` — dashboard statis (GitHub Pages)
- `data.json` — agregat EP semua klien, di-refresh otomatis tiap jam oleh Hermes
  (script `ep_mirror_sync.py` membaca sheet EP di Google Drive, tanpa AI)
- Sumber data: sheet `Bell Content Bank List for <Client>` di Google Drive
