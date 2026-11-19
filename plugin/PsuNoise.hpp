#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <algorithm>
#include "../native/Calibration.hpp"
namespace mkii {
struct PsuNoise {
    struct Filter {
        double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
        void prepare(double rate,double hz,bool high) {
            const double w=6.283185307179586*std::min(hz,rate*.49)/rate;
            const double c=std::cos(w),a=std::sin(w)/std::sqrt(2.0),d=1+a;
            b0=(high?1+c:1-c)/(2*d);b1=(high?-2:2)*b0;b2=b0;
            a1=-2*c/d;a2=(1-a)/d;z1=z2=0;
        }
        double step(double x) {const double y=b0*x+z1;z1=b1*x-a1*y+z2;z2=b2*x-a2*y;return y;}
    };
    struct Voice {
        Filter hp,lp;std::uint32_t seed=1;
        std::array<double,7> b{};
        double pink() {
            auto& x=seed;x^=x<<13;x^=x>>17;x^=x<<5;
            const double w=double(x)/2147483648.-1.;
            b[0]=.99886*b[0]+w*.0555179;
            b[1]=.99332*b[1]+w*.0750759;
            b[2]=.96900*b[2]+w*.1538520;
            b[3]=.86650*b[3]+w*.3104856;
            b[4]=.55000*b[4]+w*.5329522;
            b[5]=-.7616*b[5]-w*.0168980;
            const double y=b[0]+b[1]+b[2]+b[3]+b[4]+b[5]+b[6]+w*.5362;
            b[6]=w*.115926;
            return lp.step(hp.step(y));
        }
    };
    std::array<Voice,2> voices;
    double phase=0,increment=0,amplitude=0,scale=1;
    void prepare(double rate) {
        phase=0;increment=6.283185307179586*60/rate;
        // Calibrate band-limited pink RMS, independent of analyzer FFT length.
        Voice calibration;calibration.seed=0xabcdef12u;
        calibration.hp.prepare(rate,40,true);calibration.lp.prepare(rate,15000,false);
        double sum=0;const int n=static_cast<int>(rate*2);
        for(int i=0;i<n+4096;++i){const double y=calibration.pink();if(i>=4096)sum+=y*y;}
        amplitude=std::pow(10.,-83./20)/std::sqrt(sum/n);
        // Target complete additive noise at -87 dBV RMS (5 dB below factory ceiling).
        const double baseRms=std::sqrt(std::pow(10.,-83./10)+.5*std::pow(10.,-76./10)+.5*std::pow(10.,-79./10));
        scale=std::pow(10.,-87./20)/(fullScalePeakVolts*baseRms);
        for(int c=0;c<2;++c){auto& v=voices[c];v.seed=0x12345678u+0x9e3779b9u*c;v.b.fill(0);v.hp.prepare(rate,40,true);v.lp.prepare(rate,15000,false);}
    }
    float next(int c) {
        auto& v=voices[c];
        // Hum levels are peak dBFS; noise calibration is RMS dBFS.
        return float(scale*(amplitude*v.pink()+0.000158489319246*std::sin(phase)+0.000112201845430*std::sin(2*phase)));
    }
    void advance(){phase+=increment;if(phase>=6.283185307179586)phase-=6.283185307179586;}
};
}
