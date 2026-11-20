#include "Circuit.hpp"
#include "OutputResponse.hpp"

#include <complex>
#include <iomanip>
#include <iostream>
#include <numbers>
#include <string>

namespace {
using mkii::native::OutputResponse;
using mkii::native::Solver;
using Complex = std::complex<double>;

constexpr double pi = std::numbers::pi;
constexpr double attackStart = .4;
constexpr double releaseStart = .8;
constexpr double end = 1.25;
constexpr double timingFrequency = 1000;

double amplitude(double dbu) { return std::pow(10., (dbu - 18.) / 20.); }

int tone(int rate, double hz, double dbu, double more, bool correction) {
    Solver solver;
    if (!solver.prepare(rate)) return 2;
    OutputResponse response;
    response.prepare(rate);
    const int warm = rate / 2, length = rate;
    const int highest = std::min(20, int((rate / 2. - 1) / hz));
    std::array<Complex, 20> outputSpectrum{};
    Complex inputFundamental{};
    for (int i = 0; i < warm + length; ++i) {
        const double angle = 2 * pi * hz * i / rate;
        const double input = amplitude(dbu) * std::sin(angle) * std::min(1., i / (rate * .03));
        const double raw = solver.step(input, more, .5);
        const double output = correction ? response.process(raw) : raw;
        if (i < warm) continue;
        for (int k = 1; k <= highest; ++k)
            outputSpectrum[k - 1] += output * std::polar(1., -k * angle);
        inputFundamental += input * std::polar(1., -angle);
    }
    const Complex transfer = outputSpectrum[0] / inputFundamental;
    double sum = 0;
    for (int k = 1; k < highest; ++k) sum += std::norm(outputSpectrum[k]);
    std::cout << rate << ',' << more << ',' << hz << ',' << dbu << ','
              << 20 * std::log10(std::abs(transfer)) << ',' << std::arg(transfer) * 180 / pi << ','
              << 100 * std::sqrt(sum) / std::abs(outputSpectrum[0]) << ',' << solver.failures();
    for (int k = 1; k < highest; ++k)
        std::cout << ',' << 20 * std::log10(std::max(1e-30, std::abs(outputSpectrum[k] / outputSpectrum[0])));
    std::cout << '\n';
    return 0;
}

int burst(int rate, double lowDbu, double highDbu, double more, double level) {
    Solver solver;
    if (!solver.prepare(rate)) return 2;
    OutputResponse response;
    response.prepare(rate);
    const double low = amplitude(lowDbu), high = amplitude(highDbu);
    const auto edge = [](double seconds) {
        return .5 - .5 * std::cos(pi * std::clamp(seconds / .0005, 0., 1.));
    };
    Complex inputTone{}, outputTone{};
    double ec = 0, detector = 0;
    for (int i = 0; i < int(end * rate); ++i) {
        const double t = double(i) / rate;
        const double angle = 2 * pi * timingFrequency * t;
        const double gate = edge(t - attackStart) - edge(t - releaseStart);
        const double input = std::lerp(low, high, gate) * edge(t / 60) * std::sin(angle);
        const double output = response.process(solver.step(input, more, level));
        const Complex basis = std::polar(1., -angle);
        inputTone += input * basis;
        outputTone += output * basis;
        ec += solver.controlVolts();
        detector += solver.levelVolts();
        const int period = i * int(timingFrequency) / rate;
        const int next = (i + 1) * int(timingFrequency) / rate;
        if (next == period) continue;
        if (t > .33) {
            const double scale = double(rate) / timingFrequency;
            std::cout << (period + .5) / timingFrequency << ','
                      << 20 * std::log10(std::abs(inputTone / outputTone)) << ','
                      << ec / scale << ',' << detector / scale << ',' << solver.failures() << '\n';
        }
        inputTone = outputTone = {};
        ec = detector = 0;
    }
    return 0;
}
}

int main(int argc, char** argv) {
    std::cout << std::setprecision(10);
    if (argc == 7 && std::string(argv[1]) == "tone")
        return tone(std::stoi(argv[2]), std::stod(argv[3]), std::stod(argv[4]),
                    std::stod(argv[5]), std::stoi(argv[6]) != 0);
    if (argc == 7 && std::string(argv[1]) == "burst")
        return burst(std::stoi(argv[2]), std::stod(argv[3]), std::stod(argv[4]),
                     std::stod(argv[5]), std::stod(argv[6]));
    std::cerr << "Usage: XLProbe tone <rate> <Hz> <input dBu> <slider> <correction 0/1>\n"
                 "       XLProbe burst <rate> <low dBu> <high dBu> <slider> <level set>\n";
    return 2;
}
