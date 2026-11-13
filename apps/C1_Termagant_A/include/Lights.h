#ifndef LIGHTS_H
#define LIGHTS_H

#include <stdint.h>

enum RGB {
    RED = 0x1,
    GREEN = 0x2,
    BLUE = 0x4
};

namespace Lights {
    void init();
    void set(RGB colors, bool state);
    void set(RGB colors, uint8_t intensity);
}

#endif // LIGHTS_H