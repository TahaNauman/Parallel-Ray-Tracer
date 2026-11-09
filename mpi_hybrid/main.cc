#include <mpi.h>
#ifdef _OPENMP
#include <omp.h>
#endif

#include "rtweekend.h"
#include "camera.h"
#include "hittable_list.h"
#include "scene.h"

#include <fstream>
#include <algorithm>
#include <cstdlib>
#include <string>
#include <vector>

static_assert(sizeof(color) == 3 * sizeof(double), "color must be 3 packed doubles");

int main(int argc, char** argv) {
    int provided;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    int width = 400, spp = 10, depth = 5, objects = 50, threads = 0;
    uint64_t seed = 42;
    std::string out_path;

    // Every rank parses the same arguments
    for (int a = 1; a < argc; a++) {
        std::string arg = argv[a];
        if      (arg == "--width"   && a + 1 < argc) width   = std::atoi(argv[++a]);
        else if (arg == "--spp"     && a + 1 < argc) spp     = std::atoi(argv[++a]);
        else if (arg == "--depth"   && a + 1 < argc) depth   = std::atoi(argv[++a]);
        else if (arg == "--objects" && a + 1 < argc) objects = std::atoi(argv[++a]);
        else if (arg == "--seed"    && a + 1 < argc) seed    = std::strtoull(argv[++a], nullptr, 10);
        else if (arg == "--threads" && a + 1 < argc) threads = std::atoi(argv[++a]);
        else if (arg == "--out"     && a + 1 < argc) out_path = argv[++a];
        else {
            if (rank == 0) std::cerr << "Unknown or incomplete argument: " << arg << "\n";
            MPI_Finalize();
            return 1;
        }
    }

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

    // Static decomposition: contiguous row blocks, sizes differ by at most 1 row
    const int base = H / size, rem = H % size;
    const int my_rows = base + (rank < rem ? 1 : 0);
    const int my_y0   = rank * base + std::min(rank, rem);

    std::vector<color> tile(size_t(width) * my_rows);

    MPI_Barrier(MPI_COMM_WORLD);
    double t_start = MPI_Wtime();
    cam.render_tile(0, my_y0, width, my_rows, world, tile);   // global y keeps RNG seeds identical
    double my_compute = MPI_Wtime() - t_start;

    MPI_Barrier(MPI_COMM_WORLD);                  // wait for the slowest rank
    double compute_wall = MPI_Wtime() - t_start;  // time until every rank finished computing

    double cmax, cmin;
    MPI_Reduce(&my_compute, &cmax, 1, MPI_DOUBLE, MPI_MAX, 0, MPI_COMM_WORLD);
    MPI_Reduce(&my_compute, &cmin, 1, MPI_DOUBLE, MPI_MIN, 0, MPI_COMM_WORLD);

    std::vector<int> counts(size), displs(size);
    for (int r = 0; r < size; r++) {
        int rows_r = base + (r < rem ? 1 : 0);
        int y0_r   = r * base + std::min(r, rem);
        counts[r] = rows_r * width * 3;           // counted in doubles, not pixels
        displs[r] = y0_r * width * 3;
    }

    std::vector<color> full;
    if (rank == 0) full.resize(size_t(width) * H);

    double t_g0 = MPI_Wtime();
    MPI_Gatherv(reinterpret_cast<double*>(tile.data()), my_rows * width * 3, MPI_DOUBLE,
                reinterpret_cast<double*>(full.data()), counts.data(), displs.data(), MPI_DOUBLE,
                0, MPI_COMM_WORLD);
    double gather_s = MPI_Wtime() - t_g0;

    if (rank == 0) {
        double t_w0 = MPI_Wtime();
        if (out_path.empty()) {
            cam.output(std::cout, full);
        } 
        else {
            std::ofstream f(out_path, std::ios::binary);
            cam.output(f, full);
        }
        double write_s = MPI_Wtime() - t_w0;

        std::clog << "RESULT mode=static width=" << width << " height=" << H
                  << " spp=" << spp << " depth=" << depth
                  << " ranks=" << size << " threads=" << nthreads
                  << " compute_s=" << compute_wall
                  << " compute_max_s=" << cmax << " compute_min_s=" << cmin
                  << " gather_s=" << gather_s << " write_s=" << write_s << "\n";
    }

    MPI_Finalize();
    return 0;
}
