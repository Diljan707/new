import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Denver1769"}

def process_single_channel(channel_info, global_key_line, global_user_agent):
    i, lines = channel_info
    extinf_line = lines[i]

    # MPD ਲਿੰਕ ਲੱਭੋ
    mpd_line = None
    for f in range(i + 1, min(len(lines), i + 4)):
        sub_f = lines[f].strip()
        if sub_f.startswith("http") and ".mpd" in sub_f:
            mpd_line = sub_f

    channel_lines = []
    channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
    channel_lines.append(global_key_line) # ਸਾਰਿਆਂ ਲਈ ਸਾਂਝੀ ਕੀਅ/ਟੋਕਨ

    channel_lines.append(extinf_line)
    channel_lines.append(f"#EXTVLCOPT:http-user-agent={global_user_agent}")

    if mpd_line:
        clean_url = mpd_line.strip().split()[0]
        try:
            r = requests.get(clean_url, headers=HEADERS, allow_redirects=False, timeout=5)
            if r.status_code in [301, 302, 303, 307, 308]:
                real_url = r.headers.get('Location')
                if real_url:
                    clean_url = real_url.strip().split()[0]
        except:
            pass
        
        if clean_url.endswith("~"):
            clean_url = clean_url[:-1]
        channel_lines.append(clean_url)

    return i, channel_lines

def main():
    print("[*] Downloading target playlist...")
    try:
        res = requests.get(PLAYLIST_URL, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()
        
        # 1. ਪਹਿਲਾਂ ਪਹਿਲੇ ਚੈਨਲ ਤੋਂ ਸਾਂਝਾ Key URL ਅਤੇ User-Agent ਲੱਭੋ
        global_key_line = None
        global_user_agent = "Denver1769"
        
        for idx, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                # License Key ਲੱਭੋ
                for b in range(max(0, idx - 3), idx):
                    sub_b = lines[b].strip()
                    if "inputstream.adaptive.license_key=" in sub_b:
                        k_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()
                        if '"' in k_url:
                            k_url = k_url.replace('"', "")
                        # JSON ਡਾਊਨਲੋਡ ਕਰੋ
                        try:
                            k_res = requests.get(k_url, headers=HEADERS, timeout=8)
                            if k_res.status_code == 200:
                                global_key_line = f"#KODIPROP:inputstream.adaptive.license_key={json.dumps(k_res.json())}"
                        except:
                            global_key_line = f"#KODIPROP:inputstream.adaptive.license_key={k_url}"
                        break
                
                # User-Agent ਲੱਭੋ
                for f in range(idx + 1, min(len(lines), idx + 4)):
                    sub_f = lines[f].strip()
                    if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
                        global_user_agent = sub_f.split("=")[1].strip()
                break

        if not global_key_line:
            print("[-] Warning: Could not extract master key, using fallback.")
            global_key_line = "#KODIPROP:inputstream.adaptive.license_key="

        # 2. ਹੁਣ 20 ਚੈਨਲਾਂ ਦੀ ਸੂਚੀ ਤਿਆਰ ਕਰੋ
        channel_indices = []
        i = 0
        while i < len(lines):
            if lines[i].strip().startswith("#EXTINF"):
                channel_indices.append((i, lines))
                if len(channel_indices) >= 20:
                    break
            i += 1

        total_channels = len(channel_indices)
        print(f"[*] Found {total_channels} channels. Processing with shared key/HMAC...")

        results = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(process_single_channel, ch, global_key_line, global_user_agent): ch for ch in channel_indices}
            for future in as_completed(futures):
                idx, res_lines = future.result()
                results[idx] = res_lines

        new_lines = ["#EXTM3U"]
        for idx in sorted(results.keys()):
            new_lines.extend(results[idx])

        output_file = "safe_20_channels_ultra.m3u"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        print(f"[+] Success! Exactly {total_channels} channels saved to {output_file}")

    except Exception as e:
        print(f"[-] Critical Error: {e}")

if __name__ == "__main__":
    main()
            
