#!/usr/bin/env python3
"""Make summary tables and figures from results/*.csv (run from the project root).

    python3 scripts/plot.py

Reads main.csv, resolution.csv, complexity.csv and big.csv (whichever exist) and writes
results/summary.csv plus results/fig_*.png. Speedup is always against the sequential
run of the same suite and parameters. Both the median and the best of the repeats are
used, because short runs on this laptop drift by up to ~40% between rounds.
"""
import csv
import os
import statistics
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")                      # no display needed (WSL)
import matplotlib.pyplot as plt

RES = "results"
HW_CEILING = 3.5     # speedup limit measured with 4 concurrent sequential copies (see NOTES.md)
INT_COLS = ["round", "ranks", "workers", "threads", "tile", "width", "height", "spp", "depth", "objects"]
FLOAT_COLS = ["compute_s", "compute_max_s", "compute_min_s", "gather_s", "write_s", "wall_s"]
MAIN = ("main", 1920, 16, 5, 100)          # suite, width, spp, depth, objects


# ---------- loading and statistics ----------
def load(name):
    path = f"{RES}/{name}.csv"
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            for k in INT_COLS:
                r[k] = int(r[k])
            for k in FLOAT_COLS:
                r[k] = float(r[k])
            rows.append(r)
    return rows


def stats(rows):
    """key = (suite, width, spp, depth, objects, config name) -> summary dict."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["suite"], r["width"], r["spp"], r["depth"], r["objects"], r["name"])].append(r)
    out = {}
    for k, rs in groups.items():
        v = [r["compute_s"] for r in rs]
        out[k] = dict(n=len(v), med=statistics.median(v), best=min(v), worst=max(v),
                      cmax=statistics.median([r["compute_max_s"] for r in rs]),
                      cmin=statistics.median([r["compute_min_s"] for r in rs]),
                      units=rs[0]["workers"] * rs[0]["threads"])   # compute threads in use
    return out


def write_summary(st, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["suite", "width", "spp", "depth", "objects", "config", "n", "median_s", "best_s",
                    "worst_s", "compute_units", "speedup_median", "speedup_best",
                    "efficiency_median", "efficiency_best"])
        for k in sorted(st):
            s = st[k]
            base = st.get(k[:5] + ("seq",))
            if base:
                sm, sb = base["med"] / s["med"], base["best"] / s["best"]
                row = [f"{sm:.3f}", f"{sb:.3f}", f"{sm / s['units']:.3f}", f"{sb / s['units']:.3f}"]
            else:
                row = ["", "", "", ""]
            w.writerow(list(k) + [s["n"], f"{s['med']:.3f}", f"{s['best']:.3f}", f"{s['worst']:.3f}",
                                  s["units"]] + row)


def save(fig, name):
    path = f"{RES}/fig_{name}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path)


def grouped(ax, labels, series):
    """Grouped bar chart: series = {legend name: [value or None per label]}."""
    n = len(series)
    w = 0.8 / n
    for i, (name, vals) in enumerate(series.items()):
        xs = [j - 0.4 + w * (i + 0.5) for j in range(len(labels))]
        ax.bar(xs, [v if v is not None else 0 for v in vals], w, label=name)
        for x, v in zip(xs, vals):
            if v is not None:
                ax.text(x, v, f"{v:.2f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels)
    top = max([v for vals in series.values() for v in vals if v is not None] or [1])
    ax.set_ylim(0, top * 1.35)                      # room for the legend above the bars


def legend_top(ax):
    ax.legend(fontsize=8, loc="upper center", ncol=2, frameon=False)


# ---------- figures ----------
def plot_omp(st):
    base = st.get(MAIN + ("seq",))
    if not base:
        return
    xs, med, best = [], [], []
    for t in (1, 2, 3, 4, 6, 8):
        s = st.get(MAIN + (f"omp-t{t}",))
        if s:
            xs.append(t)
            med.append(base["med"] / s["med"])
            best.append(base["best"] / s["best"])
    if not xs:
        return
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot([1, 8], [1, 8], "k--", lw=1, label="ideal")
    ax.axhline(HW_CEILING, color="gray", ls=":", label=f"4-copy hardware ceiling (~{HW_CEILING}x)")
    ax.plot(xs, med, "o-", label="median of runs")
    ax.plot(xs, best, "s--", label="best of runs")
    ax.axvline(4, color="lightgray", lw=0.8)
    ax.text(4.1, 1.0, "4 physical cores", fontsize=8, color="gray")
    ax.set_xlabel("OpenMP threads")
    ax.set_ylabel("speedup vs sequential")
    ax.set_title("OpenMP speedup (1080p, SPP 16)")
    ax.legend(fontsize=8)
    save(fig, "openmp_speedup")


def plot_mpi(st):
    base = st.get(MAIN + ("seq",))
    if not base:
        return
    ns = (1, 2, 4, 8)

    def sp(name):
        s = st.get(MAIN + (name,))
        return base["med"] / s["med"] if s else None

    series = {"MPI static (n ranks)": [sp(f"mpi-static-n{n}") for n in ns],
              "MPI dynamic (n workers + coordinator)": [sp(f"mpi-dynamic-w{n}") for n in ns],
              "OpenMP (n threads)": [sp(f"omp-t{n}") for n in ns]}
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    grouped(ax, [str(n) for n in ns], series)
    ax.set_xlabel("compute processes / threads")
    ax.set_ylabel("speedup vs sequential (median)")
    ax.set_title("Static vs dynamic load balancing (1080p, SPP 16)")
    legend_top(ax)
    save(fig, "static_vs_dynamic")


def plot_imbalance(st):
    items = [("static 2", "mpi-static-n2"), ("static 4", "mpi-static-n4"), ("static 8", "mpi-static-n8"),
             ("dynamic 2", "mpi-dynamic-w2"), ("dynamic 4", "mpi-dynamic-w4"), ("dynamic 8", "mpi-dynamic-w8")]
    labels, fast, slow = [], [], []
    for lab, name in items:
        s = st.get(MAIN + (name,))
        if s:
            labels.append(lab)
            fast.append(s["cmin"])
            slow.append(s["cmax"])
    if not labels:
        return
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    grouped(ax, labels, {"fastest process": fast, "slowest process": slow})
    ax.set_xlabel("MPI mode and number of compute processes")
    ax.set_ylabel("compute time per process (s, median)")
    ax.set_title("Load imbalance: per-process compute time (1080p, SPP 16)")
    legend_top(ax)
    save(fig, "load_imbalance")


def plot_hybrid(st):
    base = st.get(MAIN + ("seq",))
    if not base:
        return
    splits = [(1, 8), (2, 4), (4, 2), (8, 1)]

    def sp(kind, n, t):
        s = st.get(MAIN + (f"hybrid-{kind}-{n}x{t}",))
        return base["med"] / s["med"] if s else None

    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    grouped(ax, [f"{n}x{t}" for n, t in splits],
            {"hybrid static (ranks x threads)": [sp("static", n, t) for n, t in splits],
             "hybrid dynamic (workers x threads)": [sp("dynamic", n, t) for n, t in splits]})
    o8 = st.get(MAIN + ("omp-t8",))
    if o8:
        ax.axhline(base["med"] / o8["med"], color="k", ls="--", lw=1, label="OpenMP, 8 threads")
    ax.set_xlabel("MPI processes x OpenMP threads (8 compute threads in total)")
    ax.set_ylabel("speedup vs sequential (median)")
    ax.set_title("Hybrid MPI + OpenMP configurations (1080p, SPP 16)")
    legend_top(ax)
    save(fig, "hybrid")


def plot_overview(st):
    base = st.get(MAIN + ("seq",))
    if not base:
        return
    names = [("OpenMP 4 thr", "omp-t4"), ("OpenMP 8 thr", "omp-t8"), ("MPI static 4", "mpi-static-n4"),
             ("MPI dynamic 4w", "mpi-dynamic-w4"), ("Hybrid static 1x8", "hybrid-static-1x8"),
             ("Hybrid dynamic 2x4", "hybrid-dynamic-2x4")]
    med, best, labels = [], [], []
    for lab, name in names:
        s = st.get(MAIN + (name,))
        if s:
            labels.append(lab)
            med.append(base["med"] / s["med"])
            best.append(base["best"] / s["best"])
    if not labels:
        return
    fig, ax = plt.subplots(figsize=(9, 4.4))
    grouped(ax, labels, {"median of runs": med, "best of runs": best})
    ax.set_ylabel("speedup vs sequential")
    ax.set_title("All versions, key configurations (1080p, SPP 16)")
    legend_top(ax)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    save(fig, "overview")


def plot_resolution(st):
    series = defaultdict(dict)
    for (suite, w, spp, d, o, name), s in st.items():
        if suite in ("resolution", "big") and (spp, d, o) == (4, 5, 100):
            series[name][w] = (s["best"], suite)
    series = {k: v for k, v in series.items() if len(v) >= 2}
    if not series:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    for name, pts in sorted(series.items()):
        ws = sorted(pts)
        mp = [w * int(w / (16.0 / 9.0)) / 1e6 for w in ws]            # megapixels
        t = [pts[w][0] for w in ws]
        line, = a1.plot(mp, t, "o-", label=name)
        a2.plot(ws, [ti / m for ti, m in zip(t, mp)], "o-", color=line.get_color(), label=name)
        for w, m, ti in zip(ws, mp, t):
            if pts[w][1] == "big":                                       # 8K: different session
                a1.plot(m, ti, "o", mfc="white", color=line.get_color(), ms=10)
                a2.plot(w, ti / m, "o", mfc="white", color=line.get_color(), ms=10)
    a1.set_xscale("log")
    a1.set_yscale("log")
    a1.set_xlabel("megapixels")
    a1.set_ylabel("best compute time (s)")
    a1.set_title("Time vs image size (SPP 4)")
    a1.legend(fontsize=8)
    a2.set_xlabel("image width (px)")
    a2.set_ylabel("best compute time per megapixel (s)")
    a2.set_title("Flat line = linear scaling in pixels")
    a2.set_ylim(bottom=0)
    fig.text(0.5, 0.005, "hollow markers: 8K runs from a separate session (machine speed drifts between sessions)",
             ha="center", fontsize=8, color="gray")
    save(fig, "resolution")


def plot_complexity(st):
    base = dict(width=960, spp=16, depth=5, objects=100)
    sweeps = [("spp", "samples per pixel"), ("depth", "max reflection depth"), ("objects", "random spheres")]
    names = ["seq", "omp-t4", "mpi-dynamic-w4"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    drew = False
    for ax, (key, label) in zip(axes, sweeps):
        for name in names:
            pts = []
            for (suite, w, spp, d, o, nm), s in st.items():
                if suite != "complexity" or nm != name:
                    continue
                p = dict(width=w, spp=spp, depth=d, objects=o)
                if all(p[k] == base[k] for k in base if k != key):
                    pts.append((p[key], s["best"]))
            pts.sort()
            if pts:
                ax.plot(*zip(*pts), "o-", label=name)
                drew = True
        if key == "spp":
            ax.set_xscale("log")
            ax.set_yscale("log")
        ax.set_xlabel(label)
        ax.set_ylabel("best compute time (s)")
        ax.legend(fontsize=8)
    if drew:
        fig.suptitle("Complexity scaling (960 px wide; other parameters at default)")
        save(fig, "complexity")
    else:
        plt.close(fig)


def plot_big(st):
    rows = [(k[5], s, k) for k, s in st.items() if k[0] == "big"]
    if not rows:
        return
    base = next((s for n, s, _ in rows if n == "seq"), None)
    rows.sort(key=lambda r: -r[1]["med"])
    _, _, k0 = rows[0]
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    for i, (n, s, _) in enumerate(rows):
        ax.bar(i, s["med"], yerr=[[s["med"] - s["best"]], [s["worst"] - s["med"]]], capsize=4)
        label = f"{s['med']:.0f} s" + (f"\n{base['med'] / s['med']:.2f}x" if base else "")
        ax.text(i, s["worst"] * 1.01, label, ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([n for n, _, _ in rows], rotation=20, ha="right")
    ax.set_ylim(0, max(s["worst"] for _, s, _ in rows) * 1.18)
    ax.set_ylabel("compute time (s); bar = median, whiskers = min..max")
    ax.set_title(f"8K ({k0[1]} px wide), SPP {k0[2]}, speedup vs sequential")
    save(fig, "big_8k")


def main():
    rows = []
    for name in ("main", "resolution", "complexity", "big"):
        rows += load(name)
    if not rows:
        sys.exit("no CSV files found in results/ (run scripts/bench.py first)")
    st = stats(rows)
    write_summary(st, f"{RES}/summary.csv")
    print(f"wrote {RES}/summary.csv ({len(st)} configurations)")
    for fn in (plot_omp, plot_mpi, plot_imbalance, plot_hybrid, plot_overview,
               plot_resolution, plot_complexity, plot_big):
        fn(st)


if __name__ == "__main__":
    main()
