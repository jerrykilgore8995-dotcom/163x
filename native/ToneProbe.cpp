#include "Circuit.hpp"
#include "OutputResponse.hpp"

#include <complex>
#include <cstdio>
#include <numbers>
#include <chrono>

int main() {
    constexpr int rate=44100, warm=13230, count=22050;
    for (const double more : {0.,0.45,1.}) {
        const auto frequencies=more==0 ? std::vector{30,1000,5000,10000,15000,20000}
                                       : std::vector{1000};
        for (const int frequency : frequencies) {
            mkii::native::Solver solver;
            if (!solver.prepare(rate)) return 2;
            std::fprintf(stderr,"New kernel frequency=%d generated=%d eliminationUpdates=%d\n",frequency,int(solver.usesGenerated()),solver.operations());
            const auto start=std::chrono::steady_clock::now();
            mkii::native::OutputResponse response;
            response.prepare(rate);
            std::array<std::complex<double>,5> spectrum{};
            for (int i=0;i<count;++i) {
                const double phase=2*std::numbers::pi*frequency*i/rate;
                const double input=0.11*std::sin(phase)*std::min(1.,i/1300.);
                const double output=response.process(solver.step(input,more,0.5));
                if (i>=warm)
                    for (int k=1;k<=5;++k) spectrum[k-1]+=output*std::polar(1.,-k*phase);
            }
            std::fprintf(stderr,"New kernel elapsedMs=%.3f audioMs=%.3f refined=%u misses=%u\n",std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count(),1000.0*count/rate,solver.refinedSamples(),solver.failures());
            const double volts=std::abs(spectrum[0])*2/(count-warm)*mkii::fullScalePeakVolts/std::sqrt(2.);
            double harmonics=0;
            for (int i=1;i<5 && (i+1)*frequency<rate/2;++i) harmonics+=std::norm(spectrum[i]);
            std::printf("%.2f,%d,%.8f,%.8f,%u\n",more,frequency,20*std::log10(volts/0.775),
                        100*std::sqrt(harmonics)/std::abs(spectrum[0]),solver.failures());
        }
    }
}
