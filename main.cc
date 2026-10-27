#include "rtweekend.h"

#include "camera.h"
#include "hittable_list.h"
#include "sphere.h"

#include <cstdlib>
#include <string>

static void build_scene(hittable_list& world, int num_objects, uint64_t seed) {
    // Fixed objects: ground and two feature spheres
    world.add(make_shared<sphere>(point3(0, -100.5, -1), 100, color(0.6, 0.6, 0.6), 0.1));
    world.add(make_shared<sphere>(point3(0.0, 0, -1.0), 0.5, color(0.8, 0.2, 0.2), 0.6));
    world.add(make_shared<sphere>(point3(1.2, 0, -1.5), 0.5, color(0.2, 0.3, 0.8), 0.3));

    // Random spheres, same every run for a given seed
    rng gen(seed);
    for (int n = 0; n < num_objects; n++) {
        double z  = -(2.0 + 12.0 * gen.uniform());        // depth in front of camera
        double x  = (gen.uniform() * 2 - 1) * (-z) * 1.4; // keep mostly inside the view
        double r  = 0.15 + 0.30 * gen.uniform();
        double cr = gen.uniform();
        double cg = gen.uniform();
        double cb = gen.uniform();
        double shiny = gen.uniform();
        double refl  = (shiny < 0.3) ? 0.5 + 0.3 * gen.uniform()    // 30% mirror-ish
                                     : 0.1 + 0.2 * gen.uniform();   // 70% mostly matte
        world.add(make_shared<sphere>(point3(x, -0.5 + r, z), r, color(cr, cg, cb), refl));
    }
}

int main(int argc, char** argv) {
    int width = 400, spp = 10, depth = 5, objects = 50;
    uint64_t seed = 42;

    for (int a = 1; a < argc; a++) {
        std::string arg = argv[a];
        if      (arg == "--width"   && a + 1 < argc) width   = std::atoi(argv[++a]);
        else if (arg == "--spp"     && a + 1 < argc) spp     = std::atoi(argv[++a]);
        else if (arg == "--depth"   && a + 1 < argc) depth   = std::atoi(argv[++a]);
        else if (arg == "--objects" && a + 1 < argc) objects = std::atoi(argv[++a]);
        else if (arg == "--seed"    && a + 1 < argc) seed    = std::strtoull(argv[++a], nullptr, 10);
        else { std::cerr << "Unknown or incomplete argument: " << arg << "\n"; return 1; }
    }

    hittable_list world;
    build_scene(world, objects, seed);

    camera cam;
    cam.aspect_ratio      = 16.0 / 9.0;
    cam.image_width       = width;
    cam.samples_per_pixel = spp;
    cam.max_depth         = depth;

    cam.lights.push_back({point3( 2, 3,  1), color(0.8, 0.8, 0.8)});
    cam.lights.push_back({point3(-3, 2,  0), color(0.4, 0.4, 0.4)});
    cam.lights.push_back({point3( 0, 5, -4), color(0.3, 0.3, 0.3)});

    cam.render(world);
}
