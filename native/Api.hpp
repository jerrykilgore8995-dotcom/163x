#pragma once

#include <cstdint>

namespace mkii::native {

struct Controls {
    float compression=0.45f, levelSet=0.5f;
    int detectorHpf=0;
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
constexpr std::uint32_t apiVersion=2;

// Allow one extra block at 512 for the brief extra work at sharp transients.
constexpr int playbackLatency(int hostBlock) {
    if (hostBlock<=128) return 512;
    if (hostBlock<=256) return 1024;
    if (hostBlock<=512) return 1536;
    if (hostBlock>=4096) return 8192;
    return 2*hostBlock;
}
// New Blackmer model has more transient work; reserve two Old transport windows.
constexpr int newPlaybackLatency(int hostBlock) {
    const int d=playbackLatency(hostBlock);
    return d<=4096 ? 2*d : d;
}
using LoadApi=const Api* (*)();

}
