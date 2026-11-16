#pragma once

#include <cstdint>

namespace mkii::native {

struct Controls {
    float compression=0.45f, levelSet=0.5f;
};

struct MeterReadings {
    float gainReductionDb=0, inputMeanSquare=0, outputMeanSquare=0;
    int aboveThreshold=0;
};

// Only POD values and opaque pointers cross the Windows compiler boundary.
struct Api {
    std::uint32_t version;
    int latency;
    void* (*create)();
    void (*destroy)(void*);
    int (*prepare)(void*,double,int,int);
    void (*stop)(void*);
    int (*process)(void*,float* const*,int,const Controls*,int,int);
    unsigned (*failedSolves)(void*);
    void (*readMeters)(void*,MeterReadings*);
};
constexpr std::uint32_t apiVersion=1;

// Keep one complete block of reserve after the block currently being filled.
constexpr int playbackLatency(int hostBlock) {
    if (hostBlock<=256) return 512;
    if (hostBlock>=4096) return 8192;
    return 2*hostBlock;
}
using LoadApi=const Api* (*)();

}
