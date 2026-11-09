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
