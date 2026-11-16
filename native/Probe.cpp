#include "Pipeline.hpp"
#include "PlaybackClock.hpp"

#include <chrono>
#include <cstdio>
#include <numbers>

namespace {
float signal(int sample,int channel,int rate) {
    const double t=double(sample)/rate;
    const double phase=2*std::numbers::pi*t;
    const double age=std::fmod(t,0.25);
    const double fast=0.11*std::exp(-13*age)*(std::sin(8127*phase+channel)
                                           +0.24*std::sin(15893*phase));
    return static_cast<float>(0.07*std::sin(83*phase)+0.06*std::sin(1877*phase)+fast);
}
}

int main() {
    constexpr int rate=44100, block=512;
    using Clock=mkii::native::PlaybackClock::Clock;
    bool okay=true;
    for (int channels : {1,2}) {
        mkii::native::Pipeline engine;
        if (!engine.prepare(rate,channels,mkii::native::playbackLatency(block))) return 2;
        std::array<std::array<float,block>,2> audio{};
        float* pointers[]={audio[0].data(),audio[1].data()};
        mkii::native::PlaybackClock clock;
        const auto start=Clock::now();
        double callbackPeak=0;
        for (int frame=0;frame<rate*8;frame+=block) {
            for (int c=0;c<channels;++c)
                for (int i=0;i<block;++i)
                    audio[c][i]=signal(frame+i,c,rate);
            clock.waitUntil(start+std::chrono::duration_cast<Clock::duration>(
                std::chrono::duration<double>(double(frame)/rate)));
            const auto before=Clock::now();
            engine.process(pointers,block,{});
            callbackPeak=std::max(callbackPeak,std::chrono::duration<double,std::milli>(Clock::now()-before).count());
        }
        std::printf("%d channels, 44.1 kHz, 512 samples: misses %llu, failed solves %u, "
                    "required delay %llu samples, longest callback %.3f ms\n",
                    channels,static_cast<unsigned long long>(engine.missedSamples()),engine.failedSolves(),
                    static_cast<unsigned long long>(engine.requiredDelaySamples()),callbackPeak);
        okay=!engine.missedSamples() && !engine.failedSolves() && callbackPeak<1000.*block/rate && okay;
    }
    return okay?0:3;
}
