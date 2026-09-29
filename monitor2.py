#!/usr/bin/env python3
import os, sys, json, time, urllib.request, urllib.parse
from datetime import datetime

GPUSHARE_TOKEN = os.environ.get("GPUSHARE_TOKEN", "")
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")
TARGET_GPUS = ["3080", "3090", "4090", "4080", "5090", "5060"]
REQUIRED_CUDA = 13.0
MIN_BANDWIDTH = 400
API_BASE = "https://api.gpushare.com/app/api"
STATE_FILE = os.path.join(os.path.dirname(__file__), "last_state2.json")
RUN_SECONDS = 5 * 3600 + 50 * 60
CHECK_INTERVAL = 5

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
    for page in range(1, 6):
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

def gpu_matches(gpu_name):
    name = gpu_name.upper()
    return any(g.upper() in name for g in TARGET_GPUS)

def short_gpu(gpu_name):
    for g in TARGET_GPUS:
        if g.upper() in gpu_name.upper():
            return g.upper()
    return gpu_name

def filter_machines(machines):
    results = []
    for m in machines:
        gpu = m.get("baseInfo", {}).get("gpuName", "")
        if not gpu_matches(gpu):
            continue
        if not m.get("isOnline"):
            continue
        free = m.get("gpuNum", 0) - m.get("gpuUsed", 0)
        if free <= 0:
            continue
        cuda = float(m.get("baseInfo", {}).get("gpuToolkitVersion", "0"))
        if cuda != REQUIRED_CUDA:
            continue
        dl_bytes = int(m.get("baseInfo", {}).get("netDownloadSpeed", 0))
        dl_mbps = round(dl_bytes * 8 / 1000000)
        if dl_mbps < MIN_BANDWIDTH:
            continue
        driver = str(m.get("baseInfo", {}).get("gpuDriverVersion", "?")).split(".")[0]
        price = next((s.get("price", "?") for s in m.get("skuList", []) if s.get("skuName") == "payg"), "?")
        mid = m.get("id", "")
        rent_url = f"https://www.gpushare.com/store/hire/create?id={mid}&models=-1&skuName=payg"
        results.append({
            "name": m.get("machineName", "?"),
            "gpu": short_gpu(gpu),
            "free": free,
            "driver": driver,
            "bandwidth": dl_mbps,
            "price": price,
            "rent_url": rent_url
        })
    return results

def send_wecom(title, desp):
    if not WECOM_WEBHOOK:
        print(f"[Notification] {title}\n{desp}")
        return
    content = f"## {title}\n{desp}"
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(WECOM_WEBHOOK, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[WeCom error] {e}")

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
                send_wecom("GPU2 Token expired", "Update GPUSHARE_TOKEN in GitHub Secrets.")
                auth_notified = True
            print(f"[{now}] TOKEN EXPIRED")
            break
        matches = filter_machines(result)
        current_keys = set(m["name"] for m in matches)
        new_machines = current_keys - prev_keys
        if matches and (first_run or new_machines):
            matches_sorted = sorted(matches, key=lambda m: m["name"] not in new_machines)
            lines = []
            for m in matches_sorted:
                is_new = m["name"] in new_machines and not first_run
                tag = "🆕 " if is_new else ""
                line = (f"{tag}**{m['gpu']}** | 驱动{m['driver']} | {m['bandwidth']}Mbps | "
                        f"空闲{m['free']} | ¥{m['price']}/h\n"
                        f"[点这里租用]({m['rent_url']})")
                lines.append(line)
            label = "当前可用" if first_run else f"新增 {len(new_machines)} 台"
            desp = "\n\n".join(lines)
            send_wecom(f"GPU2: {label}", desp)
            print(f"[{now}] Pushed: {len(matches)} machine(s), {len(new_machines)} new")
            first_run = False
        else:
            print(f"[{now}] {len(matches)} machines (no new)")
        prev_keys = current_keys
        save_current(current_keys)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
