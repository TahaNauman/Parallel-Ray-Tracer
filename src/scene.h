#ifndef SCENE_H
#define SCENE_H

#include "rtweekend.h"
#include "camera.h"
#include "hittable_list.h"
#include "sphere.h"

inline void build_scene(hittable_list& world, int num_objects, uint64_t seed) {
    // Fixed objects: ground and two feature spheres
    world.add(make_shared<sphere>(point3(0, -100.5, -1), 100, color(0.6, 0.6, 0.6), 0.1));
    world.add(make_shared<sphere>(point3(0.0, 0, -1.0), 0.5, color(0.8, 0.2, 0.2), 0.6));
    world.add(make_shared<sphere>(point3(1.2, 0, -1.5), 0.5, color(0.2, 0.3, 0.8), 0.3));

    // Random spheres, same every run for a given seed
    rng gen(seed);
    for (int n = 0; n < num_objects; n++) {
        double z  = -(2.0 + 12.0 * gen.uniform());
        double x  = (gen.uniform() * 2 - 1) * (-z) * 1.4;
        double r  = 0.15 + 0.30 * gen.uniform();
        double cr = gen.uniform();
        double cg = gen.uniform();
        double cb = gen.uniform();
        double shiny = gen.uniform();
        double refl  = (shiny < 0.3) ? 0.5 + 0.3 * gen.uniform()
                                     : 0.1 + 0.2 * gen.uniform();
        world.add(make_shared<sphere>(point3(x, -0.5 + r, z), r, color(cr, cg, cb), refl));
    }
}

inline void add_lights(camera& cam) {
    cam.lights.push_back({point3( 2, 3,  1), color(0.8, 0.8, 0.8)});
    cam.lights.push_back({point3(-3, 2,  0), color(0.4, 0.4, 0.4)});
    cam.lights.push_back({point3( 0, 5, -4), color(0.3, 0.3, 0.3)});
}

#endif
