from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time  # <--- Eh import zaroor add karo
from requests.adapters import HTTPAdapter
import requests
from urllib3.util.retry import Retry

PLAYLIST_URL = "https://game.playindia.fun/Jtv/RiYlIZ/Playlist.m3u"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}  # <--- User agent thoda standard rakho
MAX_CHANNELS = 3000
MAX_WORKERS = 1  # 1 worker hi rakho taan ik ik karke request jave


def get_robust_session():
  session = requests.Session()
  retries = Retry(
      total=5,
      backoff_factor=2,
      status_forcelist=[403, 429, 500, 502, 503, 504],
  )  # <--- 403 nu retry vich vi rakh sakde ho
  session.mount("https://", HTTPAdapter(max_retries=retries))
  session.mount("http://", HTTPAdapter(max_retries=retries))
  return session


session = get_robust_session()


def process_channel_block(channel_data):
  i, lines = channel_data
  line = lines[i].strip()
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
      if '"' in key_url:
        key_url = key_url.replace('"', "")
      key_res = session.get(key_url, headers=HEADERS, timeout=10)
      if key_res.status_code == 200:
        key_json = key_res.json()
        embedded_key_data = json.dumps(key_json)
    except Exception:
      pass

  channel_lines = []
  channel_lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
  if embedded_key_data:
    channel_lines.append(
        f"#KODIPROP:inputstream.adaptive.license_key={embedded_key_data}"
    )
  elif key_url:
    channel_lines.append(f"#KODIPROP:inputstream.adaptive.license_key={key_url}")

  channel_lines.append(extinf_line)
  channel_lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")

  if mpd_line:
    try:
      channel_headers = {"User-Agent": user_agent}
      r = session.get(
          mpd_line, headers=channel_headers, allow_redirects=False, timeout=10
      )

      real_url = (
          r.headers.get("Location")
          if r.status_code in [301, 302, 303, 307, 308]
          else mpd_line
      )
      clean_url = real_url.strip().split()[0]
      if clean_url.endswith("~"):
        clean_url = clean_url[:-1]
      channel_lines.append(clean_url)
    except Exception:
      clean_url = mpd_line.strip().split()[0]
      if clean_url.endswith("~"):
        clean_url = clean_url[:-1]
      channel_lines.append(clean_url)

  # **IMPORTANT:** Har request ton baad 0.5 to 1 second da gap paao taan 403 na aave
  time.sleep(0.4)

  return i, channel_lines
    
