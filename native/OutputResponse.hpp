#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace mkii::native {

// The fixed-step nodal solve attenuates the upper band more than the same
// circuit in continuous time. Calibrate the wet output against the deck's
// small-signal AC response, downstream of the detector and VCA.
class OutputResponse {
public:
    void prepare(double rate) {
        const auto upper=std::lower_bound(calibration.begin()+1,calibration.end()-1,rate,
                                         [](const auto& entry,double fs) {return entry.rate<fs;});
        const auto& low=*(upper-1);
        const auto mix=std::clamp((rate-low.rate)/(upper->rate-low.rate),0.0,1.0);
        b0=std::lerp(low.b0,upper->b0,mix);
        b1=std::lerp(low.b1,upper->b1,mix);
        a1=std::lerp(low.a1,upper->a1,mix);
        a2=std::lerp(low.a2,upper->a2,mix);
        b2=1+a1+a2-b0-b1; // Exact unity at DC.
        z1=z2=0;
    }

    double process(double input) {
        const double output=b0*input+z1;
        z1=b1*input-a1*output+z2;
        z2=b2*input-a2*output;
        return output;
    }

private:
    struct Fit {double rate,b0,b1,a1,a2;};
    // Stable high shelves fitted to measured native error at each rate.
    // Denominator interpolation preserves second-order stability.
    static constexpr std::array<Fit,6> calibration{{
        { 44100,1.13126808, 0.28053696, 0.40076049,0.10291232},
        { 48000,1.14051862, 0.24638881, 0.37846188,0.10819685},
        { 88200,1.16536720,-0.27690366,-0.07577895,0.14991704},
        { 96000,1.16331640,-0.34629237,-0.14273356,0.15688481},
        {176400,1.17461130,-0.67841384,-0.43882141,0.19919185},
        {192000,1.23117385,-0.66981148,-0.35761749,0.18792712},
    }};
    double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
};

}
