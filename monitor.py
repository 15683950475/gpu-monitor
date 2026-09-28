#!/usr/bin/env python3
import os, sys, json, time, urllib.request, urllib.parse
from datetime import datetime

GPUSHARE_TOKEN = os.environ.get("GPUSHARE_TOKEN", "")
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")
MIN_CUDA = 12.8
MIN_BANDWIDTH = 400
API_BASE = "https://api.gpushare.com/app/api"
STATE_FILE = os.path.join(os.path.dirname(__file__), "last_state.json")
RUN_SECONDS = 5 * 3600 + 50 * 60
CHECK_INTERVAL = 30

def api_get(path, token):
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Origin", "https://www.gpushare.com")
    req.add_header("Referer", "https://www.gpushare.com/store")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None
        raise

def fetch_all_machines(token):
    all_machines = []
    for page in range(1, 5):
        qs = urllib.parse.urlencode({"models": -1, "gpuName": "", "priceOrder": "asc", "pn": page, "ps": 50})
        data = api_get(f"/market/machine/list?{qs}", token)
        if data is None:
            return "AUTH_EXPIRED"
        if not data or "data" not in data:
            break
        all_machines.extend(data["data"]["list"])
        if page * 50 >= data["data"]["total"]:
            break
    return all_machines

def filter_machines(machines):
    results = []
    for m in machines:
        gpu = m.get("baseInfo", {}).get("gpuName", "")
        if "3090" not in gpu:
            continue
        if not m.get("isOnline"):
            continue
        free = m.get("gpuNum", 0) - m.get("gpuUsed", 0)
        if free <= 0:
            continue
        cuda = float(m.get("baseInfo", {}).get("gpuToolkitVersion", "0"))
        if cuda < MIN_CUDA:
            continue
        dl_bytes = int(m.get("baseInfo", {}).get("netDownloadSpeed", 0))
        dl_mbps = round(dl_bytes * 8 / 1000000)
        if dl_mbps < MIN_BANDWIDTH:
            continue
        price = next((s.get("price", "?") for s in m.get("skuList", []) if s.get("skuName") == "payg"), "?")
        results.append({"name": m.get("machineName", "?"), "gpu": gpu, "free": free, "total": m.get("gpuNum", 0), "cuda": m.get("baseInfo", {}).get("gpuToolkitVersion", "?"), "bandwidth": dl_mbps, "price": price})
    return results

def send_serverchan(title, desp):
    if not SERVERCHAN_KEY:
        print(f"[Notification] {title}\n{desp}")
        return
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"[ServerChan error] {e}")

def load_previous():
    try:
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_current(keys):
    with open(STATE_FILE, "w") as f:
        json.dump(list(keys), f)

def main():
    if not GPUSHARE_TOKEN:
        print("ERROR: GPUSHARE_TOKEN not set")
        sys.exit(1)
    start = time.time()
    prev_keys = load_previous()
    first_run = len(prev_keys) == 0
    auth_notified = False
    while time.time() - start < RUN_SECONDS:
        now = datetime.now().strftime("%H:%M:%S")
        result = fetch_all_machines(GPUSHARE_TOKEN)
        if result == "AUTH_EXPIRED":
            if not auth_notified:
                send_serverchan("GPU Monitor - Token expired!", "gpushare token expired. Update GPUSHARE_TOKEN in GitHub Secrets.")
                auth_notified = True
            print(f"[{now}] TOKEN EXPIRED")
            break
        matches = filter_machines(result)
        current_keys = set(m["name"] for m in matches)
        if matches:
            new_machines = current_keys - prev_keys
            if first_run or new_machines:
                lines = [f"- **{m['name']}** | free: {m['free']}/{m['total']} | CUDA {m['cuda']} | {m['bandwidth']}Mbps | ${m['price']}/hr" for m in matches]
                label = "Current machines" if first_run else f"FOUND {len(new_machines)} new!"
                desp = f"### {label}\n\n" + "\n".join(lines) + "\n\n[Open gpushare](https://www.gpushare.com/store)"
                send_serverchan(f"GPU Monitor: {label}", desp)
                print(f"[{now}] Pushed: {len(matches)} machine(s), {len(new_machines)} new")
                first_run = False
            else:
                print(f"[{now}] {len(matches)} machines (no new)")
        else:
            print(f"[{now}] No matching machine")
        prev_keys = current_keys
        save_current(current_keys)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
