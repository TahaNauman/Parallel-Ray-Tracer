#!/usr/bin/env python3
"""Benchmark driver for the ray tracer (run from the project root).

Runs every configuration of a suite interleaved (shuffled order each round) so that
machine drift hits all configurations equally, repeats the whole set, and appends one
CSV row per run to results/<suite>.csv. Before benchmarking, every binary's 400 px
output is checked against the reference checksum.

Examples:
  python3 scripts/bench.py --suite smoke --repeats 1
  python3 scripts/bench.py --suite main --repeats 3
  python3 scripts/bench.py --suite main --dry-run
  python3 scripts/bench.py --suite big --only seq --repeats 1
"""
import argparse
import csv
import hashlib
import os
import random
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime

REF_MD5 = "56b7db7050c821d9e94f209f381388ed"   # --width 400 --spp 10 --objects 100 (depth 5, seed 42)
MPI = ["mpirun", "--bind-to", "none", "--use-hwthread-cpus", "--oversubscribe", "-x", "OMP_SCHEDULE"]
KV = re.compile(r"(\w+)=(\S+)")
FIELDS = ["suite", "round", "name", "version", "mode", "ranks", "workers", "threads", "tile",
          "width", "height", "spp", "depth", "objects",
          "compute_s", "compute_max_s", "compute_min_s", "gather_s", "write_s",
          "wall_s", "timestamp"]


# ---------- configurations ----------
def seq():
    return dict(name="seq", version="seq", binary="bin/raytracer_seq", np=0, threads=1, mode="")

def omp(t):
    return dict(name=f"omp-t{t}", version="omp", binary="bin/raytracer_omp", np=0, threads=t, mode="")

def mpi_static(n):
    return dict(name=f"mpi-static-n{n}", version="mpi-static", binary="bin/raytracer_mpi",
                np=n, threads=1, mode="static")

def mpi_dynamic(workers):   # one extra rank is the coordinator
    return dict(name=f"mpi-dynamic-w{workers}", version="mpi-dynamic", binary="bin/raytracer_mpi",
                np=workers + 1, threads=1, mode="dynamic")

def hyb_static(n, t):
    return dict(name=f"hybrid-static-{n}x{t}", version="hybrid-static", binary="bin/raytracer_hybrid",
                np=n, threads=t, mode="static")

def hyb_dynamic(workers, t):
    return dict(name=f"hybrid-dynamic-{workers}x{t}", version="hybrid-dynamic", binary="bin/raytracer_hybrid",
                np=workers + 1, threads=t, mode="dynamic")


# ---------- suites: (default params, function returning [(config, params), ...]) ----------
def fixed(cfgs):
    return lambda base: [(c, dict(base)) for c in cfgs]

def resolution_jobs(base):
    return [(c, dict(base, width=w)) for w in (1280, 1920, 3840)
            for c in (seq(), omp(4), mpi_dynamic(4))]

def complexity_jobs(base):
    pts = [dict(base, spp=v) for v in (1, 4, 16, 64)]
    pts += [dict(base, depth=v) for v in (1, 2, 3, 5, 8)]
    pts += [dict(base, objects=v) for v in (10, 50, 100, 200)]
    uniq, seen = [], set()
    for q in pts:                       # the default point appears in all three sweeps; run it once
        key = tuple(sorted(q.items()))
        if key not in seen:
            seen.add(key)
            uniq.append(q)
    return [(c, q) for q in uniq for c in (seq(), omp(4), mpi_dynamic(4))]

SUITES = {
    "smoke": (dict(width=400, spp=10, depth=5, objects=100),
              fixed([seq(), omp(4), mpi_static(4), mpi_dynamic(4), hyb_static(2, 4), hyb_dynamic(2, 4)])),
    "main": (dict(width=1920, spp=16, depth=5, objects=100),
             fixed([seq()]
                   + [omp(t) for t in (1, 2, 3, 4, 6, 8)]
                   + [mpi_static(n) for n in (1, 2, 4, 8)]
                   + [mpi_dynamic(w) for w in (1, 2, 4, 8)]
                   + [hyb_static(n, t) for n, t in ((1, 8), (2, 4), (4, 2), (8, 1))]
                   + [hyb_dynamic(w, t) for w, t in ((1, 8), (2, 4), (4, 2), (8, 1))])),
    "resolution": (dict(width=1920, spp=4, depth=5, objects=100), resolution_jobs),
    "complexity": (dict(width=960, spp=16, depth=5, objects=100), complexity_jobs),
    "big": (dict(width=7680, spp=16, depth=5, objects=100),
            fixed([seq(), omp(4), mpi_dynamic(4), hyb_dynamic(2, 4), hyb_dynamic(4, 2)])),
}


# ---------- running ----------
def build_cmd(cfg, p, tile, out="/dev/null"):
    args = ["--width", str(p["width"]), "--spp", str(p["spp"]),
            "--depth", str(p["depth"]), "--objects", str(p["objects"])]
    if cfg["version"] in ("omp", "hybrid-static", "hybrid-dynamic"):
        args += ["--threads", str(cfg["threads"])]
    if cfg["np"]:
        args += ["--mode", cfg["mode"], "--tile", str(tile), "--out", out]
        return MPI + ["-np", str(cfg["np"]), cfg["binary"]] + args
    return [cfg["binary"]] + args       # seq/omp write the image to stdout


def run_env():
    return dict(os.environ, OMP_SCHEDULE="dynamic,1")


def run_once(cfg, p, tile, timeout):
    cmd = build_cmd(cfg, p, tile)
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           text=True, env=run_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, 0.0, "timeout"
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        return None, wall, f"exit {r.returncode}: {r.stderr.strip()[-300:]}"
    line = next((l for l in r.stderr.splitlines() if l.startswith("RESULT")), None)
    if line is None:
        return None, wall, "no RESULT line in output"
    return dict(KV.findall(line)), wall, ""


def make_row(suite, rnd, cfg, p, kv, wall):
    ranks = int(kv.get("ranks", 1))
    comp = float(kv["compute_s"])
    return {
        "suite": suite, "round": rnd, "name": cfg["name"], "version": cfg["version"],
        "mode": cfg["mode"] or "-", "ranks": ranks,
        "workers": ranks - 1 if cfg["mode"] == "dynamic" else ranks,
        "threads": int(kv.get("threads", cfg["threads"])), "tile": int(kv.get("tile", 0)),
        "width": p["width"], "height": int(kv.get("height", 0)), "spp": p["spp"],
        "depth": p["depth"], "objects": p["objects"],
        "compute_s": comp,
        "compute_max_s": float(kv.get("compute_max_s", comp)),
        "compute_min_s": float(kv.get("compute_min_s", comp)),
        "gather_s": float(kv.get("gather_s", 0)), "write_s": float(kv.get("write_s", 0)),
        "wall_s": round(wall, 3), "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def verify(jobs, tile):
    """Run each distinct config once at 400 px and compare the image with the reference checksum."""
    p = dict(width=400, spp=10, depth=5, objects=100)
    tmp = "/tmp/bench_verify.ppm"
    cfgs = {c["name"]: c for c, _ in jobs}
    ok = True
    print(f"Verifying {len(cfgs)} configurations against {REF_MD5} ...")
    for name, cfg in cfgs.items():
        if os.path.exists(tmp):
            os.remove(tmp)
        cmd = build_cmd(cfg, p, tile, out=tmp)
        if cfg["np"]:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=run_env())
        else:
            with open(tmp, "wb") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.DEVNULL, env=run_env())
        md5 = hashlib.md5(open(tmp, "rb").read()).hexdigest() if os.path.exists(tmp) else "no output"
        good = md5 == REF_MD5
        ok = ok and good
        print(f"  {name:24s} {'IDENTICAL' if good else 'MISMATCH (' + md5 + ')'}")
    return ok


def summarize(rows):
    groups = {}
    for r in rows:
        key = (r["width"], r["spp"], r["depth"], r["objects"])
        groups.setdefault(key, {}).setdefault(r["name"], []).append(r["compute_s"])
    for key, names in groups.items():
        print(f"\nwidth={key[0]} spp={key[1]} depth={key[2]} objects={key[3]}")
        base = statistics.median(names["seq"]) if "seq" in names else None
        print(f"{'config':24s} {'n':>2s} {'median_s':>9s} {'speedup':>8s}")
        for name, vals in names.items():
            med = statistics.median(vals)
            sp = f"{base / med:8.2f}" if base else "     n/a"
            print(f"{name:24s} {len(vals):2d} {med:9.2f} {sp}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", required=True, choices=sorted(SUITES))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated substrings; keep configs whose name matches")
    ap.add_argument("--out", default="", help="CSV path (default results/<suite>.csv)")
    ap.add_argument("--width", type=int)
    ap.add_argument("--spp", type=int)
    ap.add_argument("--depth", type=int)
    ap.add_argument("--objects", type=int)
    ap.add_argument("--tile", type=int, default=64)
    ap.add_argument("--timeout", type=int, default=7200, help="seconds per run")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    base, make_jobs = SUITES[a.suite]
    base = dict(base)
    for k in ("width", "spp", "depth", "objects"):
        if getattr(a, k) is not None:
            base[k] = getattr(a, k)
    jobs = make_jobs(base)
    if a.only:
        keys = [s for s in a.only.split(",") if s]
        jobs = [(c, p) for c, p in jobs if any(k in c["name"] for k in keys)]
    if not jobs:
        sys.exit("no jobs selected")

    if a.dry_run:
        for c, p in jobs:
            print(" ".join(build_cmd(c, p, a.tile)))
        print(f"\n{len(jobs)} jobs x {a.repeats} repeats = {len(jobs) * a.repeats} runs")
        return

    missing = sorted({c["binary"] for c, _ in jobs if not os.path.exists(c["binary"])})
    if missing:
        sys.exit(f"missing binaries: {', '.join(missing)}  (run: make seq omp mpi hybrid)")

    if not a.no_verify and not verify(jobs, a.tile):
        sys.exit("verification failed; fix correctness before benchmarking")

    os.makedirs("results", exist_ok=True)
    path = a.out or f"results/{a.suite}.csv"
    new_file = not os.path.exists(path) or os.path.getsize(path) == 0
    rows, total, n = [], len(jobs) * a.repeats, 0
    print(f"\nSuite '{a.suite}': {len(jobs)} jobs x {a.repeats} repeats = {total} runs -> {path}")

    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        for rnd in range(1, a.repeats + 1):
            order = list(jobs)
            random.Random(1234 + rnd).shuffle(order)       # different order each round, reproducible
            for cfg, p in order:
                n += 1
                kv, wall, err = run_once(cfg, p, a.tile, a.timeout)
                if kv is None:
                    print(f"[{n}/{total}] round {rnd} {cfg['name']}: FAILED ({err})")
                    continue
                row = make_row(a.suite, rnd, cfg, p, kv, wall)
                w.writerow(row)
                f.flush()                                    # keep data if interrupted
                rows.append(row)
                print(f"[{n}/{total}] round {rnd} {cfg['name']:24s} width={p['width']} spp={p['spp']} "
                      f"depth={p['depth']} obj={p['objects']}  compute_s={row['compute_s']:.2f}")

    summarize(rows)
    print(f"\nCSV: {path}")


if __name__ == "__main__":
    main()
