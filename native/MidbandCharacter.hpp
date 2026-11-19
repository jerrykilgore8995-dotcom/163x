#pragma once
#include <array>
#include <cmath>
#include <algorithm>
#include <complex>
#include "Calibration.hpp"
#ifdef DBX_CHARACTER
#include "CharacterTable.hpp"
#endif
namespace mkii::native {
// Parallel harmonic-only midband character. No change to the nodal equations.
class MidbandCharacter {
    struct Band {
        double b=0,a1=0,a2=0,x1=0,x2=0,y1=0,y2=0;
        void prepare(double w){double a=std::sin(w)/(2*1.4);b=a/(1+a);a1=-2*std::cos(w)/(1+a);a2=(1-a)/(1+a);x1=x2=y1=y2=0;}
        double step(double x){double y=b*(x-x2)-a1*y1-a2*y2;x2=x1;x1=x;y2=y1;y1=y;return y;}
    };
    std::array<Band,3> bands;
    double previous=0,cs=0,sn=1,rate=44100;
public:
    void prepare(double fs){rate=fs;double w=6.283185307179586*1000/fs;cs=std::cos(w);sn=std::sin(w);for(auto& b:bands)b.prepare(w);previous=0;}
    double process(double input,double slider){
        double x=input;for(auto& b:bands)x=b.step(x);
        constexpr double ref=.199526231496888;
        std::complex<double> z(x/ref,(previous-cs*x)/(sn*ref));previous=x;
        // Bound the nonlinear branch at above-reference levels; do not clip dry audio.
        double mag=std::abs(z);if(mag>1.25)z*=1.25/mag;
#ifdef DBX_CHARACTER
        double pos=std::clamp(slider,0.,1.)*10;int i=std::min(9,int(pos));double t=pos-i;
        auto coeff=[&](int k){return std::complex<double>(std::lerp(characterTable[i][k*2],characterTable[i+1][k*2],t),std::lerp(characterTable[i][k*2+1],characterTable[i+1][k*2+1],t));};
        auto z2=z*z,z3=z2*z,z5=z3*z2;
        return std::real(coeff(0)*z2+coeff(1)*z3+coeff(2)*z5);
#else
        return 0;
#endif
    }
};
}
