# Marvel (Cooler Box) — EP aktif
# Tab: format QJMOTOR "YYMM - Bulan", TAPI kode YYMM sering salah bulan
# (mis. "2610 - November" padahal November) — kata bulan yang dipercaya.
# Tanggal campur DD/MM/YYYY dan MM/DD/YYYY (US).
SPEC = {
    "columns": {
        "tanggal": ["tanggal upload"],
        "status": ["content status"],
        "tipe": ["content types"],
        "link": ["link content", "link design/video"],
        "cover": ["link cover"],
        "caption": ["caption"],
        "desc": ["descriptions"],
    },
    "judul_mode": "title",
    "desc_fallback": True,
}
