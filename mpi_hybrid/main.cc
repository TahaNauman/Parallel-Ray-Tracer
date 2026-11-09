#include <mpi.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#include "rtweekend.h"
#include "camera.h"
#include "hittable_list.h"
#include "scene.h"

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <string>
#include <vector>

static_assert(sizeof(color) == 3 * sizeof(double), "color must be 3 packed doubles");

enum { TAG_WORK = 1, TAG_RESULT = 2 };

struct tile_geom { int x0, y0, w, h; };

// Tile `id` of a W x H image cut into T x T tiles, numbered row-major.
static tile_geom get_tile(int id, int W, int H, int T) {
    int ntx = (W + T - 1) / T;
    tile_geom g;
    g.x0 = (id % ntx) * T;
    g.y0 = (id / ntx) * T;
    g.w  = std::min(T, W - g.x0);
    g.h  = std::min(T, H - g.y0);
    return g;
}

int main(int argc, char** argv) {
    int provided;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    int width = 400, spp = 10, depth = 5, objects = 50, threads = 0, tile_size = 64;
    uint64_t seed = 42;
    std::string out_path;            // empty = write to stdout
    std::string mode = "static";     // static | dynamic

    // Every rank parses the same arguments
    for (int a = 1; a < argc; a++) {
        std::string arg = argv[a];
        if      (arg == "--width"   && a + 1 < argc) width     = std::atoi(argv[++a]);
        else if (arg == "--spp"     && a + 1 < argc) spp       = std::atoi(argv[++a]);
        else if (arg == "--depth"   && a + 1 < argc) depth     = std::atoi(argv[++a]);
        else if (arg == "--objects" && a + 1 < argc) objects   = std::atoi(argv[++a]);
        else if (arg == "--seed"    && a + 1 < argc) seed      = std::strtoull(argv[++a], nullptr, 10);
        else if (arg == "--threads" && a + 1 < argc) threads   = std::atoi(argv[++a]);
        else if (arg == "--tile"    && a + 1 < argc) tile_size = std::atoi(argv[++a]);
        else if (arg == "--mode"    && a + 1 < argc) mode      = argv[++a];
        else if (arg == "--out"     && a + 1 < argc) out_path  = argv[++a];
        else {
            if (rank == 0) std::cerr << "Unknown or incomplete argument: " << arg << "\n";
            MPI_Finalize();
            return 1;
        }
    }
    if (mode != "static" && mode != "dynamic") {
        if (rank == 0) std::cerr << "--mode must be static or dynamic\n";
        MPI_Finalize();
        return 1;
    }
    if (tile_size < 1) tile_size = 1;

    int nthreads = 1;
#ifdef _OPENMP
    if (threads > 0) omp_set_num_threads(threads);
    nthreads = omp_get_max_threads();
#endif

    // Every rank builds the identical scene from the same seed; nothing is sent over MPI
    hittable_list world;
    build_scene(world, objects, seed);

    camera cam;
    cam.aspect_ratio      = 16.0 / 9.0;
    cam.image_width       = width;
    cam.samples_per_pixel = spp;
    cam.max_depth         = depth;
    add_lights(cam);
    cam.prepare();
    const int H = cam.height();

    std::vector<color> full;
    if (rank == 0) full.resize(size_t(width) * H);

    double compute_wall = 0, cmax = 0, cmin = 0, gather_s = 0;

    if (mode == "static") {
        // Contiguous row blocks, sizes differ by at most 1 row
        const int base = H / size, rem = H % size;
        const int my_rows = base + (rank < rem ? 1 : 0);
        const int my_y0   = rank * base + std::min(rank, rem);

        std::vector<color> tile(size_t(width) * my_rows);

        MPI_Barrier(MPI_COMM_WORLD);
        double t_start = MPI_Wtime();
        cam.render_tile(0, my_y0, width, my_rows, world, tile);
        double my_compute = MPI_Wtime() - t_start;
        MPI_Barrier(MPI_COMM_WORLD);
        compute_wall = MPI_Wtime() - t_start;

        MPI_Reduce(&my_compute, &cmax, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);
        MPI_Reduce(&my_compute, &cmin, 1, MPI_DOUBLE, MPI_MIN, 0, MPI_COMM_WORLD);

        std::vector<int> counts(size), displs(size);
        for (int r = 0; r < size; r++) {
            int rows_r = base + (r < rem ? 1 : 0);
            int y0_r   = r * base + std::min(r, rem);
            counts[r] = rows_r * width * 3;      // counted in doubles, not pixels
            displs[r] = y0_r * width * 3;
        }

        double t_g0 = MPI_Wtime();
        MPI_Gatherv(reinterpret_cast<double*>(tile.data()), my_rows * width * 3, MPI_DOUBLE,
                    reinterpret_cast<double*>(full.data()), counts.data(), displs.data(), MPI_DOUBLE,
                    0, MPI_COMM_WORLD);
        gather_s = MPI_Wtime() - t_g0;
    } else {
        // Master-worker: rank 0 hands out tile ids, ranks 1.. render
        if (size < 2) {
            if (rank == 0) std::cerr << "dynamic mode needs at least 2 ranks (1 coordinator + workers)\n";
            MPI_Finalize();
            return 1;
        }
        const int ntiles = ((width + tile_size - 1) / tile_size) * ((H + tile_size - 1) / tile_size);
        double my_busy = 0.0;   // worker time spent rendering and sending

        MPI_Barrier(MPI_COMM_WORLD);
        double t_start = MPI_Wtime();

        if (rank == 0) {
            std::vector<int> assigned(size, -1);                     // tile each worker is working on
            std::vector<double> rbuf(size_t(tile_size) * tile_size * 3);
            int next_tile = 0, active = 0;

            for (int w = 1; w < size; w++) {                         // first tile for every worker
                int id = (next_tile < ntiles) ? next_tile++ : -1;
                assigned[w] = id;
                MPI_Send(&id, 1, MPI_INT, w, TAG_WORK, MPI_COMM_WORLD);
                if (id >= 0) active++;
            }
            while (active > 0) {
                MPI_Status st;
                MPI_Recv(rbuf.data(), int(rbuf.size()), MPI_DOUBLE, MPI_ANY_SOURCE,
                         TAG_RESULT, MPI_COMM_WORLD, &st);
                int src = st.MPI_SOURCE;
                tile_geom g = get_tile(assigned[src], width, H, tile_size);
                const color* px = reinterpret_cast<const color*>(rbuf.data());
                for (int r = 0; r < g.h; r++)                        // copy tile rows into the image
                    std::copy(px + size_t(r) * g.w, px + size_t(r + 1) * g.w,
                              full.begin() + size_t(g.y0 + r) * width + g.x0);

                int id = (next_tile < ntiles) ? next_tile++ : -1;
                assigned[src] = id;
                MPI_Send(&id, 1, MPI_INT, src, TAG_WORK, MPI_COMM_WORLD);
                if (id < 0) active--;
            }
        } else {
            std::vector<color> tile;
            while (true) {
                int id;
                MPI_Recv(&id, 1, MPI_INT, 0, TAG_WORK, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
                if (id < 0) break;
                tile_geom g = get_tile(id, width, H, tile_size);
                tile.resize(size_t(g.w) * g.h);
                double t0 = MPI_Wtime();
                cam.render_tile(g.x0, g.y0, g.w, g.h, world, tile);
                MPI_Send(tile.data(), g.w * g.h * 3, MPI_DOUBLE, 0, TAG_RESULT, MPI_COMM_WORLD);
                my_busy += MPI_Wtime() - t0;
            }
        }

        MPI_Barrier(MPI_COMM_WORLD);
        compute_wall = MPI_Wtime() - t_start;

        // Busy-time spread across workers only (the coordinator is excluded)
        double busy_max = (rank == 0) ? 0.0   : my_busy;
        double busy_min = (rank == 0) ? 1e300 : my_busy;
        MPI_Reduce(&busy_max, &cmax, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);
        MPI_Reduce(&busy_min, &cmin, 1, MPI_DOUBLE, MPI_MIN, 0, MPI_COMM_WORLD);
    }

    if (rank == 0) {
        double t_w0 = MPI_Wtime();
        if (out_path.empty()) {
            cam.output(std::cout, full);
        } else {
            std::ofstream f(out_path, std::ios::binary);
            cam.output(f, full);
        }
        double write_s = MPI_Wtime() - t_w0;

        std::clog << "RESULT mode=" << mode << " width=" << width << " height=" << H
                  << " spp=" << spp << " depth=" << depth
                  << " ranks=" << size << " threads=" << nthreads
                  << " tile=" << (mode == "dynamic" ? tile_size : 0)
                  << " compute_s=" << compute_wall
                  << " compute_max_s=" << cmax << " compute_min_s=" << cmin
                  << " gather_s=" << gather_s << " write_s=" << write_s << "\n";
    }

    MPI_Finalize();
    return 0;
}
