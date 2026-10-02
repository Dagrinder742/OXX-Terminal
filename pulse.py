#!/usr/bin/env python3
"""
pulse.py - zero-dependency order-book crawler + local web server + live ASCII TUI.

Python 3.8+, standard library only.

    python3 pulse.py                          # Coinbase BTC-USD
    python3 pulse.py --source kraken          # Kraken XBTUSD
    python3 pulse.py --source binanceus --symbol ETHUSD
    python3 pulse.py --sim                    # offline random-walk book

Terminal: live price chart + depth ladder with pulsing best bid/ask. Press q to quit.
Browser:  http://127.0.0.1:8765  (JSON at /api/book)
If a feed is unreachable it falls back to a simulated book and retries every tick.

Test: python3 pulse.py --sim if you want to see the TUI before pointing it at a live feed.
"""
import argparse, json, math, os, random, shutil, sys, threading, time, urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOURCES = {
    "coinbase":  ("https://api.exchange.coinbase.com/products/{s}/book?level=2", "BTC-USD"),
    "kraken":    ("https://api.kraken.com/0/public/Depth?pair={s}&count=50", "XBTUSD"),
    "binanceus": ("https://api.binance.us/api/v3/depth?symbol={s}&limit=50", "BTCUSD"),
}

# ───────────────────────────── data layer ─────────────────────────────

def parse(src, d):
    if src == "kraken":
        if d.get("error"):
            raise RuntimeError(d["error"])
        d = next(iter(d["result"].values()))
    bids = [(float(r[0]), float(r[1])) for r in d["bids"]]
    asks = [(float(r[0]), float(r[1])) for r in d["asks"]]
    if not bids or not asks:
        raise RuntimeError("empty book")
    return sorted(bids, reverse=True), sorted(asks)

def sim_book(mid, rng, depth=50):
    tick = max(mid * 1e-5, 0.01)
    p = mid - tick * rng.uniform(0.5, 1.5)
    bids = []
    for _ in range(depth):
        bids.append((round(p, 2), rng.expovariate(1 / 0.8) + 0.01))
        p -= tick * rng.uniform(1, 4)
    p = mid + tick * rng.uniform(0.5, 1.5)
    asks = []
    for _ in range(depth):
        asks.append((round(p, 2), rng.expovariate(1 / 0.8) + 0.01))
        p += tick * rng.uniform(1, 4)
    return bids, asks

class State:
    def __init__(s):
        s.lock = threading.Lock()
        s.bids, s.asks = [], []
        s.hist = deque(maxlen=1200)
        s.live, s.err, s.lat, s.n = False, "", 0.0, 0
        s.prev_mid, s.dir, s.moved = None, 0, 0.0

    def update(s, bids, asks, live, lat, err=""):
        mid = (bids[0][0] + asks[0][0]) / 2
        with s.lock:
            if s.prev_mid is not None and mid != s.prev_mid:
                s.dir, s.moved = (1 if mid > s.prev_mid else -1), time.time()
            s.prev_mid = mid
            s.bids, s.asks, s.live, s.lat, s.err = bids, asks, live, lat, err
            s.hist.append(mid)
            s.n += 1

    def snap(s):
        with s.lock:
            return dict(bids=list(s.bids), asks=list(s.asks), hist=list(s.hist),
                        live=s.live, err=s.err, lat=s.lat, n=s.n, dir=s.dir, moved=s.moved)

def poller(args, st, stop):
    url, _ = SOURCES[args.source]
    rng, mid = random.Random(), None
    while not stop.is_set():
        t0 = time.time()
        try:
            if args.sim:
                raise RuntimeError("")
            req = urllib.request.Request(url.format(s=args.sym),
                                         headers={"User-Agent": "pulse/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.load(r)
            b, a = parse(args.source, data)
            mid = (b[0][0] + a[0][0]) / 2
            st.update(b, a, True, (time.time() - t0) * 1000)
        except Exception as e:
            mid = (mid or 60000.0) * (1 + rng.gauss(0, 2e-4))
            b, a = sim_book(mid, rng)
            st.update(b, a, False, 0, "" if args.sim else f"{type(e).__name__}: {e}"[:60])
        stop.wait(args.interval)

# ───────────────────────────── web server ─────────────────────────────

PAGE = r"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>pulse</title>
<style>body{background:#0b0e11;color:#cfd8dc;font:14px ui-monospace,Menlo,monospace;margin:1.2rem}
.a{color:#ff5370}.b{color:#26d07c}</style><pre id=o>connecting...</pre>
<script>
const bar=(v,m)=>'█'.repeat(Math.round(v/m*36));
const row=(c,l,m)=>`<span class=${c}>${l[0].toFixed(2).padStart(12)} ${l[1].toFixed(4).padStart(10)} ${bar(l[2],m)}</span>\n`;
async function tick(){try{const d=await(await fetch('/api/book')).json();
const m=Math.max(d.asks.at(-1)[2],d.bids.at(-1)[2]);
let h=`${d.symbol} @ ${d.source}  mid ${d.mid.toFixed(2)}  spread ${d.spread.toFixed(2)}  ${d.live?'LIVE':'SIM'}\n\n`;
for(const l of [...d.asks].reverse())h+=row('a',l,m);
h+='\n';for(const l of d.bids)h+=row('b',l,m);
document.getElementById('o').innerHTML=h}catch(e){}}
setInterval(tick,1000);tick();
</script>"""

def make_api(st, args):
    def levels(x, n=15):
        c, out = 0.0, []
        for p, q in x[:n]:
            c += q
            out.append([p, q, c])
        return out
    def api():
        s = st.snap()
        if not s["bids"]:
            return None
        b, a = s["bids"], s["asks"]
        return {"symbol": args.sym, "source": args.source, "live": s["live"],
                "mid": (b[0][0] + a[0][0]) / 2, "spread": a[0][0] - b[0][0],
                "bids": levels(b), "asks": levels(a), "history": s["hist"][-120:]}
    return api

def serve(args, st):
    api = make_api(st, args)
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            code, ctype, body = 200, "text/html; charset=utf-8", PAGE.encode()
            if self.path.startswith("/api/book"):
                d = api()
                ctype = "application/json"
                code, body = (200, json.dumps(d).encode()) if d else (503, b"{}")
            elif self.path not in ("/", "/index.html"):
                code, body = 404, b"not found"
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), H)
    except OSError:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

# ───────────────────────────── terminal UI ─────────────────────────────

RST, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
VB = " ▁▂▃▄▅▆▇█"      # vertical eighths (chart)
HB = " ▏▎▍▌▋▊▉"      # horizontal eighths (depth bars)
def c(n):    return f"\x1b[38;5;{n}m"
def gcol(p): return 16 + 6 * (2 + round(3 * p))     # greens, dim -> bright
def rcol(p): return 16 + 36 * (2 + round(3 * p))    # reds,   dim -> bright

def render(st, args, port):
    cols, rows = shutil.get_terminal_size((100, 32))
    W = cols - 1
    s, now = st.snap(), time.time()
    if not s["bids"]:
        return "\x1b[H\x1b[J connecting..."
    pulse = (math.sin(now * 5.6) + 1) / 2                 # ~0.9 Hz heartbeat
    bids, asks, hist = s["bids"], s["asks"], s["hist"]
    mid, spread = hist[-1], asks[0][0] - bids[0][0]
    chg = (mid / hist[0] - 1) * 100
    up = chg >= 0
    flash = "\x1b[7m" if now - s["moved"] < 0.35 else ""
    pcol = c(gcol(pulse)) if s["dir"] >= 0 else c(rcol(pulse))

    L = [f" {BOLD}{args.sym}{RST}  {BOLD}{flash}{pcol} {mid:,.2f} {RST}  "
         f"{c(gcol(3) if up else rcol(3))}{chg:+.3f}%{RST}  {DIM}spread {spread:,.2f}{RST}"]
    dot = f"{c(gcol(pulse))}●{RST} LIVE" if s["live"] else f"{c(214)}●{RST} SIM"
    L.append(f" {dot} {DIM}{args.source} · {s['lat']:.0f} ms · {s['n']} ticks · "
             f"http://127.0.0.1:{port}{RST}" + (f"  {c(203)}{s['err']}{RST}" if s["err"] else ""))

    avail = rows - 5
    ch = max(4, avail * 2 // 5)
    n = max(2, (avail - ch) // 2)

    # ── price chart (filled area, eighth-block resolution) ──
    LW = 11
    cw = max(10, W - LW - 1)
    pts = list(hist)
    if len(pts) > cw:
        pts = [pts[int(i * len(pts) / cw)] for i in range(cw)]
        pts[-1] = hist[-1]
    lo, hi = min(pts), max(pts)
    if hi - lo < 1e-9:
        lo, hi = lo - max(hi * 1e-5, 0.01), hi + max(hi * 1e-5, 0.01)
    lev = [1 + (p - lo) / (hi - lo) * (ch * 8 - 1) for p in pts]
    pad = " " * (cw - len(pts))
    base = c(gcol(3) if up else rcol(3))
    head = c(gcol(pulse) if up else rcol(pulse))
    for r in range(ch):
        k = ch - 1 - r
        cells = ["█" if (f := v - k * 8) >= 8 else (VB[int(f)] if f >= 1 else " ") for v in lev]
        val = hi if r == 0 else lo if r == ch - 1 else (hi + lo) / 2 if r == ch // 2 else None
        label = f"{val:>{LW - 1},.2f} " if val is not None else " " * LW
        L.append(f"{DIM}{label}{RST}{pad}{base}{''.join(cells[:-1])}{head}{cells[-1]}{RST}")

    # ── depth ladder ──
    def cum(x):
        t, o = 0.0, []
        for p, q in x[:n]:
            t += q
            o.append((p, q, t))
        return o
    bc, ac = cum(bids), cum(asks)
    mx = max(bc[-1][2], ac[-1][2])
    bw = max(8, W - 27)
    def bar(v):
        e = int(v / mx * bw * 8)
        return "█" * (e // 8) + (HB[e % 8] if e % 8 else "")

    for i in reversed(range(len(ac))):
        p, q, cm = ac[i]
        col = c(rcol(pulse) if i == 0 else rcol(2 if i > 2 else 3))
        L.append(f" {col}{p:>11,.2f} {q:>9.4f} {bar(cm)}{RST}")

    tb, ta = sum(q for _, q in bids[:n]), sum(q for _, q in asks[:n])
    share = tb / (tb + ta)
    k = int(share * 24)
    L.append(f" {DIM}──{RST} {BOLD}{mid:,.2f}{RST} {c(gcol(3))}{'█' * k}{c(rcol(3))}{'█' * (24 - k)}{RST} "
             f"{DIM}bids {share * 100:.0f}% of top-{n} depth{RST}")

    for i, (p, q, cm) in enumerate(bc):
        col = c(gcol(pulse) if i == 0 else gcol(2 if i > 2 else 3))
        L.append(f" {col}{p:>11,.2f} {q:>9.4f} {bar(cm)}{RST}")

    L.append(f" {DIM}q quit{RST}")
    return "\x1b[H" + "\x1b[K\n".join(L[:rows - 1]) + "\x1b[K\x1b[J"

def read_key():
    try:
        if os.name == "nt":
            import msvcrt
            return msvcrt.getwch() if msvcrt.kbhit() else None
        import select
        return sys.stdin.read(1) if select.select([sys.stdin], [], [], 0)[0] else None
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=SOURCES, default="coinbase")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between feed polls")
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--sim", action="store_true", help="skip the network, simulate a book")
    args = ap.parse_args()
    args.sym = args.symbol or SOURCES[args.source][1]
    if not sys.stdout.isatty():
        sys.exit("pulse.py needs an interactive terminal.")
    if os.name == "nt":
        os.system("")  # enable ANSI escapes on Windows 10+

    st, stop = State(), threading.Event()
    threading.Thread(target=poller, args=(args, st, stop), daemon=True).start()
    port = serve(args, st)

    old = None
    if os.name != "nt" and sys.stdin.isatty():
        import termios, tty
        old = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
    out = sys.stdout
    out.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            out.write(render(st, args, port))
            out.flush()
            if read_key() in ("q", "Q", "\x03"):
                break
            time.sleep(1 / args.fps)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        out.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        out.flush()
        if old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)

if __name__ == "__main__":
    main()
