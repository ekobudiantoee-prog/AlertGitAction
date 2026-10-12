#!/usr/bin/env python3
"""Ambil pengumuman keterbukaan informasi IDX, filter yang positif, kirim ke Telegram.

Env wajib : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Opsional  : SEND_BACKLOG=1  (kirim juga pengumuman yang sudah ada saat run pertama)
Tes kirim : python idx_telegram.py --test
"""
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from curl_cffi import requests as cffi  # meniru browser, membantu lolos Cloudflare
except ImportError:  # pragma: no cover
    cffi = None

API = "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
STATE_FILE = Path("sent_ids.json")
WIB = timezone(timedelta(hours=7))
MAX_STATE = 3000

# Kata kunci berita positif (dicocokkan ke judul + perihal, huruf kecil).
POSITIVE = [
    "akuisisi", "mengakuisisi", "pengambilalihan", "pengambilan alih",
    "perolehan kontrak", "memperoleh kontrak", "kontrak baru", "memenangkan",
    "kerja sama", "kerjasama", "kemitraan", "joint venture", "usaha patungan",
    "dividen", "pembelian kembali saham", "buyback", "buy back",
    "ekspansi", "investasi baru", "penambahan penyertaan", "penyertaan modal",
    "peningkatan laba", "laba meningkat", "kenaikan laba", "pertumbuhan laba",
    "peningkatan pendapatan", "penjualan meningkat", "pencatatan", "peringkat naik",
]
# Kata yang membatalkan (berita negatif / netral-buruk).
NEGATIVE = [
    "pembatalan", "dibatalkan", "penundaan", "ditunda", "gagal", "wanprestasi",
    "default", "pkpu", "kepailitan", "pailit", "suspensi", "penghentian sementara",
    "delisting", "kerugian", "rugi", "penurunan", "sanksi", "denda", "gugatan",
    "perkara", "pemutusan", "pengunduran diri", "somasi", "peringatan",
]


def fetch_today():
    now = datetime.now(WIB)
    d = now.strftime("%Y%m%d")
    params = {
        "kodeEmiten": "", "emitenType": "*", "indexFrom": 0, "pageSize": 100,
        "dateFrom": d, "dateTo": d, "lang": "id", "keyword": "",
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    }
    if cffi is not None:
        r = cffi.get(API, params=params, headers=headers, impersonate="chrome", timeout=30)
    else:
        r = requests.get(API, params=params, headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"IDX balas HTTP {r.status_code} (kemungkinan diblokir Cloudflare)")
    return r.json().get("Replies", [])


def parse(item):
    p = item.get("pengumuman", item)
    pid = str(p.get("NoPengumuman") or p.get("Id2") or p.get("Id") or "")
    judul = (p.get("JudulPengumuman") or "").strip()
    perihal = (p.get("PerihalPengumuman") or "").strip()
    kode = (p.get("Kode_Emiten") or "").strip()
    tgl = (p.get("TglPengumuman") or p.get("CreatedDate") or "")[:16].replace("T", " ")
    links = []
    for a in item.get("attachments", []) or []:
        url = a.get("FullSavePath")
        if url:
            links.append((a.get("OriginalFilename") or "Lampiran", url))
    return {"id": pid, "judul": judul, "perihal": perihal, "kode": kode, "tgl": tgl, "links": links}


def is_positive(a):
    text = f"{a['judul']} {a['perihal']}".lower()
    if any(w in text for w in NEGATIVE):
        return False
    return any(w in text for w in POSITIVE)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save_state(ids):
    STATE_FILE.write_text(json.dumps(ids[-MAX_STATE:]))


def send(text):
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=30,
    )
    r.raise_for_status()


def format_msg(a):
    lines = [f"🟢 <b>{html.escape(a['kode'] or '-')}</b> | {html.escape(a['tgl'])}", html.escape(a["judul"])]
    if a["perihal"] and a["perihal"] != a["judul"]:
        lines.append(f"<i>{html.escape(a['perihal'])}</i>")
    for name, url in a["links"][:3]:
        lines.append(f'📎 <a href="{html.escape(url)}">{html.escape(name)}</a>')
    lines.append('<a href="https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi">Sumber: IDX</a>')
    return "\n".join(lines)


def main():
    if "--test" in sys.argv:
        send("✅ Tes bot IDX berhasil.")
        return

    items = [parse(i) for i in fetch_today()]
    items = [i for i in items if i["id"]]
    state = load_state()
    first_run = state is None
    seen = set(state or [])

    new = [i for i in items if i["id"] not in seen]
    positives = [i for i in new if is_positive(i)]
    print(f"Total hari ini: {len(items)}, baru: {len(new)}, positif: {len(positives)}")

    if first_run and os.environ.get("SEND_BACKLOG") != "1":
        print("Run pertama: menandai semua pengumuman saat ini sebagai sudah dilihat.")
        positives = []

    for a in reversed(positives):  # kirim dari yang terlama
        send(format_msg(a))

    save_state(list(state or []) + [i["id"] for i in new])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
