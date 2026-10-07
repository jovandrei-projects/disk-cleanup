"""Build and apply keep/delete marks for the 2026-10-07 review pass.

Reads data/cand.json (the live /api/candidates dump) and data/td.json
(/api/treedups), applies the review policy below, and POSTs the result to
/api/decide. Run with --dry first to see the plan.

Policy, agreed with the user 2026-10-07:
  delete - regenerable caches that are not app-managed (user .cache,
           WhatsApp/Spotify web caches), installers of removed apps
           (Basemark, Sibelius, Windsurf/Typora/marktext update payloads),
           the Claude VM bundle cache, the whole Android emulator stack
           (user confirmed: mark delete), the Nintendo Switch dump trees
           (Contents + save; Album screenshots left alone, user confirmed
           delete on the dumps), Temp leftovers, and redundant Downloads /
           old-laptop copies of consolidated personal files.
  keep   - everything in Videos\\history (user's recorded video decision),
           interview footage, the video-tools venv (user: keep), every
           dup member inside live project/app-managed trees (singing-tools,
           nirvana data sets, Python installs, vscode/gradle internals,
           Calibre library, Wattpad inputs), and the important parents'
           documents where a second copy is cheap insurance.
  skip   - guard-refused rows (cannot be marked through the UI anyway) and
           system/appdata-only dup sets, which are report-only by design.
"""
import json
import sys
import urllib.request

CAND = json.load(open(r"data\cand.json"))
TD = json.load(open(r"data\td.json"))

A = "C:\\Users\\andry\\"

DELETE = {
    # regenerable / caches (unguarded rows only)
    A + ".cache",
    A + "AppData\\Local\\Packages\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm\\LocalCache\\EBWebView\\Default\\Cache",
    A + "AppData\\Local\\Packages\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm\\LocalCache\\EBWebView\\Default\\Service Worker\\CacheStorage",
    A + "AppData\\Local\\Packages\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0\\LocalCache\\Spotify\\Browser\\Cache",
    # Android emulator stack (user: delete)
    A + ".android\\avd\\Pixel_3a_API_34_extension_level_7_x86_64.avd",
    A + "AppData\\Local\\Android\\Sdk\\system-images",
    A + "AppData\\Local\\Android\\Sdk\\system-images\\android-34",
    A + "AppData\\Local\\Android\\Sdk\\system-images\\android-34\\google_apis",
    A + "AppData\\Local\\Android\\Sdk\\system-images\\android-34\\google_apis\\x86_64",
    # Nintendo dumps (user: delete) - Album/* left for the user
    A + "OneDrive\\Escritorio\\Nintendo\\Contents",
    A + "OneDrive\\Escritorio\\Nintendo\\save",
    # installers / payloads of gone or installed apps
    A + "AppData\\Local\\basemarkgpu-updater\\installer.exe",
    A + "AppData\\Local\\Downloaded Installations\\{77691980-0CB0-4AF3-A60F-8EF2997D13C1}\\Sibelius.msi",
    A + "AppData\\Local\\Temp\\windsurf-stable-user-x64\\WindsurfSetup-stable-fcf7ba39e6150055fad817f8716385b4d320d46d.exe",
    A + "AppData\\Local\\Temp\\Typora\\typora-update-x64-1.14.10.exe",
    A + "AppData\\Local\\marktext-updater\\installer.exe",
    A + "AppData\\Local\\Packages\\Claude_pzs8sxrjxfjjc\\LocalCache\\Roaming\\Claude\\vm_bundles\\claudevm.bundle\\rootfs.vhdx.zst",
    # leftover VS Installer extraction dirs in Temp (treedup members' roots)
    A + "AppData\\Local\\Temp\\yft00kke.fcu",
    A + "AppData\\Local\\Temp\\xwwxdy0s.zl5",
    A + "AppData\\Local\\Temp\\vpwxtl2x.dat",
    A + "AppData\\Local\\Temp\\pe40zif2.zdp",
    A + "AppData\\Local\\Temp\\lwzq5v21.gtb",
    A + "AppData\\Local\\Temp\\ljlxwxw4.zyt",
    A + "AppData\\Local\\Temp\\hgfanyyr.per",
    A + "AppData\\Local\\Temp\\gvn3qhmh.qnd",
    A + "AppData\\Local\\Temp\\f0czmk3u.32e",
    A + "AppData\\Local\\Temp\\ckipeai5.p12",
    A + "AppData\\Local\\Temp\\bvyj323h.54z",
    # consolidated personal duplicates - keepers listed under KEEP
    A + "OneDrive\\Documentos\\_Personal\\Backup Downloads Old Laptop 09 2021 HP\\Cracking the Coding Interview, 6th Edition 189 Programming Questions and Solutions.pdf",
    A + "OneDrive\\Documentos\\_Personal\\Backup Downloads Old Laptop 09 2021 HP\\Cracking_the_Coding_Interview_6th_Editio.pdf",
    A + "OneDrive\\Documentos\\_Personal\\Downloads_2022\\Cracking-the-Coding-Interview-6th-Edition-189-Programming-Questions-and-Solutions.pdf",
    A + "Downloads\\SCAN0031.PDF",
    A + "Downloads\\chapter_7_take.wav",
    A + "Downloads\\chapter_7_take (1).wav",
    A + "Downloads\\WhatsApp\\VID-20250914-WA0018.mp4",
    A + "Downloads\\WhatsApp\\VID-20250928-WA0028.mp4",
    A + "Downloads\\TegraRcmGUI_v2.6_Installer.msi",
    # Temp copies of project scratch images
    A + "AppData\\Local\\Temp\\pdfscan\\page1.png",
    A + "AppData\\Local\\Temp\\pdfscan\\page2.png",
}

KEEP = {
    # the recorded video decision - history recordings stay for now
    # (every Videos\history row gets keep below by prefix rule)
    "C:\\Projects\\video-tools\\.venv",
    # part of the installed marktext app - deleting it breaks the app
    A + "AppData\\Local\\Programs\\marktext\\resources\\app.asar.unpacked\\node_modules",
    # consolidated-dup keepers
    A + "OneDrive\\Documentos\\_Learning\\Courses\\CTCI\\CTCI.pdf",
    A + "OneDrive\\Documentos\\_Work\\Interviews topics\\Videos Interview\\InterviewVijay.mkv",
    A + "Videos\\history\\_has_content\\2024-05-14 09-30-49.mkv",
}

# a delete mark on a dir covers every marked path beneath it - the dirs in
# DELETE, explicitly (extension-sniffing misfires on ".cache")
DELETE_DIRS = [
    A + ".cache",
    A + ".android\\avd\\Pixel_3a_API_34_extension_level_7_x86_64.avd",
    A + "AppData\\Local\\Android\\Sdk\\system-images",
    A + "AppData\\Local\\Android\\Sdk\\system-images\\android-34",
    A + "AppData\\Local\\Android\\Sdk\\system-images\\android-34\\google_apis",
    A + "AppData\\Local\\Android\\Sdk\\system-images\\android-34\\google_apis\\x86_64",
    A + "OneDrive\\Escritorio\\Nintendo\\Contents",
    A + "OneDrive\\Escritorio\\Nintendo\\save",
    A + "AppData\\Local\\Packages\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm\\LocalCache\\EBWebView\\Default\\Cache",
    A + "AppData\\Local\\Packages\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm\\LocalCache\\EBWebView\\Default\\Service Worker\\CacheStorage",
    A + "AppData\\Local\\Packages\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0\\LocalCache\\Spotify\\Browser\\Cache",
] + [A + "AppData\\Local\\Temp\\" + n for n in (
    "yft00kke.fcu", "xwwxdy0s.zl5", "vpwxtl2x.dat", "pe40zif2.zdp",
    "lwzq5v21.gtb", "ljlxwxw4.zyt", "hgfanyyr.per", "gvn3qhmh.qnd",
    "f0czmk3u.32e", "ckipeai5.p12", "bvyj323h.54z")]


def covered(p):
    return any(p.startswith(d + "\\") for d in DELETE_DIRS)


def build():
    pairs = {}

    def mark(path, choice):
        if path in pairs and pairs[path] != choice:
            raise SystemExit("conflict on %s: %s vs %s"
                             % (path, pairs[path], choice))
        pairs[path] = choice

    for c in CAND["items"]:
        p, guard = c["path"], c.get("guard")
        if guard:
            continue  # not markable in the UI; report-only
        if p in DELETE or covered(p):
            mark(p, "delete")
        elif p in KEEP or "\\Videos\\history\\" in p:
            mark(p, "keep")
        else:
            mark(p, "keep")  # reviewed; nothing else here should go

    # duplicate sets: mark every member in personal-containing territory.
    # system/appdata-only sets stay report-only.
    for s in CAND["dup_sets"]["sets"]:
        ts = {t(m["path"]) for m in s["members"]}
        if "personal" not in ts:
            continue
        for m in s["members"]:
            p = m["path"]
            if m.get("protected"):
                continue
            if p in DELETE or covered(p):
                mark(p, "delete")
            else:
                mark(p, "keep")

    # treedup members: Temp leftovers resolved above via their Temp roots;
    # important-doc pair keeps both copies.
    for g in TD["groups"]:
        for m in g["members"]:
            p = m["path"]
            if m.get("protected"):
                continue
            if p in DELETE or covered(p):
                mark(p, "delete")
            elif "Papas_importante" in p:
                mark(p, "keep")

    # The DELETE set's own paths must be marked too - most dir roots are not
    # candidate rows, and without these the smaller files under them
    # (sub-500MB nca parts, the rest of each Temp dir) would stay behind.
    for p in DELETE:
        mark(p, "delete")

    # stale test remnant: mangled path, matches nothing on disk
    pairs["C:$Recycle.Bin"] = "none"
    return pairs


def t(p):
    p = p.lower()
    if (p.startswith("c:\\windows\\") or p.startswith("c:\\program files\\")
            or p.startswith("c:\\program files (x86)\\")
            or p.startswith("c:\\programdata\\")
            or p.startswith("c:\\$recycle.bin\\")):
        return "system"
    if "\\appdata\\" in p:
        return "appdata"
    return "personal"


if __name__ == "__main__":
    pairs = build()
    dele = sorted(p for p, c in pairs.items() if c == "delete")
    keep = sum(1 for c in pairs.values() if c == "keep")
    print("%d delete marks, %d keep marks" % (len(dele), keep))
    for p in dele[:80]:
        print("  DEL", p)
    if len(dele) > 80:
        print("  ... +%d more" % (len(dele) - 80))
    if "--apply" in sys.argv:
        body = json.dumps(
            {"decisions": [[p, c] for p, c in pairs.items()]}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8770/api/decide", data=body,
            headers={"Content-Type": "application/json"})
        print(urllib.request.urlopen(req).read().decode())
