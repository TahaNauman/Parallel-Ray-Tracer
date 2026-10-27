# Project notes

## Locked defaults (do not change the scene from here on)
- Width 1920 (1080p), SPP 16, depth 5, objects 100, seed 42
- Lights: 3 (fixed in main.cc)
- Compile: g++ -O2 -std=c++17 (no -ffast-math; -fopenmp is fine)

## Reference checksum (correctness check for all parallel versions)
- Args: --width 400 --spp 10 --objects 100 (depth 5, seed 42)
- md5sum: 56b7db7050c821d9e94f209f381388ed
- Every parallel version must reproduce this exactly (check with cmp or md5sum)

## Sequential baseline (v1-sequential)
| width | spp | depth | objects | compute_s | write_s |
|---|---|---|---|---|---|
| 480  | 10 | 5 | 100 | 4.35 | 0.039 |
| 480  | 10 | 5 | 100 | 4.44 | 0.025 |
| 400  | 10 | 5 | 100 | 3.50 | 0.013 |
| 400  | 10 | 5 | 100 | 3.16 | 0.015 |
| 1920 | 16 | 5 | 100 | 113.0 | 0.33 |

## Calibration
- Cost is about 3.4 microseconds per sample (pixels x SPP)
- Time scales linearly with pixels and SPP (predicted 113 s for 1080p, measured 113.0 s)
- Extrapolated sequential at SPP 16: 4K ~7.5 min, 8K ~30 min

## Depth experiment (early scene, 3 spheres, SPP 10)
| max_depth | real_s |
|---|---|
| 1 | 0.163 |
| 2 | 0.270 |
| 5 | 0.285 |
- Big jump from 1 to 2, then flat: most reflected rays reach the sky quickly

## Observations for the report
- Short runs (under a few seconds) are noisy: two identical 400 px runs differed by ~10%
- Benchmark each config 3-5 times, take the median or minimum
- Main sweeps at 1080p; 8K for only a few key configs
- Load is uneven: sky rows are cheap, ground and mirror spheres are expensive
  (this is why dynamic scheduling should beat static)
- user ~ real in sequential runs, confirming one core
