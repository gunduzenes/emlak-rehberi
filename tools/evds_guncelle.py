#!/usr/bin/env python3
"""TCMB EVDS'den piyasa serilerini çekip content.json'u günceller.

Kullanım:
  EVDS_API_KEY=... python3 evds_guncelle.py content.json            # güncelle
  EVDS_API_KEY=... python3 evds_guncelle.py content.json --kesfet   # yalnız seri kodlarını listele

Seri kodları ezbere yazılmaz; EVDS'deki veri grubu ve seri adlarından bulunur,
böylece TCMB kod değiştirse de betik çalışmaya devam eder. Bulunamayan seri
atlanır, mevcut içerik korunur.
"""
import json, os, ssl, sys, urllib.request, urllib.parse
from datetime import date

BASE = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
KEY = os.environ.get("EVDS_API_KEY", "").strip()
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

# Her seri: veri grubu adında geçmesi gerekenler, geçmemesi gerekenler,
# seri adında geçmesi gerekenler (ilk eşleşen alınır).
HEDEFLER = [
    dict(id="kfe-ist", scope="istanbul", title="İstanbul konut fiyat endeksi", unit="endeks",
         grup=["konut fiyat endeksi"], grup_degil=["yeni konut", "birim", "hedonik", "sorgu"],
         seri=[["istanbul"]], kaynak="TCMB", yedek_kod="TP.KFE.TR10"),
    dict(id="kfe-tr", scope="turkiye", title="Türkiye konut fiyat endeksi", unit="endeks",
         kod="TP.KFE.TR", kaynak="TCMB"),
    dict(id="ykke-ist", scope="istanbul", title="İstanbul yeni kiracı kira endeksi", unit="endeks",
         grup=["kira"], grup_degil=["hizmet", "tüfe", "tufe"],
         seri=[["istanbul"]], kaynak="TCMB", yedek_kod="TP.YKKE.TR10"),
    dict(id="ykke-tr", scope="turkiye", title="Türkiye yeni kiracı kira endeksi", unit="endeks",
         kod="TP.YKKE.TR", kaynak="TCMB"),
    dict(id="satis-ist", scope="istanbul", title="İstanbul konut satışları", unit="adet",
         grup=["konut", "satış"], grup_degil=["ikinci", "ilk el", "ipotek", "yabancı", "diğer"],
         seri=[["istanbul", "konut"]], kaynak="TÜİK (EVDS)", yedek_kod="TP.AKONUTSAT1.KTR100"),
    dict(id="satis-tr", scope="turkiye", title="Türkiye konut satışları", unit="adet",
         grup=["konut", "satış"], grup_degil=["ikinci", "ilk el", "ipotek", "yabancı", "diğer"],
         seri=[["türkiye", "konut"]], kaynak="TÜİK (EVDS)", yedek_kod="TP.AKONUTSAT1.KTRTOPLAM"),
]


def kucuk(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower()


def istek(yol, params):
    if not KEY:
        sys.exit("EVDS_API_KEY tanımlı değil")
    url = BASE + yol + "&".join(f"{k}={v}" for k, v in params.items())
    ctx = ssl.create_default_context()
    ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT (EVDS sunucusu için gerekli)
    req = urllib.request.Request(url, headers={"key": KEY, "User-Agent": "emlak-rehberi"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def gruplar():
    return istek("datagroups/", {"mode": 0, "code": "", "type": "json"})


def seriler(grup_kodu):
    return istek("serieList/", {"type": "json", "code": grup_kodu})


def bul(hedef, tum_gruplar):
    if hedef.get("kod"):
        return hedef["kod"], "(sabit kod)", hedef["kod"]
    for g in tum_gruplar:
        ad = kucuk(g.get("DATAGROUP_NAME"))
        if all(k in ad for k in hedef["grup"]) and not any(k in ad for k in hedef["grup_degil"]):
            try:
                ss = seriler(g["DATAGROUP_CODE"])
            except Exception as e:
                print("  seri listesi alınamadı", g["DATAGROUP_CODE"], e)
                continue
            for kosul in hedef["seri"]:
                for s in ss:
                    sad = kucuk(s.get("SERIE_NAME"))
                    if all(k in sad for k in kosul):
                        return s["SERIE_CODE"], g["DATAGROUP_NAME"], s.get("SERIE_NAME")
    if hedef.get("yedek_kod"):
        return hedef["yedek_kod"], "(yedek kod)", hedef["yedek_kod"]
    return None


def veri(kod, formul=""):
    bas = date(date.today().year - 8, 1, 1).strftime("%d-%m-%Y")
    son = date.today().strftime("%d-%m-%Y")
    d = istek("", {"series": kod, "startDate": bas, "endDate": son, "type": "json",
                   "formulas": formul, "frequency": "5", "aggregationTypes": ""})
    alan = kod.replace(".", "_") + (f"-{formul}" if formul else "")
    noktalar = []
    for it in d.get("items", []):
        tarih = it.get("Tarih") or it.get("TARIH")
        deger = it.get(alan)
        if deger is None:
            deger = next((v for k, v in it.items() if k.startswith(kod.replace(".", "_"))), None)
        if not tarih or deger in (None, "", "null"):
            continue
        try:
            y, a = str(tarih).split("-")[:2]
            noktalar.append({"period": f"{int(y):04d}-{int(a):02d}", "value": round(float(deger), 2)})
        except ValueError:
            continue
    return noktalar


def yuzde(x, isaret=False):
    s = f"{abs(x):.1f}".replace(".", ",")
    return ("−" if x < 0 else "") + "%" + s if isaret else "%" + f"{x:.1f}".replace(".", ",")


def sayi(x, ondalik=0):
    s = f"{x:,.{ondalik}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def donem(p):
    y, a = p.split("-")
    return f"{AYLAR[int(a) - 1]} {y}"


def gostergeleri_guncelle(ind, seriler_):
    by = {s["id"]: s["points"] for s in seriler_}
    def degisim(p, geri):
        return (p[-1]["value"] / p[-1 - geri]["value"] - 1) * 100 if len(p) > geri and p[-1 - geri]["value"] else None
    for i in ind:
        p = by.get(i["id"])
        if not p or len(p) < 13:
            continue
        yil, ay = degisim(p, 12), degisim(p, 1)
        if i["id"] in ("kfe-ist", "kfe-tr"):
            i["value"] = yuzde(yil, True)
            i["detail"] = f"Yıllık artış · endeks {sayi(p[-1]['value'], 1)} · aylık {yuzde(ay, True)}"
        elif i["id"] == "ykke-ist":
            i["value"] = yuzde(ay, True)
            i["detail"] = f"Aylık artış (İstanbul) · yıllık {yuzde(yil, True)}"
        elif i["id"] == "ykke-tr":
            i["value"] = yuzde(yil, True)
            i["detail"] = f"Yıllık artış · aylık {yuzde(ay, True)}"
        else:
            continue
        i["period"] = donem(p[-1]["period"])
        i["sourceUrl"] = "https://evds3.tcmb.gov.tr"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    yol, kesfet = sys.argv[1], "--kesfet" in sys.argv
    tum = gruplar()
    print(f"EVDS: {len(tum)} veri grubu")
    if kesfet:
        for g in tum:
            ad = kucuk(g.get("DATAGROUP_NAME"))
            if any(k in ad for k in ["konut", "kira", "tüketici fiyat", "inşaat"]):
                print(f"\n[{g['DATAGROUP_CODE']}] {g.get('DATAGROUP_NAME')}")
                try:
                    for s in seriler(g["DATAGROUP_CODE"])[:40]:
                        print(f"   {s['SERIE_CODE']}  {s.get('SERIE_NAME')}")
                except Exception as e:
                    print("   hata:", e)
        return

    icerik = json.load(open(yol, encoding="utf-8"))
    market = icerik.setdefault("market", {})
    eski = {s["id"]: s for s in market.get("series", [])}
    yeni = []
    for h in HEDEFLER:
        try:
            b = bul(h, tum)
            if not b:
                print(f"- {h['id']}: seri bulunamadı, atlandı")
                if h["id"] in eski: yeni.append(eski[h["id"]])
                continue
            kod, grup, sad = b
            p = veri(kod, h.get("formul", ""))
            print(f"+ {h['id']}: {kod} ({grup} / {sad}) · {len(p)} nokta · son {p[-1]['period'] if p else '-'}")
            if p and p[-1]["period"] < f"{date.today().year - 1:04d}-{date.today().month:02d}":
                print(f"  {h['id']}: seri güncel değil (son {p[-1]['period']}), atlandı")
                p = []
            if len(p) < 3:
                if h["id"] in eski: yeni.append(eski[h["id"]])
                continue
            yeni.append({"id": h["id"], "scope": h["scope"], "title": h["title"], "unit": h["unit"],
                         "source": h["kaynak"], "sourceUrl": "https://evds3.tcmb.gov.tr", "code": kod,
                         "points": p})
        except Exception as e:
            print(f"! {h['id']}: {e}")
            if h["id"] in eski: yeni.append(eski[h["id"]])

    if [ (s["id"], s["points"]) for s in yeni ] == [ (s["id"], s["points"]) for s in market.get("series", []) ]:
        print("Değişiklik yok.")
        return
    market["series"] = yeni
    gostergeleri_guncelle(market.get("indicators", []), yeni)
    son = max((s["points"][-1]["period"] for s in yeni if s["points"]), default=None)
    if son:
        market["asOf"] = donem(son)
    icerik["version"] = int(icerik.get("version", 1)) + 1
    icerik["updatedAt"] = date.today().strftime("%d.%m.%Y")
    json.dump(icerik, open(yol, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"content.json güncellendi · sürüm {icerik['version']}")


if __name__ == "__main__":
    main()
