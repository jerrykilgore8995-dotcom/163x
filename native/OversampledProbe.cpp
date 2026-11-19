#include "Client.hpp"
#include "Calibration.hpp"
#include <array>
#include <complex>
#include <vector>
#include <cmath>
#include <numbers>
#include <cstdio>
int main(){
 using namespace mkii::native;
 constexpr int rate=44100,warm=44100,count=22050;
 wchar_t path[32768]{};
 if(!GetFullPathNameW(L"build/163x-native.dll",32768,path,nullptr))return 2;
 Client p;if(!p.open(path))return 3;
 for(double more:{0.,.45,1.}){
  for(int hz:(more==0?std::vector<int>{30,1000,5000,10000,15000,20000}:std::vector<int>{1000})){
   if(!p.prepare(rate,1,512))return 4;
   int delay=p.latency(),total=warm+count+delay;std::vector<float>x(total);
   for(int i=0;i<total;++i)x[i]=float(.11*std::sin(2*std::numbers::pi*hz*i/rate)*std::min(1.,i/1300.));
   Controls ctl{float(more),.5f};
   for(int i=0;i<total;i+=512){float* ptr=x.data()+i;if(!p.process(&ptr,std::min(512,total-i),ctl,true))return 5;}
   std::array<std::complex<double>,5> bins{};
   for(int i=0;i<count;++i)for(int k=1;k<=5;++k)bins[k-1]+=double(x[warm+delay+i])*std::polar(1.,-2*std::numbers::pi*hz*i*k/rate);
   double harm=0;for(int k=1;k<5&&(k+1)*hz<rate/2;++k)harm+=std::norm(bins[k]);
   const double volts=std::abs(bins[0])*2/count*mkii::fullScalePeakVolts/std::sqrt(2.);
   std::printf("%.2f,%d,%.8f,%.8f,%u\n",more,hz,20*std::log10(volts/.775),100*std::sqrt(harm)/std::abs(bins[0]),p.failedSolves());
   if(p.failedSolves())return 6;p.stop();
  }
 }
}
