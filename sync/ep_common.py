#!/usr/bin/env python3
"""Mesin bersama untuk puller EP per klien (tanpa LLM).

Setiap klien punya script sendiri di ep_clients/ yang mendeklarasikan SPEC
(format kolom & tab khas klien itu). Mesin di sini mengurus hal yang sama
di semua EP: auth, rate-limit, baca gridData (hyperlink + smart chip),
normalisasi tanggal, carry-free date (B kosong = belum terjadwal), dan
resolusi link (hyperlink > chip > URL teks > fallback Descriptions).
"""
import json, os, re, time
from datetime import date, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

HOME = os.path.expanduser("~")
HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "ep_sheets.json")

MONTHS = {
    "januari": 1, "january": 1, "jan": 1,
    "februari": 2, "february": 2, "feb": 2,
    "maret": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6,
    "juli": 7, "july": 7, "jul": 7,
    "agustus": 8, "august": 8, "agt": 8, "agu": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nov": 11,
    "desember": 12, "december": 12, "des": 12, "dec": 12,
}
NON_CONTENT = {"info", "pivot", "stock", "stock content", "template",
               "content pillar distribution", "jumlah konten", "req", "sheet3"}

WARN = []
_last_read = {"t": 0.0}
_RATE = 1.1  # jeda antar read — kuota Sheets API 60 read/menit


def warn(msg):
    WARN.append(msg)


def services():
    """Kredensial dari env (GitHub Actions) atau dari ~/.hermes/google_token.json (lokal)."""
    if os.environ.get("GOOGLE_REFRESH_TOKEN"):
        creds = Credentials(
            token=None,
            refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
            token_uri=os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            scopes=os.environ.get("GOOGLE_SCOPES",
                                  "https://www.googleapis.com/auth/spreadsheets "
                                  "https://www.googleapis.com/auth/drive").split(),
        )
    else:
        tok = json.load(open(os.path.join(HOME, ".hermes", "google_token.json")))
        creds = Credentials(token=tok.get("token"), refresh_token=tok.get("refresh_token"),
                            token_uri=tok["token_uri"], client_id=tok["client_id"],
                            client_secret=tok["client_secret"], scopes=tok["scopes"])
    return build("sheets", "v4", credentials=creds), build("drive", "v3", credentials=creds)


def _throttle():
    now = time.time()
    wait = _RATE - (now - _last_read["t"])
    if wait > 0:
        time.sleep(wait)
    _last_read["t"] = time.time()


def get_tabs(svc, sid):
    _throttle()
    meta = svc.spreadsheets().get(spreadsheetId=sid, includeGridData=False).execute()
    return [p["properties"]["title"] for p in meta["sheets"]]


def read_tab(svc, sid, tab):
    """rowData satu tab (gridData, dengan hyperlink + chipRuns), retry + throttle."""
    for attempt in (0, 1):
        try:
            _throttle()
            resp = svc.spreadsheets().get(
                spreadsheetId=sid,
                ranges=[f"'{tab}'!A1:Z"],
                includeGridData=True,
                fields="sheets/data/rowData/values(formattedValue,hyperlink,textFormatRuns,chipRuns)"
            ).execute()
            return resp["sheets"][0]["data"][0].get("rowData", [])
        except Exception as e:
            if attempt == 1:
                raise
            time.sleep(5)


def parse_tab_month(title):
    """(year, month, cleaned) — kata bulan di judul lebih dipercaya dari kode
    YYMM (tab Marvel '2610 - November' berarti November)."""
    t = re.sub(r"^✅\s*", "", re.sub(r"\s+", " ", title.strip()))
    year = None
    yymm = re.match(r"^(\d{2})(0[1-9]|1[0-2])\b", t)
    if yymm:
        year = 2000 + int(yymm.group(1))
        yymm_month = int(yymm.group(2))
    else:
        yymm_month = None
    m4 = re.search(r"(?<!\d)(20\d{2})(?!\d)", t)
    if m4:
        year = int(m4.group(1))
    if year is None:
        m2 = re.search(r"(?<!\d)(\d{2})(?!\d)", t)
        if m2:
            year = 2000 + int(m2.group(1))
    found = []
    for name, num in MONTHS.items():
        for mm in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", t, re.I):
            found.append((mm.start(), len(name), num))
    month = None
    if found:
        _, _, month = sorted(found, key=lambda x: (-x[1], x[0]))[0]
    elif yymm_month:
        month = yymm_month
    if month is None or year is None:
        return None
    return year, month, t


def month_window():
    """(lo, hi) — jendela tab dibaca penuh = bulan lalu s.d. bulan depan."""
    today = date.today()
    y, m = today.year, today.month
    ym = y * 12 + (m - 1)
    lo_y, lo_m = divmod(ym - 1, 12)
    hi_y, hi_m = divmod(ym + 1, 12)
    return (lo_y, lo_m + 1), (hi_y, hi_m + 1)


def norm_date(s, tab_year, tab_month):
    """Normalisasi '10/11/26' | '7/11/2026' | '11/3/2026' (US) -> ISO.
    Kalau D/M/Y dan M/D/Y sama-sama valid, pilih yang bulannya == bulan tab."""
    if not s:
        return ""
    s = s.strip()
    m = re.search(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", s)
    if not m:
        return s
    token = m.group(0)
    parts = [p for p in re.split(r"[-/.]", token) if p]
    if len(parts) != 3:
        return s
    a, b, c = parts
    if len(c) == 2:
        c = "20" + c
    if not (len(c) == 4 and c.isdigit() and a.isdigit() and b.isdigit()):
        return s
    a, b, c = int(a), int(b), int(c)
    if not (2000 <= c <= 2100):
        return s
    cands = []
    if 1 <= b <= 12 and 1 <= a <= 31:
        cands.append((a, b, c))  # D/M/Y
    if 1 <= a <= 12 and 1 <= b <= 31:
        cands.append((b, a, c))  # M/D/Y
    best = None
    for d, mo, y in cands:
        score = 2 if (mo == tab_month and y == tab_year) else (1 if mo == tab_month else 0)
        if best is None or score > best[0]:
            best = (score, d, mo, y)
    if best is None:
        return s
    _, d, mo, y = best
    return f"{y:04d}-{mo:02d}-{d:02d}"


def ci(row, i):
    """(formattedValue, hyperlink, [link dari textFormatRuns/chipRuns]) sel i."""
    if i is None:
        return "", None, []
    vals = row.get("values", [])
    if i >= len(vals):
        return "", None, []
    c = vals[i]
    fv = c.get("formattedValue", "") or ""
    link = c.get("hyperlink") or None
    links = []
    for tfr in c.get("textFormatRuns", []):
        u = ((tfr.get("format") or {}).get("link") or {}).get("uri")
        if u:
            links.append(u)
    for cr in c.get("chipRuns", []):
        u = ((cr.get("chip") or {}).get("richLinkProperties") or {}).get("uri")
        if u:
            links.append(u)
    return fv, link, links


def link_value(raw):
    """Kolom link/cover: hyperlink/chip (URL) menang atas teks label."""
    fv, link, links = raw
    urls = ([link] if link else []) + links
    if urls:
        return "\n".join(dict.fromkeys(urls))
    return (fv or "").strip()


def platform_of(tipe):
    tl = tipe.lower()
    if "tiktok" in tl:
        return "TikTok"
    if "threads" in tl:
        return "Threads"
    return "Instagram"


def select_tabs(titles, lo, hi, old_floor):
    """[(title, (year, month), date_filter)] — tab jendela dibaca penuh,
    tab lama (non-✅, maks 6 bulan) hanya baris bertanggal ≥ 45 hari lalu."""
    picked = []
    for title in titles:
        low = title.strip().lower()
        if low in NON_CONTENT or title.strip().startswith("✅"):
            continue
        parsed = parse_tab_month(title)
        if parsed is None:
            continue
        y, m, _ = parsed
        if lo <= (y, m) <= hi:
            picked.append((title, (y, m), False))
        elif (y, m) >= old_floor:
            picked.append((title, (y, m), True))
    picked.sort(key=lambda x: (-x[1][0], -x[1][1]))
    return picked


def _exact(headers, names):
    for i, h in enumerate(headers):
        if h in names:
            return i
    return None


def pull_client(svc, sid, name, spec, lo, hi, old_floor, cutoff):
    """Baca satu EP sesuai SPEC klien; kembalikan (items, n, last_tab, ok).
    items = dict ternormalisasi: klien, tanggal(ISO|""), status, tipe, judul,
    platform, link, cover, caption, tab."""
    titles = get_tabs(svc, sid)
    picked = select_tabs(titles, lo, hi, old_floor)
    items, n, ok = [], 0, True
    cols = spec.get("columns", {})
    for tab, (ty_, tm_), dflt in picked:
        try:
            rowdata = read_tab(svc, sid, tab)
        except Exception as e:
            warn(f"{name}/{tab}: baca gagal ({type(e).__name__}: {str(e)[:100]})")
            ok = False
            continue
        if not rowdata:
            continue
        hvals = rowdata[0].get("values", [])
        headers = [ci(rowdata[0], i)[0].strip().lower() for i in range(len(hvals))]
        col = {k: _exact(headers, names) for k, names in cols.items()}
        if col.get("tanggal") is None:
            col["tanggal"] = next((i for i, h in enumerate(headers)
                                   if "tanggal" in h or "date" in h), None)
        if col.get("status") is None:
            col["status"] = next((i for i, h in enumerate(headers) if "status" in h), None)
            if col["status"] is None and spec.get("status_column3"):
                col["status"] = _exact(headers, ["column 3"])
        if col.get("link") is None:
            col["link"] = next((i for i, h in enumerate(headers)
                                if "link" in h and "cover" not in h), None)
        jmode = spec.get("judul_mode", "title")
        if jmode == "title":
            col["judul"] = _exact(headers, ["title"]) or \
                next((i for i, h in enumerate(headers) if "judul" in h), None)
        elif jmode == "main_sub":
            col["main"] = _exact(headers, ["main topic"])
            col["sub"] = _exact(headers, ["subtopic"])
        elif jmode == "sub":
            col["sub"] = _exact(headers, ["subtopic"])
        if not dflt:  # peringatan hanya untuk tab jendela aktif
            missing = [k for k in ("tanggal", "status", "tipe") if col.get(k) is None]
            if missing:
                warn(f"{name}/{tab}: kolom {missing} tidak ketemu; headers={headers}")
            if col.get("cover") is None or col.get("caption") is None:
                warn(f"{name}/{tab}: cover/caption tidak ada "
                     f"(cover={col.get('cover')}, caption={col.get('caption')}); headers={headers}")
        for r in rowdata[1:]:
            fv = {k: (ci(r, v)[0] or "").strip() for k, v in col.items() if v is not None}
            tanggal = norm_date(fv.get("tanggal", ""), ty_, tm_) if fv.get("tanggal") else ""
            status = fv.get("status", "")
            tipe = fv.get("tipe", "")
            if jmode == "title":
                judul = fv.get("judul", "")
            elif jmode == "main_sub":
                main, sub = fv.get("main", ""), fv.get("sub", "")
                judul = main + (" — " + sub if main and sub else sub or main)
            else:
                judul = fv.get("sub", "")
            link = link_value(ci(r, col.get("link")))
            cover = link_value(ci(r, col.get("cover")))
            caption = fv.get("caption", "")
            # Fallback link: nama file (bukan kosong, bukan URL) → URL Drive dari
            # Descriptions (baris referensi/sumber dilewati — bukan asset).
            if spec.get("desc_fallback", True) and link and "http" not in link \
                    and col.get("desc") is not None:
                desc = ci(r, col["desc"])[0]
                urls = []
                for line in desc.splitlines():
                    low = line.lower()
                    if "referensi" in low or "sumber" in low or "reference" in low:
                        continue
                    for u in re.findall(r"https?://[^\s\"'<>]+", line):
                        if "drive.google.com" in u:
                            urls.append(u)
                if urls:
                    link = "\n".join(dict.fromkeys(urls))
            # SYARAT MASUK MASTER (semua klien): tanggal WAJIB terisi.
            # Status wajib terisi KECUALI link konten sudah ada (pembuat EP
            # kadang belum update status padahal kontennya sudah jadi).
            if not tanggal or not (status or link):
                continue
            if dflt and not (tanggal and len(tanggal) == 10
                             and tanggal[4] == "-" and tanggal >= cutoff):
                continue
            platform = spec.get("platform_map", {}).get(tipe.lower()) \
                or spec.get("platform_default") or platform_of(tipe)
            items.append({
                "klien": name, "tanggal": tanggal, "status": status, "tipe": tipe,
                "platform": platform, "judul": judul, "link": link,
                "cover": cover, "caption": caption, "tab": tab,
            })
            n += 1
    last_tab = picked[0][0] if picked else ""
    return items, n, last_tab, ok
