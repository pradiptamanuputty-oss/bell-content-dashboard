#!/usr/bin/env python3
"""Driver: pull semua EP client (tiap klien punya script spec sendiri di
ep_clients/) ke (1) tab 'Mirror' di 'Bell Master EP', (2) tab 'Daftar Klien',
dan (3) data.json untuk dashboard GitHub Pages. Tanpa LLM.

Skema item ternormalisasi (sama untuk semua klien):
  klien, tanggal (ISO atau "" = belum terjadwal), status, tipe, judul,
  platform, link, cover, caption, tab

Mirror: Klien | Tanggal Upload | Status | Tipe | Judul | Platform | Link |
        Cover | Caption | Tab

Run dengan venv python Hermes:
  VP=$(ls -d ~/.hermes/installs/*/environments/*/venv/bin/python | head -1)
  "$VP" ~/.hermes/skills/productivity/bell-content-bank/scripts/ep_mirror_sync.py [--json-out PATH]
"""
import argparse, importlib, json, os, sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "ep_sheets.json")
sys.path.insert(0, HERE)

import ep_common as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", help="tulis data.json dashboard ke path ini")
    args = ap.parse_args()

    cfg = json.load(open(CFG_PATH))
    svc, drive = C.services()
    lo, hi = C.month_window()
    today = date.today()
    cutoff = (today - timedelta(days=45)).isoformat()
    floor_d = today - timedelta(days=180)
    old_floor = (floor_d.year, floor_d.month)

    items = []
    stats = []
    client_info = {}  # name -> {rows, last_tab, link}
    for c in cfg["clients"]:
        name, sid = c["name"], c["sheet"]
        status = c.get("status", "aktif")
        link = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
        if status == "past":
            # bukan klien lagi: tidak di-sync, cukup catat tab terakhirnya
            last_tab = ""
            try:
                tabs = C.get_tabs(svc, sid)
                parsed = [C.parse_tab_month(t) for t in tabs]
                parsed = [p for p in parsed if p]
                if parsed:
                    parsed.sort(key=lambda x: (-x[0], -x[1]))
                    last_tab = parsed[0][2]
            except Exception as e:
                C.warn(f"{name}: metadata gagal ({type(e).__name__}: {e})")
            client_info[name] = {"rows": 0, "last_tab": last_tab, "link": link}
            continue
        mod = c.get("module")
        if not mod:
            C.warn(f"{name}: config tanpa 'module' — dilewati")
            stats.append((name, -1))
            client_info[name] = {"rows": -1, "last_tab": "", "link": link}
            continue
        try:
            spec = importlib.import_module(f"ep_clients.{mod}").SPEC
            c_items, n, last_tab, ok = C.pull_client(
                svc, sid, name, spec, lo, hi, old_floor, cutoff)
        except Exception as e:
            C.warn(f"{name}: pull gagal ({type(e).__name__}: {str(e)[:100]})")
            stats.append((name, -1))
            client_info[name] = {"rows": -1, "last_tab": "", "link": link}
            continue
        if ok:
            items.extend(c_items)
            stats.append((name, n))
        else:
            stats.append((name, -1))
        client_info[name] = {"rows": n if ok else -1, "last_tab": last_tab, "link": link}

    # --- Mirror sheet ---
    mirror_id = cfg.get("mirror_sheet_id")
    if not mirror_id:
        f = drive.files().create(body={
            "name": cfg["mirror_name"],
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [cfg["folder_id"]],
        }, fields="id").execute()
        mirror_id = f["id"]
        cfg["mirror_sheet_id"] = mirror_id
        json.dump(cfg, open(CFG_PATH, "w"), indent=2, ensure_ascii=False)
        meta = svc.spreadsheets().get(spreadsheetId=mirror_id).execute()
        sid0 = meta["sheets"][0]["properties"]["sheetId"]
        svc.spreadsheets().batchUpdate(spreadsheetId=mirror_id, body={"requests": [{
            "updateSheetProperties": {"properties": {"sheetId": sid0, "title": "Mirror"},
                                      "fields": "title"}}]}).execute()

    header = ["Klien", "Tanggal Upload", "Status", "Tipe", "Judul", "Platform",
              "Link", "Cover", "Caption", "Tab"]
    rows = [[i["klien"], i["tanggal"], i["status"], i["tipe"], i["judul"],
             i["platform"], i["link"], i["cover"], i["caption"], i["tab"]]
            for i in items]
    svc.spreadsheets().values().clear(spreadsheetId=mirror_id, range="Mirror!A:Z").execute()
    if rows:
        svc.spreadsheets().values().update(
            spreadsheetId=mirror_id, range="Mirror!A1",
            valueInputOption="RAW",  # RAW: "2026-11-10" tetap teks ISO, tidak di-parse jadi tanggal (tampilan locale berubah-ubah)
            body={"values": [header] + rows}).execute()
    stamp = f"Sinkron terakhir: {date.today().isoformat()}"
    svc.spreadsheets().values().update(
        spreadsheetId=mirror_id, range="Mirror!L1",
        valueInputOption="RAW", body={"values": [[stamp]]}).execute()

    # --- tab Daftar Klien ---
    meta = svc.spreadsheets().get(spreadsheetId=mirror_id, includeGridData=False).execute()
    titles = [p["properties"]["title"] for p in meta["sheets"]]
    if "Daftar Klien" not in titles:
        svc.spreadsheets().batchUpdate(spreadsheetId=mirror_id, body={"requests": [
            {"addSheet": {"properties": {"title": "Daftar Klien"}}}]}).execute()
    cl_header = ["Klien", "Status Project", "Link EP", "Baris Ter-sync", "Tab Terakhir"]
    cl_rows = []
    for c in cfg["clients"]:
        info = client_info.get(c["name"], {})
        rn = info.get("rows", 0)
        st_label = "Past Project" if c.get("status") == "past" else "Aktif"
        cl_rows.append([c["name"], st_label, info.get("link", ""),
                        str(rn) if rn >= 0 else "ERROR",
                        info.get("last_tab", "") or "—"])
    svc.spreadsheets().values().clear(spreadsheetId=mirror_id, range="'Daftar Klien'!A:Z").execute()
    svc.spreadsheets().values().update(
        spreadsheetId=mirror_id, range="'Daftar Klien'!A1",
        valueInputOption="RAW",
        body={"values": [cl_header] + cl_rows}).execute()

    # --- data.json dashboard ---
    if args.json_out:
        out = os.path.expanduser(args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # klien yang gagal dibaca: pertahankan baris lama agar dashboard tidak kehilangan data
        failed = {n for n, s in stats if s == -1}
        if failed:
            try:
                with open(out, encoding="utf-8") as fh:
                    old_items = json.load(fh).get("items", [])
            except Exception:
                old_items = []
            preserved = [i for i in old_items if i["klien"] in failed]
            if preserved:
                items.extend(preserved)
                C.warn(f"{len(preserved)} baris lama dipertahankan untuk klien gagal: {sorted(failed)}")
        tz = timezone(timedelta(hours=7))  # WIB
        payload = {
            "generated_at": datetime.now(tz).isoformat(timespec="seconds"),
            "clients": {c["name"]: f"https://docs.google.com/spreadsheets/d/{c['sheet']}/edit"
                        for c in cfg["clients"]},
            "items": items,
        }
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)

    print("=== STAT PER KLIEN ===")
    for name, n in stats:
        print(f"{n if n >= 0 else 'ERROR':>5}  {name}")
    print(f"TOTAL {len(items)} baris")
    print("MIRROR ID:", mirror_id)
    if args.json_out:
        print("JSON OUT:", os.path.expanduser(args.json_out))
    if C.WARN:
        print("=== WARNING ===")
        for w in C.WARN:
            print(" -", w)


if __name__ == "__main__":
    main()
