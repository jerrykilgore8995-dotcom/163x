#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace mkii::native {

// Match the fixed-step OA3 output to the continuous-time deck.
// This correction runs downstream of the detector and VCA.
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
    // Stable biquads fitted to complex native/SPICE measurements at each rate.
    // Denominator interpolation preserves second-order stability.
    static constexpr std::array<Fit,6> calibration{{
        { 44100,1.01858080, 1.32021753, 1.30986773,0.35766443},
        { 48000,1.00680422, 1.48174872, 1.46395453,0.53030228},
        { 88200,1.00837084,-0.47186444,-0.45768561,0.64206676},
        { 96000,1.00693041,-0.68798251,-0.67284093,0.61340085},
        {176400,0.99996921,-1.12965262,-1.11920522,0.44059522},
        {192000,1.00012496,-1.12759612,-1.11591669,0.41602207},
    }};
    double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
};

}
