# Honda NTB — Bell Content Bank List for Honda NTB
# Tab: "BULAN YYYY" (NOV 2026). TIDAK ada kolom Title → judul dari
# Main Topic + Subtopic. Tanggal MM/DD/YYYY (US). Link Design/Video bisa
# berisi angka indeks — dibiarkan apa adanya kalau tidak ter-resolve.
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
    "judul_mode": "main_sub",
    "desc_fallback": True,
    # Sebagian konten Honda mirror ke TikTok dan IG — ditandai di Content Types
    "platform_map": {
        "tiktok videos": "TikTok",
        "reels/tiktok videos": "Instagram + TikTok",
        "reels ig videos, reels/tiktok videos": "Instagram + TikTok",
        "feed - single post, tiktok picture/design": "Instagram + TikTok",
    },
}
