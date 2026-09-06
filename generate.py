import requests
import json

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Denver1769"}

def main():
    print("[*] Downloading target playlist...")
    try:
        res = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=30)
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()
        new_lines = ["#EXTM3U"]

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            if line.startswith("#EXTINF"):
                extinf_line = line
                
                key_url = None
                for b in range(max(0, i - 3), i):
                    sub_b = lines[b].strip()
                    if "inputstream.adaptive.license_key=" in sub_b:
                        key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

                user_agent = "Denver1769"
                mpd_line = None
                for f in range(i + 1, min(len(lines), i + 4)):
                    sub_f = lines[f].strip()
                    if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
                        user_agent = sub_f.split("=")[1].strip()
                    if sub_f.startswith("http") and ".mpd" in sub_f:
                        mpd_line = sub_f

                embedded_key_data = None
                if key_url:
                    try:
                        clean_key_url = key_url.replace('"', "")
                        key_res = requests.get(clean_key_url, headers=HEADERS, timeout=8)
                        if key_res.status_code == 200:
                            key_json = key_res.json()
                            embedded_key_data = json.dumps(key_json)
                    except Exception:
                        pass

                new_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
                
                if embedded_key_data:
                    new_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}")
                elif key_url:
                    new_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

                new_lines.append(extinf_line)
                new_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

                if mpd_line:
                    try:
                        r = requests.get(mpd_line, headers=HEADERS, allow_redirects=False, timeout=6)
                        real_url = r.headers.get('Location') if r.status_code in [301, 302, 303, 307, 308] else mpd_line
                        clean_url = real_url.strip().split()[0]
                        if clean_url.endswith("~"):
                            clean_url = clean_url[:-1]
                        new_lines.append(clean_url)
                    except Exception:
                        clean_url = mpd_line.strip().split()[0]
                        if clean_url.endswith("~"):
                            clean_url = clean_url[:-1]
                        new_lines.append(clean_url)

            i += 1

        with open("playlist.m3u", "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print("[+] Success! Playlist generated successfully.")

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    main()
                        
