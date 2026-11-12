# Project notes

## Machine
- Intel Core i5-1135G7 (4 cores / 8 threads, 2.4 GHz base, boosts to about 4.2 GHz), laptop
- Windows + WSL2 (Ubuntu), single node
- `lscpu` inside WSL reports 8 CPUs, 2 threads per core, 4 cores per socket

## Locked defaults (do not change the scene from here on)
- Width 1920 (1080p), SPP 16, depth 5, objects 100, seed 42
- Lights: 3 (fixed in main.cc)
- Compile flags: `-O2 -std=c++17` (no `-ffast-math`; `-fopenmp` is fine)
- Binaries: `raytracer_seq` (no -fopenmp), `raytracer_omp` (-fopenmp)

## Reference checksum (correctness check for all parallel versions)
- Args: `--width 400 --spp 10 --objects 100` (depth 5, seed 42)
- md5sum: `56b7db7050c821d9e94f209f381388ed`
- Every parallel version must reproduce this exactly (`cmp ref.ppm out.ppm`)

## Code changes per version
- **v1-sequential:** vec3.h, ray.h, color.h, interval.h, rtweekend.h (incl. per-pixel RNG), hittable.h, hittable_list.h, sphere.h, camera.h (`render_tile`, buffer, timing), main.cc (CLI, seeded scene)
- **v2-openmp:** only camera.h and main.cc changed
  - camera.h: `#include <omp.h>` (guarded by `_OPENMP`), `#pragma omp parallel for schedule(runtime)` above the row loop in `render_tile`, `threads=` added to the RESULT line
  - main.cc: guarded `omp.h` include, `--threads` argument, `omp_set_num_threads`
  - Scheduling is chosen at run time with `OMP_SCHEDULE`

## Sequential baselines
| width | spp | depth | objects | compute_s | write_s | note |
|---|---|---|---|---|---|---|
| 480  | 10 | 5 | 100 | 4.35 | 0.039 | |
| 480  | 10 | 5 | 100 | 4.44 | 0.025 | |
| 400  | 10 | 5 | 100 | 3.50 | 0.013 | |
| 400  | 10 | 5 | 100 | 3.16 | 0.015 | |
| 1920 | 16 | 5 | 100 | 113.0 | 0.33 | main baseline |
| 1920 | 4  | 5 | 100 | 31.36, 27.31, 29.09 | ~0.3-0.4 | batch A (median 29.09) |
| 1920 | 4  | 5 | 100 | 24.86, 26.00, 25.98 | ~0.3-0.5 | batch B (median 25.98) |
| 1920 | 4  | 5 | 100 | 26.10, 27.21, 28.12 | ~0.3-0.6 | batch C (median 27.21) |

## Calibration
- Cost is about 3.4 microseconds per sample (pixels x SPP)
- Time scales linearly with pixels and SPP (predicted 113 s for 1080p SPP 16, measured 113.0 s)
- Extrapolated sequential at SPP 16: 4K ~7.5 min, 8K ~30 min (not measured)

## Depth experiment (early scene: 3 spheres, SPP 10, 400 px wide)
| max_depth | real_s |
|---|---|
| 1 | 0.163 |
| 2 | 0.270 |
| 5 | 0.285 |
- Big jump from 1 to 2, then flat: most reflected rays reach the sky quickly
- To redo at proper scale (100 objects, 1080p) with the benchmark script

## OpenMP

### Correctness
- `cmp` against the reference: IDENTICAL for the sequential build and for the OpenMP build at 1, 2, 4, 8 threads
- Reason: each pixel has its own RNG seeded from its index, writes only its own buffer slot, and only reads the shared world and lights

### Scheduling comparison (batch A; 1080p, SPP 4, 4 threads; T_seq = 29.09 s)
| Policy | median compute_s | speedup | efficiency |
|---|---|---|---|
| static | 13.79 | 2.11x | 53% |
| static,1 | 11.18 | 2.60x | 65% |
| dynamic,1 | 10.08 | 2.89x | 72% |
| dynamic,4 | 10.38 | 2.80x | 70% |
| dynamic,16 | 10.25 | 2.84x | 71% |
| guided | 10.12 | 2.87x | 72% |
- static is clearly worst: contiguous row blocks give one thread the cheap sky rows and another the expensive ground and mirror rows
- dynamic (any chunk) and guided are indistinguishable (run-to-run spread is as large as the gaps); default choice: `dynamic,1`
- Chunk size does not matter because each row is coarse work

### Thread pinning (batch B; 1080p, SPP 4, 4 threads, dynamic,1; T_seq about 25.98 s)
| Config | median compute_s | speedup | efficiency |
|---|---|---|---|
| unpinned | 8.44 | 3.08x | 77% |
| pinned (`OMP_PLACES=cores OMP_PROC_BIND=close`) | 10.39 | 2.50x | 62% |
- Pinning made things worse; do not pin. Possible reason (untested): WSL2 virtual CPUs do not map onto physical cores, so pinning removes the scheduler's freedom without controlling real placement

### Hardware ceiling test (960 px wide, SPP 4)
- Solo sequential: 6.56 s, 6.86 s (median 6.71 s)
- 4 independent copies at once: 7.57, 7.62, 7.86, 7.98 s (median about 7.74 s)
- Each copy slowed about 1.15x, so the machine's best case on 4 cores is about 4 / 1.15 = 3.5x (clock, power, thermal limits)

### Thread sweep (batch C; 1080p, SPP 4, dynamic,1; T_seq = 27.21 s)
| Threads | runs (compute_s) | median | speedup | efficiency |
|---|---|---|---|---|
| 1 | 33.57, 36.07, 29.23 | 33.57 | n/a (noisy) | n/a |
| 2 | 14.85, 14.50, 16.89 | 14.85 | 1.83x | 92% |
| 3 | 11.25, 10.91, 11.11 | 11.11 | 2.45x | 82% |
| 4 | 9.72, 9.65, 9.57 | 9.65 | 2.82x | 70% |
| 5 | 8.86, 8.89, 11.33 | 8.89 | 3.06x | 61% |
| 6 | 9.66, 10.24, 10.03 | 10.03 | 2.71x | 45% |
| 7 | 9.03, 9.41, 12.01 | 9.41 | 2.89x | 41% |
| 8 | 9.93, 9.36, 8.57 | 9.36 | 2.91x | 36% |

### Findings
- Near-linear up to 3 threads (82% efficiency), then bends
- From 4 to 8 threads there is no real improvement (about 9 to 10 s throughout); the 5 vs 6 dip is within noise
- Hyperthreading gave almost no benefit here (interpretation, not measured)
- Reached about 2.8 to 3.1x against a hardware ceiling of about 3.5x, so roughly 80 to 90% of what the machine can do; the remainder could be end-of-loop imbalance, memory effects, or WSL scheduling (not separated)

## Caveats and measurement notes
- Absolute times drift between batches (sequential medians: 29.1, 26.0, 27.2 s); only compare numbers from the same batch
- Short runs are noisy (two identical 400 px runs differed by about 10%)
- 1-thread OpenMP runs were slower than sequential and very spread out (29.2 to 36.1 s); suspected noise or throttling, to be rerun
- One slow outlier each at 5 and 7 threads (11.3 s, 12.0 s); median handles it
- Benchmark each config 3 to 5 times, report the median; interleave configs in the final script so drift does not bias one of them
- Main sweeps at 1080p; 8K for only a few key configs
- Load is uneven across the image: sky rows are cheap, ground and mirror spheres are expensive

## MPI (static and master-worker)

### Correctness
- Static: IDENTICAL to reference at 1, 2, 3, 4, 8 ranks (225 rows, uneven blocks)
- Dynamic: IDENTICAL at 2, 3, 4, 5, 8 ranks with tiles 64 and 37 (edge tiles tested)
- Same scene on every rank from the same seed; render_tile uses global pixel coordinates, so RNG seeds match

### Design
- Static: contiguous row blocks per rank, MPI_Gatherv (counts in doubles), rank 0 writes the image
- Dynamic: rank 0 is a coordinator (hands out tile ids, copies results into the image), ranks 1.. render; -np N means N-1 workers
- Build: `make mpi` is pure MPI; `make hybrid` adds -fopenmp (same source file)
- Use `--out FILE` for benchmarks: writing through mpirun's stdout took 7.2 s vs 0.21 s to a file

### Interleaved comparison (1080p, SPP 4, 3 rounds, medians; seq = 26.29 s)
| Version | median compute_s | speedup | efficiency |
|---|---|---|---|
| OpenMP, 4 threads, dynamic,1 | 9.06 | 2.90x | 73% |
| MPI dynamic, 5 ranks (4 workers) | 10.04 | 2.62x | 65% |
| MPI static, 4 ranks | 15.29 | 1.72x | 43% |
- Static per-rank compute ranged from about 1.7 s to 15.1 s in every round (load imbalance, measured)
- Dynamic workers stayed within about 1% of each other
- Dynamic is 1.52x faster than static on the same four compute ranks
- Dynamic MPI is about 11% slower than OpenMP dynamic; cause not tested (coordinator polling, message size, tile granularity)
- Dynamic scaling: 3 workers 13.47 s, 4 workers 10.21 s (1.32x vs ideal 1.33x, single runs)

### Caveats
- Single-node shared-memory MPI: gather took 6.6 ms for about 50 MB, so communication is nearly free here; a real cluster would pay far more
- In dynamic mode gather_s = 0 because results arrive during the compute phase
- Tile-size sweep (16 to 270) and the mpi_yield_when_idle test were inconclusive: the same config varied 9.7 to 13.0 s across runs because of machine drift
- To settle the coordinator question: interleave default vs `--mca mpi_yield_when_idle 1`, 3 rounds

## TODO (updated)
- [x] Static MPI, master-worker MPI
- [ ] Hybrid: `make hybrid`, correctness first, then ranks x threads matrix (set OMP_SCHEDULE=dynamic,1; keep ranks x threads <= 8)
- [ ] Optional: coordinator yield test
- [ ] Understanding answers (pixel seed, render_tile shape, separate timing, static vs dynamic)
- [ ] Benchmark script and graphs (Week 12)

## Main suite (scripts/bench.py --suite main --repeats 3)
1080p, SPP 16, depth 5, 100 objects, seed 42. Interleaved runs in shuffled order, all binaries verified
IDENTICAL to the reference first. Speedup is against the seq median 99.66 s (seq runs: 105.4, 92.0, 99.7).
Efficiency = speedup / compute threads or ranks. The measured hardware ceiling is about 3.5x.

| Config | median compute_s | speedup | efficiency |
|---|---|---|---|
| seq | 99.66 | 1.00 | |
| omp 1 thread | 93.63 | 1.06 | |
| omp 2 threads | 52.83 | 1.89 | 94% |
| omp 3 threads | 44.73 | 2.23 | 74% |
| omp 4 threads | 38.55 | 2.58 | 65% |
| omp 6 threads | 34.42 | 2.90 | 48% |
| omp 8 threads | 33.03 | 3.02 | 38% |
| mpi static 1 rank | 95.59 | 1.04 | |
| mpi static 2 ranks | 90.93 | 1.10 | 55% |
| mpi static 4 ranks | 65.73 | 1.52 | 38% |
| mpi static 8 ranks | 71.36 | 1.40 | 17% |
| mpi dynamic 1 worker | 110.12 | 0.91 | |
| mpi dynamic 2 workers | 67.34 | 1.48 | 74% |
| mpi dynamic 4 workers | 46.10 | 2.16 | 54% |
| mpi dynamic 8 workers | 38.23 | 2.61 | 33% |
| hybrid static 1x8 | 32.71 | 3.05 | 38% |
| hybrid static 2x4 | 40.54 | 2.46 | 31% |
| hybrid static 4x2 | 44.25 | 2.25 | 28% |
| hybrid static 8x1 | 57.76 | 1.73 | 22% |
| hybrid dynamic 1x8 | 39.15 | 2.55 | 32% |
| hybrid dynamic 2x4 | 37.20 | 2.68 | 33% |
| hybrid dynamic 4x2 | 38.80 | 2.57 | 32% |
| hybrid dynamic 8x1 | 36.96 | 2.70 | 34% |
(dynamic configs use one extra coordinator rank; hybrid efficiency is against 8 logical threads but there are only 4 physical cores)

### Findings
- OpenMP: near-linear to 2 threads, flat beyond 6; hyperthreads add nothing; 1-thread overhead negligible (93.6 s vs seq 99.7 s)
- Static MPI is poor and 8 ranks is worse than 4: the cheap sky rows leave one rank with most of the work
- Dynamic vs static on the same compute ranks: 1.35x (2), 1.43x (4), 1.87x (8); the advantage grows with ranks
- MPI dynamic is about 20% slower than OpenMP at 4 compute processes (19%, 30%, 23% in the three rounds); cause untested
- MPI dynamic with 1 worker is slower than seq (0.91x); overhead of the tile machinery, cause untested
- Hybrid static improves as ranks drop (3.05x at 1x8 down to 1.73x at 8x1); interpretation: OpenMP dynamic scheduling balances inside each rank
- Hybrid dynamic is flat across rank x thread splits (differences are noise) and 12-19% behind omp 8 threads
- Best configs on this machine: omp 8 threads and hybrid static 1x8 (same thing); MPI adds nothing on one node

### Caveats
- Drift: round 3 was slower for many configs (omp-t4 35.4 s to 46.2 s); 3 repeats cannot separate gaps under about 10%
- Seq baseline spread is 92 to 105 s, so absolute speedups carry about +/-7%; ratios between parallel configs are firmer

## Resolution suite (SPP 4, 3 rounds; best-of-3 / median, seconds)
| width | seq | omp-t4 | mpi-dynamic-w4 |
|---|---|---|---|
| 1280 | 12.11 / 12.91 | 4.66 / 5.42 | 4.75 / 6.17 |
| 1920 | 28.20 / 33.67 | 9.70 / 9.99 | 10.57 / 11.64 |
| 3840 | 109.92 / 115.91 | 38.95 / 39.67 | 44.82 / 47.43 |
- Seconds per megapixel (best-of-3): seq 13.1, 13.6, 13.3; omp 5.1, 4.7, 4.7; mpi 5.2, 5.1, 5.4 -> time is linear in pixel count
- Speedup (best-of-3) omp 2.6x, 2.9x, 2.8x; mpi dynamic 2.5x, 2.7x, 2.5x: independent of resolution
- Median-based speedups are distorted by noise (seq 1920 ranged 28.2 to 44.5 s); report best-of-3 alongside medians
- MPI dynamic 9-15% behind OpenMP (best-of-3), 17-20% (median); consistent with the main suite

## Complexity suite (960 px, sequential best-of-3 / median, seconds)
- SPP 1/4/16/64: 1.51/1.95, 6.27/6.64, 24.78/33.10, 97.30/127.79 -> linear (x4.15, x3.95, x3.93)
- Depth 1/2/3/5/8: 12.61/16.30, 18.91/25.61, 22.09/28.03, 24.78/33.10, 24.68/33.63 -> saturates after about 5
- Objects 10/50/100/200: 3.89/5.09, 12.72/19.10, 24.78/33.10, 47.81/49.79 -> linear, about 0.24 s per object (brute-force intersection)
- Parallel speedup (omp-t4, mpi-dynamic-w4) ranged 2.0x to 3.3x across points by medians, no clear trend; noise dominates
- Same seq config varied up to 46% between rounds (24.8 to 36.2 s)
