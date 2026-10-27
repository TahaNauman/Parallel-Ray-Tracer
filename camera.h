#ifndef CAMERA_H
#define CAMERA_H

#include "hittable.h"

#include <chrono>
#include <vector>

struct point_light {
    point3 position;
    color intensity;
};

class camera {
  public:
    double aspect_ratio      = 1.0;
    int    image_width       = 100;
    int    samples_per_pixel = 10;
    int    max_depth         = 5;
    std::vector<point_light> lights;

    void render(const hittable& world) {
        using clock = std::chrono::steady_clock;
        initialize();

        std::vector<color> buffer(size_t(image_width) * image_height);

        auto t0 = clock::now();
        render_tile(0, 0, image_width, image_height, world, buffer);
        auto t1 = clock::now();
        write_image(std::cout, buffer);
        auto t2 = clock::now();

        double compute_s = std::chrono::duration<double>(t1 - t0).count();
        double write_s   = std::chrono::duration<double>(t2 - t1).count();
        std::clog << "RESULT width=" << image_width << " height=" << image_height
                  << " spp=" << samples_per_pixel << " depth=" << max_depth
                  << " compute_s=" << compute_s << " write_s=" << write_s << "\n";
    }

    // Renders the rectangle [x0, x0+w) x [y0, y0+h) into `tile`,
    // stored row-major with LOCAL indexing: tile[(j-y0)*w + (i-x0)].
    void render_tile(int x0, int y0, int w, int h,
                     const hittable& world, std::vector<color>& tile) const {
        for (int j = y0; j < y0 + h; j++) {
            for (int i = x0; i < x0 + w; i++) {
                rng gen(uint64_t(j) * image_width + i);   // seed depends only on the pixel
                color pixel_color(0, 0, 0);
                for (int s = 0; s < samples_per_pixel; s++) {
                    ray r = get_ray(i, j, gen);
                    pixel_color += ray_color(r, max_depth, world);
                }
                tile[size_t(j - y0) * w + (i - x0)] = pixel_samples_scale * pixel_color;
            }
        }
    }

  private:
    int    image_height;
    double pixel_samples_scale;
    point3 center;
    point3 pixel00_loc;
    vec3   pixel_delta_u;
    vec3   pixel_delta_v;

    void initialize() {
        image_height = int(image_width / aspect_ratio);
        image_height = (image_height < 1) ? 1 : image_height;
        pixel_samples_scale = 1.0 / samples_per_pixel;

        center = point3(0, 0, 0);

        auto focal_length = 1.0;
        auto viewport_height = 2.0;
        auto viewport_width = viewport_height * (double(image_width) / image_height);

        auto viewport_u = vec3(viewport_width, 0, 0);
        auto viewport_v = vec3(0, -viewport_height, 0);

        pixel_delta_u = viewport_u / image_width;
        pixel_delta_v = viewport_v / image_height;

        auto viewport_upper_left =
            center - vec3(0, 0, focal_length) - viewport_u / 2 - viewport_v / 2;
        pixel00_loc = viewport_upper_left + 0.5 * (pixel_delta_u + pixel_delta_v);
    }

    void write_image(std::ostream& out, const std::vector<color>& buffer) const {
        out << "P3\n" << image_width << ' ' << image_height << "\n255\n";
        for (const auto& c : buffer)
            write_color(out, c);
    }

    ray get_ray(int i, int j, rng& gen) const {
        double ox = gen.uniform() - 0.5;      // separate statements: C++ doesn't
        double oy = gen.uniform() - 0.5;      // guarantee argument evaluation order
        auto pixel_sample = pixel00_loc
                          + ((i + ox) * pixel_delta_u)
                          + ((j + oy) * pixel_delta_v);
        return ray(center, pixel_sample - center);
    }

    color ray_color(const ray& r, int depth, const hittable& world) const {
        if (depth <= 0)
            return color(0, 0, 0);

        hit_record rec;
        if (world.hit(r, interval(0.001, infinity), rec)) {
            color result = 0.1 * rec.albedo;

            for (const auto& light : lights) {
                vec3 to_light = light.position - rec.p;
                double dist = to_light.length();
                vec3 L = to_light / dist;

                ray shadow_ray(rec.p, L);
                hit_record shadow_rec;
                if (world.hit(shadow_ray, interval(0.001, dist), shadow_rec))
                    continue;

                double diffuse = std::fmax(0.0, dot(rec.normal, L));
                result += rec.albedo * light.intensity * diffuse;
            }

            if (rec.reflectivity > 0) {
                vec3 refl_dir = reflect(unit_vector(r.direction()), rec.normal);
                ray refl_ray(rec.p, refl_dir);
                color refl_color = ray_color(refl_ray, depth - 1, world);
                result = (1 - rec.reflectivity) * result + rec.reflectivity * refl_color;
            }
            return result;
        }

        vec3 unit_direction = unit_vector(r.direction());
        auto a = 0.5 * (unit_direction.y() + 1.0);
        return (1.0 - a) * color(1.0, 1.0, 1.0) + a * color(0.5, 0.7, 1.0);
    }
};

#endif
