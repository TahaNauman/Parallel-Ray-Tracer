#include "rtweekend.h"

#include "camera.h"
#include "hittable_list.h"
#include "scene.h"

#ifdef _OPENMP
#include <omp.h>
#endif

#include <cstdlib>
#include <string>

int main(int argc, char** argv) {
    int width = 400, spp = 10, depth = 5, objects = 50, threads = 0;
    uint64_t seed = 42;

    for (int a = 1; a < argc; a++) {
        std::string arg = argv[a];
        if      (arg == "--width"   && a + 1 < argc) width   = std::atoi(argv[++a]);
        else if (arg == "--spp"     && a + 1 < argc) spp     = std::atoi(argv[++a]);
        else if (arg == "--depth"   && a + 1 < argc) depth   = std::atoi(argv[++a]);
        else if (arg == "--objects" && a + 1 < argc) objects = std::atoi(argv[++a]);
        else if (arg == "--seed"    && a + 1 < argc) seed    = std::strtoull(argv[++a], nullptr, 10);
        else if (arg == "--threads" && a + 1 < argc) threads = std::atoi(argv[++a]);
        else { std::cerr << "Unknown or incomplete argument: " << arg << "\n"; return 1; }
    }

#ifdef _OPENMP
    if (threads > 0) omp_set_num_threads(threads);
#endif

    hittable_list world;
    build_scene(world, objects, seed);

    camera cam;
    cam.aspect_ratio      = 16.0 / 9.0;
    cam.image_width       = width;
    cam.samples_per_pixel = spp;
    cam.max_depth         = depth;
    add_lights(cam);

    cam.render(world);
}
