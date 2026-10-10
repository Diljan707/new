from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import base64
import os
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
from urllib.parse import urljoin
import threading
from bs4 import BeautifulSoup

PLAYLIST_URL = os.environ.get("PLAYLIST_URL")
IP_MANAGER_URL = "https://game.playindia.fun/Jtv/IP.php?id=RiYlIZ"

MAX_CHANNELS = 2000
MAX_WORKERS = 40

def clear_old_ips(session):
    print("[*] Checking and clearing old IPs from IP Manager...")
    headers = {
        "User-Agent": "Denver1769",
        "Referer": "https://game.playindia.fun/"
    }
    try:
        res = session.get(IP_MANAGER_URL, headers=headers, timeout=10)
        if res.status_code != 200:
            return
        soup = BeautifulSoup(res.text, 'html.parser')
        forms = soup.find_all('form')
        ip_list = []
        for form in forms:
            action_input = form.find('input', {'name': 'action', 'value': 'delete_ip'})
            ip_input = form.find('input', {'name': 'ip'})
            if action_input and ip_input:
                ip_list.append(ip_input.get('value'))
        if not ip_list:
            return
        def delete_single(ip_val):
            data = {'action': 'delete_ip', 'ip': ip_val}
            try:
                session.post(IP_MANAGER_URL, data=data, headers=headers, timeout=5)
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=15) as executor:
            executor.map(delete_single, ip_list)
        print("[+] All old IPs cleared successfully!\n")
    except Exception as e:
        print(f"[-] Error clearing IPs: {e}")

def get_robust_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def b64_to_hex(b64_str):
    padding = 4 - (len(b64_str) % 4)
    if padding < 4:
        b64_str += '=' * padding
    try:
        decoded = base64.urlsafe_b64decode(b64_str)
        return decoded.hex()
    except Exception:
        return b64_str

def resolve_stream_url(url, session, user_agent):
    if not url:
        return url
    
    headers = {
        "User-Agent": user_agent,
        "Origin": "https://www.hotstar.com",
        "Referer": "https://www.hotstar.com/",
        "Accept-Encoding": "identity"
    }

    try:
        r = session.get(url, headers=headers, allow_redirects=True, timeout=7)
        if r.status_code == 200:
            res_text = r.text
            lines = res_text.splitlines()
            nested_links = []
            for line in lines:
                line = line.strip()
                if "http" in line and ("m3u8" in line or "mpd" in line) and "playindia.fun" not in line:
                    idx = line.find("http")
                    clean_link = line[idx:].split()[0].strip('"' + "'")
                    nested_links.append(clean_link)
            
            if nested_links:
                chosen_link = nested_links[-1]
                if not chosen_link.startswith("http"):
                    chosen_link = urljoin(r.url, chosen_link)
                return chosen_link
                
        if r.url and "playindia.fun" not in r.url:
            resolved_final = r.url
            if not resolved_final.startswith("http"):
                resolved_final = urljoin(url, resolved_final)
            return resolved_final
            
    except Exception:
        pass
        
    return url

def process_single_channel(i, lines, session):
    line = lines[i].strip()
    extinf_line = line

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        if lines[f].strip().startswith("http"):
            raw_stream_line = lines[f].strip().split()[0]
            if raw_stream_line.endswith("~"):
                raw_stream_line = raw_stream_line[:-1]
            break

    user_agent = "Hotstar;in.startv.hotstar/25.02.24.8.11169@Premium Plugx(Android/15)"
    
    channel_lines = [extinf_line]

    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = lines[b].strip()
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = sub_b.split("inputstream.adaptive.license_key=")[1].strip()

        formatted_license_key = None
        if key_url:
            formatted_license_key = key_url
        
        final_stream_url = raw_stream_line
        if raw_stream_line:
            resolved = resolve_stream_url(raw_stream_line, session, user_agent)
            if resolved:
                final_stream_url = resolved

        is_mpd_link = ".mpd" in final_stream_url.lower()

        channel_lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.manifest_type={'mpd' if is_mpd_link else 'hls'}")
        channel_lines.append("#KODIPROP:inputstream.adaptive.max_bandwidth=0")
        channel_lines.append("#KODIPROP:inputstream.adaptive.stream_selection_type=buffered")
        channel_lines.append("#KODIPROP:inputstream.adaptive.buffer_segment_size=1")
        channel_lines.append("#KODIPROP:inputstream.adaptive.live_delay=0")

        if formatted_license_key:
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")

        cookie_str = ""
        for check_line in [raw_stream_line] + lines[max(0, i-2):min(len(lines), i+3)]:
            if "hdntl=" in check_line:
                try:
                    parts = check_line.split("hdntl=")
                    for p in parts[1:]:
                        candidate = p.split()[0].strip('"\'')
                        if "exp=" in candidate:
                            cookie_str = "hdntl=" + candidate.split("&")[0]
                            break
                except Exception:
                    pass
            if cookie_str:
                break
        
        if not cookie_str:
            cookie_str = "hdntl=exp=1791683205~acl=%2f*~id=8a0f084a08c7b8da69eaecf4ebdf7027~data=hdntl~hmac=dc8db40dbcee02223ba7cd875c04c40cf31f9991b6d262131edc6a94af00f063"

        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
        channel_lines.append("#EXTVLCOPT:http-referrer=https://www.hotstar.com/")
        channel_lines.append("#EXTVLCOPT:http-extra-headers=Origin: https://www.hotstar.com")
        channel_lines.append(f"#EXTVLCOPT:http-cookie={cookie_str}")
        
        ext_http_json = f'{{"User-Agent":"{user_agent}","Origin":"https://www.hotstar.com","Referer":"https://www.hotstar.com/","Cookie":"{cookie_str}","Accept-Encoding":"identity","Connection":"keep-alive"}}'
        channel_lines.append(f"#EXTHTTP:{ext_http_json}")
        
        if "?" in final_stream_url:
            base_url = final_stream_url.split("?")[0]
        else:
            base_url = final_stream_url
            
        stream_with_params = f"{base_url}?|cookie={cookie_str}&referer=https://www.hotstar.com/&origin=https://www.hotstar.com&user-agent={user_agent}"
        channel_lines.append(stream_with_params)

    except Exception:
        channel_lines.append(raw_stream_line if raw_stream_line else "http://dummy-link-to-prevent-break")

    return channel_lines

def generate_safe_playlist_1000():
    if not PLAYLIST_URL:
        return

    session = get_robust_session()
    clear_old_ips(session)

    try:
        res = session.get(PLAYLIST_URL, headers={"User-Agent": "Denver1769"})
        if res.status_code != 200:
            return

        lines = res.text.splitlines()  
        all_channels = []
        for i, line in enumerate(lines):  
            if line.strip().startswith("#EXTINF"):  
                all_channels.append((i, line))

        if not all_channels:  
            return  

        target_indices = [item[0] for item in all_channels[:MAX_CHANNELS]]
        print(f"[*] Processing {len(target_indices)} channels cleanly...")  

        channel_results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_single_channel, idx, lines, session): idx
                for idx in target_indices
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    res_lines = future.result()
                    if res_lines:
                        channel_results[idx] = res_lines
                except Exception:
                    pass

        new_lines = ["#EXTM3U"]
        for idx in target_indices:
            if idx in channel_results:
                new_lines.extend(channel_results[idx])

        output_file = ".m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n[+] Success! Final playlist saved as '{output_file}'.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
