#include "Circuit.hpp"
#include "OutputResponse.hpp"

#include <complex>
#include <cstdio>
#include <numbers>
#include <string>

int main(int argc,char** argv) {
    const bool full=argc>1 && std::string(argv[1])=="full";
    constexpr int rate=44100;
    for (const double more : {0.,0.45,1.}) {
        const auto frequencies=more==0 ? (full ? std::vector{1,2,5,10,15,20,30,40,50,60,80,100,150,200,300,500,700,1000,1500,2000,3000,4000,5000,6000,8000,10000,12000,14000,15000,16000,18000,19000,20000} : std::vector{30,1000,5000,10000,15000,20000})
                                       : std::vector{1000};
        for (const int frequency : frequencies) {
            const int warm=full?rate:13230;
            const int count=full?warm+rate*std::max(1,4/frequency):22050;
            mkii::native::Solver solver;
            if (!solver.prepare(rate)) return 2;
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
            const double volts=std::abs(spectrum[0])*2/(count-warm)*mkii::fullScalePeakVolts/std::sqrt(2.);
            double harmonics=0;
            for (int i=1;i<5 && (i+1)*frequency<rate/2;++i) harmonics+=std::norm(spectrum[i]);
            std::printf("%.2f,%d,%.8f,%.8f,%u\n",more,frequency,20*std::log10(volts/0.775),
                        100*std::sqrt(harmonics)/std::abs(spectrum[0]),solver.failures());
        }
    }
}
