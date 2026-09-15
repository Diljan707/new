from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
import threading

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "plattv/7.1.5"}
MAX_CHANNELS = 1000  # Standard 1000 channels limit
MAX_WORKERS = 60     # Safe workers balance for speed & reliability

# Eh additional channels sab ton pehla (top te) aunge
ADDITIONAL_CHANNELS = ["Star Sports", "PTC Music", "Disney"]

counter_lock = threading.Lock()
processed_count = 0

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def process_single_channel(i, lines, session):
    line = lines[i].strip()
    extinf_line = line

    channel_lines = [extinf_line]
    user_agent = "plattv/7.1.5"
    key_url = None
    license_type = "clearkey"
    ext_http_line = None
    mpd_line = None
    raw_stream_line = ""

    # JHS te standard formats nu handle krn lyi i ton aage te piche scan kro
    for f in range(i + 1, min(len(lines), i + 8)):
        sub_f = lines[f].strip()
        if sub_f.startswith("#EXTINF") or sub_f.startswith("#EXTM3U"):
            break
        
        if "inputstream.adaptive.license_key=" in sub_f:
            key_url = sub_f.split("inputstream.adaptive.license_key=")[1].strip()
        if "inputstream.adaptive.license_type=" in sub_f:
            license_type = sub_f.split("inputstream.adaptive.license_type=")[1].strip()
        if sub_f.startswith("#EXTVLCOPT:http-user-agent="):
            user_agent = sub_f.split("=")[1].strip()
        if sub_f.startswith("#EXTHTTP:"):
            ext_http_line = sub_f
        if sub_f.startswith("http") and (".mpd" in sub_f or ".m3u8" in sub_f):
            mpd_line = sub_f
        elif sub_f.startswith("http") and not raw_stream_line:
            raw_stream_line = sub_f.split()[0]

    # Kise-kise case vich key upar v ho sakdi hai, ohi check la lo
    if not key_url:
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

    try:
        embedded_key_data = None
        if key_url and "game.playindia.fun" not in key_url and "token=" not in key_url:
            try:
                if '"' in key_url:
                    key_url = key_url.replace('"', "")
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    embedded_key_data = json.dumps(key_json)
            except Exception:
                pass

        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_type={license_type}")
        
        if embedded_key_data:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}")
        elif key_url:
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

        if ext_http_line:
            channel_lines.append(ext_http_line)

        url_added = False
        target_url = mpd_line if mpd_line else raw_stream_line

        if target_url:
            if target_url.endswith("~"):
                target_url = target_url[:-1]
            
            try:
                channel_headers = {"User-Agent": user_agent}
                r = session.get(target_url, headers=channel_headers, allow_redirects=False, timeout=3)

                if r.status_code == 403 and raw_stream_line:
                    channel_lines.append(raw_stream_line)
                    url_added = True
                else:
                    real_url = (  
                        r.headers.get("Location")  
                        if r.status_code in [301, 302, 303, 307, 308]  
                        else target_url  
                    )  
                    clean_url = real_url.strip().split()[0]  
                    if clean_url.endswith("~"):  
                        clean_url = clean_url[:-1]  
                    
                    if "__hdnea__=" in clean_url and not ext_http_line:
                        try:
                            parts = clean_url.split("__hdnea__=")
                            if len(parts) > 1:
                                hdnea_val = parts[1].split("&")[0]
                                channel_lines.append(f'#EXTHTTP:{{"cookie":"__hdnea__={hdnea_val}"}}')
                        except Exception:
                            pass
                        channel_lines.append(clean_url)
                        url_added = True
                    elif "%7Ccookie=" in clean_url and not ext_http_line:
                        parts = clean_url.split("%7Ccookie=")
                        base_url = parts[0]
                        cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                        channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}"}}')
                        channel_lines.append(base_url)
                        url_added = True
                    elif "|cookie=" in clean_url and not ext_http_line:
                        parts = clean_url.split("|cookie=")
                        base_url = parts[0]
                        cookie_val = parts[1].split("&")[0] if "&" in parts[1] else parts[1]
                        channel_lines.append(f'#EXTHTTP:{{"cookie":"{cookie_val}"}}')
                        channel_lines.append(base_url)
                        url_added = True
                    else:
                        channel_lines.append(clean_url)
                        url_added = True
            except Exception:
                channel_lines.append(target_url)
                url_added = True

        if not url_added:
            channel_lines.append("http://dummy-link-to-prevent-break")

    except Exception:
        if raw_stream_line:
            channel_lines.append(raw_stream_line)
        else:
            channel_lines.append("http://dummy-link-to-prevent-break")

    return channel_lines

def generate_safe_playlist_ordered():
    global processed_count
    processed_count = 0
    print(f"[*] Downloading playlist and processing additional channels first, followed by up to {MAX_CHANNELS} channels...")
    session = get_robust_session()
    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "plattv/7.1.5"})
        if res.status_code != 200:
            print("[-] Failed to fetch playlist.")
            return

        lines = res.text.splitlines()  

        # 1. Pehle Additional Channels labho taaki oh top te rakhe ja sakan
        additional_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                for add_ch in ADDITIONAL_CHANNELS:
                    if add_ch.lower() in line.lower():
                        if i not in additional_indices:
                            additional_indices.append(i)

        # 2. Phir baaki standard 1000 channels labho
        standard_indices = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#EXTINF"):
                standard_indices.append(i)
                if len(standard_indices) >= MAX_CHANNELS:
                    break

        # 3. Combine: Additional pehla, te standard channels us ton baad (duplication avoid karde hoye)
        target_indices = []
        for idx in additional_indices:
            if idx not in target_indices:
                target_indices.append(idx)

        for idx in standard_indices:
            if idx not in target_indices:
                target_indices.append(idx)

        if not target_indices:  
            print("[-] No channels found in playlist.")  
            return  

        print(f"[*] Total combined channels: {len(target_indices)}. Processing with multithreading...\n")  

        channel_results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_single_channel, idx, lines, session): idx
                for idx in target_indices
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    channel_results[idx] = future.result()
                except Exception:
                    fallback_lines = [lines[idx].strip(), "http://dummy-link-to-prevent-break"]
                    channel_results[idx] = fallback_lines

                with counter_lock:
                    processed_count += 1
                    print(f"[*] Progress: {processed_count}/{len(target_indices)} channels processed...", end="\r")

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])
            else:
                new_lines.append(lines[idx].strip())
                new_lines.append("http://dummy-link-to-prevent-break")

        output_file = "safe_500_channels.m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n\n[+] Success! {len(target_indices)} channels saved as '{output_file}' with proper JHS and standard formatting.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_ordered()
        
