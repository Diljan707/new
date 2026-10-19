from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import base64
import os
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PLAYLIST_URL = os.environ.get("PLAYLIST_URL")
IP_MANAGER_URL = "https://game.playindia.fun/Jtv/IP.php?id=RiYlIZ"
LCN_LIST_URL = "https://raw.githubusercontent.com/Diljan707/Automated-/refs/heads/main/dishtv_lcn_list.txt"

MAX_CHANNELS = 2000
MAX_WORKERS = 40

def fetch_lcn_dict(session):
    print("[*] Fetching DishTV LCN list...")
    lcn_dict = {}
    try:
        res = session.get(LCN_LIST_URL, timeout=10)
        if res.status_code == 200:
            for line in res.text.splitlines():
                if ":" in line:
                    parts = line.split(":", 1)
                    chno = parts[0].strip()
                    chname = parts[1].strip().lower()
                    # Spaces clean karo
                    chname = " ".join(chname.split())
                    
                    # Pehli match hone wali value nu lock rakho (overwrite mat hone do)
                    if chname and chname not in lcn_dict:
                        lcn_dict[chname] = chno
            print(f"[+] Loaded {len(lcn_dict)} LCN mappings successfully!\n")
    except Exception as e:
        print(f"[-] Error fetching LCN list: {e}")
    return lcn_dict

def clean_val(val):
    if not val:
        return ""
    val = val.strip()
    while val and val[-1] in ('"', "'", '}', ']', '}', '~', ','):
        val = val[:-1].strip()
    return val

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
    b64_str = clean_val(b64_str)
    padding = 4 - (len(b64_str) % 4)
    if padding < 4:
        b64_str += '=' * padding
    try:
        decoded = base64.urlsafe_b64decode(b64_str)
        return decoded.hex()
    except Exception:
        return b64_str

def resolve_stream_url(url, session, user_agent, is_hotstar, is_sliv):
    url = clean_val(url)
    if not url:
        return url
    
    headers = {"User-Agent": user_agent}
    if is_hotstar:
        headers.update({
            "User-Agent": "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)",
            "Origin": "https://www.hotstar.com",
            "Referer": "https://www.hotstar.com/",
            "Accept-Encoding": "identity"
        })
    elif is_sliv:
        headers.update({"Origin": "https://www.sonyliv.com", "Referer": "https://www.sonyliv.com/"})

    try:
        r = session.get(url, headers=headers, allow_redirects=True, timeout=7)
        if r.status_code == 200:
            res_text = r.text
            lines = res_text.splitlines()
            nested_links = []
            for line in lines:
                line = clean_val(line)
                if "http" in line and ("m3u8" in line or "mpd" in line) and "playindia.fun" not in line:
                    idx = line.find("http")
                    clean_link = clean_val(line[idx:].split()[0])
                    nested_links.append(clean_link)
            
            if nested_links:
                chosen_link = clean_val(nested_links[-1])
                if not chosen_link.startswith("http"):
                    chosen_link = urljoin(r.url, chosen_link)
                return chosen_link
                
        if r.url and "playindia.fun" not in r.url:
            resolved_final = clean_val(r.url)
            if not resolved_final.startswith("http"):
                resolved_final = urljoin(url, resolved_final)
            return resolved_final
            
    except Exception:
        pass
        
    return url

def process_single_channel(i, lines, session, lcn_dict):
    line = lines[i].strip()
    extinf_line = line

    # --- Remove group-title (Category) from EXTINF line ---
    if 'group-title="' in extinf_line:
        try:
            parts = extinf_line.split('group-title="')
            prefix = parts[0]
            suffix = parts[1].split('"', 1)[1]
            extinf_line = prefix + suffix
        except Exception:
            pass
    if "group-title='" in extinf_line:
        try:
            parts = extinf_line.split("group-title='")
            prefix = parts[0]
            suffix = parts[1].split("'", 1)[1]
            extinf_line = prefix + suffix
        except Exception:
            pass

    # --- Title cleaning logic & LCN Matching ---
    chno = ""
    if "," in extinf_line:
        prefix, title = extinf_line.split(",", 1)
        title = title.replace(" Digital", "").replace("digital", "").replace("DIGITAL", "")
        if "star sports" not in title.lower():
            title = title.replace(" Hindi", "").replace("hindi", "").replace("HINDI", "")
        
        title = title.strip()
        channel_title_clean = " ".join(title.lower().split())
        
        # Match channel name with LCN dictionary
        chno = lcn_dict.get(channel_title_clean, "")
        
        # Prefix format clean rakho (#EXTINF:-1)
        prefix = prefix.strip()
        if not prefix.startswith("#EXTINF"):
            prefix = "#EXTINF:-1"
        elif ":" not in prefix:
            prefix = "#EXTINF:-1"
            
        # tvg-chno, ch-number tags ate channel name vich LCN add karna (e.g. Sony SAB (107))
        if chno:
            # Avoid adding parentheses again if already present
            if f"({chno})" not in title:
                title = f"{title} ({chno})"
            extinf_line = f'{prefix} tvg-chno="{chno}" ch-number="{chno}",{title}'
        else:
            extinf_line = f'{prefix},{title}'
    else:
        extinf_line = extinf_line.replace(" Digital", "").replace("digital", "").replace("DIGITAL", "")
        if "star sports" not in extinf_line.lower():
            extinf_line = extinf_line.replace(" Hindi", "").replace("hindi", "").replace("HINDI", "")
    # -------------------------------------------------------------------------

    channel_id = ""
    if 'tvg-id="' in extinf_line:
        try:
            channel_id = extinf_line.split('tvg-id="')[1].split('"')[0]
        except Exception:
            pass

    raw_stream_line = ""
    for f in range(i + 1, min(len(lines), i + 5)):
        candidate_line = clean_val(lines[f])
        if candidate_line.startswith("http"):
            raw_stream_line = candidate_line.split()[0]
            raw_stream_line = clean_val(raw_stream_line.split('"')[0].split(',')[0])
            break
            
    if not channel_id and "id=" in extinf_line:
        try:
            channel_id = extinf_line.split('id="')[1].split('"')[0]
        except Exception:
            pass

    if not channel_id and raw_stream_line:
        if "id=" in raw_stream_line:
            try:
                channel_id = raw_stream_line.split("id=")[1].split("&")[0]
            except Exception:
                pass

    lower_text = (extinf_line + raw_stream_line).lower()
    for b in range(max(0, i - 3), i + 4):
        lower_text += lines[b].lower()

    is_hotstar = "hotstar" in lower_text or "jhs" in lower_text
    is_sliv = "sliv" in lower_text or "sony" in lower_text or "ten" in lower_text

    channel_lines = [extinf_line]

    try:
        key_url = None
        for b in range(max(0, i - 3), i):
            sub_b = clean_val(lines[b])
            if "inputstream.adaptive.license_key=" in sub_b:
                key_url = clean_val(sub_b.split("inputstream.adaptive.license_key=")[1].split('"')[0])

        if is_hotstar:
            user_agent = "Hotstar;in.startv.hotstar/25.02.24.8.11169 (Android/15)"
        elif is_sliv:
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        else:
            user_agent = "Denver1769"

        formatted_license_key = None
        if key_url:
            try:
                key_url = clean_val(key_url.replace('"', "").replace("'", ""))
                key_res = session.get(key_url, headers={"User-Agent": user_agent}, timeout=3)
                if key_res.status_code == 200:
                    key_json = key_res.json()
                    key_pairs = []
                    keys_list = key_json.get("base64", {}).get("keys", [])
                    for k_obj in keys_list:
                        kid_b64 = clean_val(k_obj.get("kid", ""))
                        k_b64 = clean_val(k_obj.get("k", ""))
                        if kid_b64 and k_b64:
                            kid_hex = b64_to_hex(kid_b64)
                            k_hex = b64_to_hex(k_b64)
                            key_pairs.append(f"{kid_hex}:{k_hex}")
                    if key_pairs:
                        formatted_license_key = ",".join(key_pairs)
            except Exception:
                pass
        
        if not formatted_license_key:
            formatted_license_key = "null:null"

        final_stream_url = raw_stream_line
        if raw_stream_line:
            resolved = resolve_stream_url(raw_stream_line, session, user_agent, is_hotstar, is_sliv)
            if resolved:
                final_stream_url = clean_val(resolved.split('"')[0].split(',')[0])

        is_mpd_link = ".mpd" in final_stream_url.lower()

        # --- Zero Latency Start + 5 Minute Background Buffer Settings ---
        channel_lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.manifest_type={'mpd' if is_mpd_link else 'hls'}")
        channel_lines.append("#KODIPROP:inputstream.adaptive.max_bandwidth=0")
        channel_lines.append("#KODIPROP:inputstream.adaptive.stream_selection_type=automatic")
        channel_lines.append("#KODIPROP:inputstream.adaptive.max_buffer_time=300")
        channel_lines.append("#KODIPROP:inputstream.adaptive.buffer_segment_size=1000")
        channel_lines.append("#KODIPROP:inputstream.adaptive.live_delay=0")

        if is_hotstar:
            cookie_str = ""
            for check_line in [raw_stream_line] + lines[max(0, i-2):min(len(lines), i+3)]:
                check_line = clean_val(check_line)
                if "hdntl=" in check_line:
                    try:
                        parts = check_line.split("hdntl=")
                        for p in parts[1:]:
                            candidate = clean_val(p.split()[0].split('"')[0])
                            if "exp=" in candidate:
                                cookie_str = "hdntl=" + clean_val(candidate.split("&")[0])
                                break
                    except Exception:
                        pass
                if cookie_str:
                    break
            
            if not cookie_str:
                cookie_str = "hdntl=exp=1791763208~acl=%2f*~id=ce6ecdabc53ea306cc7be95fa7a1b49c~data=hdntl~hmac=8a7405e9c3a1f2880ac44abb4e3fee31d750b5c4d6d4bfaa67bac50b175140a1"

            base_url = clean_val(final_stream_url.split("|")[0].split('"')[0])

            if is_mpd_link:
                channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
                channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")
                pipe_headers = f"User-Agent={user_agent}&Accept-Encoding=identity&X-Denver-Secure=true&Host=livetv.hotstar.com&Connection=Keep-Alive&Cookie={cookie_str}"
            else:
                pipe_headers = f"User-Agent={user_agent}&Origin=https://www.hotstar.com&Referer=https://www.hotstar.com/&Cookie={cookie_str}"

            final_pipe_url = clean_val(f"{base_url}|{pipe_headers}")
            channel_lines.append(final_pipe_url)

        elif is_sliv:
            if is_mpd_link:
                channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
                channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")

            channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
            channel_lines.append("#EXTVLCOPT:http-referrer=https://www.sonyliv.com/")
            channel_lines.append("#EXTVLCOPT:http-extra-headers=Origin: https://www.sonyliv.com")
            channel_lines.append(clean_val(final_stream_url) if final_stream_url else "http://dummy-link-to-prevent-break")

        else:  
            channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")
            channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
            
            jio_cookie = ""
            for check_line in [raw_stream_line] + lines[max(0, i-2):min(len(lines), i+3)]:
                check_line = clean_val(check_line)
                if "hdnea=" in check_line:
                    try:
                        parts = check_line.split("hdnea=")
                        for p in parts[1:]:
                            candidate = clean_val(p.split()[0])
                            if "exp=" in candidate or "st=" in candidate:
                                jio_cookie = "hdnea=" + clean_val(candidate.split("&")[0])
                                break
                    except Exception:
                        pass
                if jio_cookie:
                    break

            if jio_cookie:
                channel_lines.append(f"#EXTVLCOPT:http-cookie={jio_cookie}")
                channel_lines.append(f'#EXTHTTP:{{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/","Cookie":"{jio_cookie}","Connection":"keep-alive"}}')
            else:
                channel_lines.append('#EXTHTTP:{"Origin":"https://www.jiotv.com/","Referer":"https://www.jiotv.com/","Connection":"keep-alive"}')

            channel_lines.append(clean_val(final_stream_url) if final_stream_url else "http://dummy-link-to-prevent-break")

    except Exception:
        channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
        channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={formatted_license_key}")
        channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
        channel_lines.append(clean_val(raw_stream_line) if raw_stream_line else "http://dummy-link-to-prevent-break")

    return chno, channel_lines

def generate_safe_playlist_1000():
    if not PLAYLIST_URL:
        return

    session = get_robust_session()
    clear_old_ips(session)
    
    # Fetch LCN dictionary
    lcn_dict = fetch_lcn_dict(session)

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

        processed_channels = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_single_channel, idx, lines, session, lcn_dict): idx
                for idx in target_indices
            }
            for future in as_completed(futures):
                try:
                    chno, res_lines = future.result()
                    if res_lines:
                        # Numerical sorting key (je chno number hai taan int, nahi taan 99999 jo ki last vich javega)
                        try:
                            sort_key = int(chno)
                        except (ValueError, TypeError):
                            sort_key = 99999
                        processed_channels.append((sort_key, res_lines))
                except Exception:
                    pass

        # Sort channels in ascending order based on LCN numbers
        processed_channels.sort(key=lambda x: x[0])

        new_lines = ["#EXTM3U"]
        for sort_key, res_lines in processed_channels:
            new_lines.extend(res_lines)

        output_file = ".m3u"  
        with open(output_file, "w", encoding="utf-8") as f:  
            f.write("\n".join(new_lines))  

        print(f"\n[+] Success! Final playlist saved as '{output_file}' with sorted channels.")

    except Exception as e:
        print(f"\n[-] Critical Error: {e}")

if __name__ == "__main__":
    generate_safe_playlist_1000()
