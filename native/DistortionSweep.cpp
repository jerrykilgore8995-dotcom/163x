#include "Client.hpp"
#include "Calibration.hpp"
#include <array>
#include <vector>
#include <complex>
#include <cmath>
#include <numbers>
#include <iostream>
#include <iomanip>
#include <algorithm>
int main(){
 using namespace mkii::native;
 constexpr int rate=44100,warm=rate*2,count=rate;
 const double amp=.775*std::sqrt(2.)*std::pow(10.,4./20)/mkii::fullScalePeakVolts;
 wchar_t path[32768]{};
 if(!GetFullPathNameW(L"build/163x-native.dll",32768,path,nullptr))return 2;
 Client p;if(!p.open(path))return 3;
 std::cout<<std::fixed<<std::setprecision(8)<<"Hz,slider_pct,input_dBu,level_set_dBV,output_dBu,GR_peak_dB,THD_pct,THD_dBc,residual_THDN_dBc";
 for(int k=2;k<=20;++k)std::cout<<",K"<<k<<"_dBc";
 std::cout<<",failed_solves"<<std::endl;
 bool pass=true;
 for(int hz:{1000,100})for(int slider=0;slider<=100;slider+=10){
  if(!p.prepare(rate,1,512))return 4;
  int delay=p.latency(),total=warm+count+delay;
  std::vector<float> x(total);
  for(int i=0;i<total;++i)x[i]=float(amp*std::sin(2*std::numbers::pi*hz*i/rate)*std::min(1.,i/1300.));
  double gr=0;Controls ctl{slider/100.f,.5f};
  for(int i=0;i<total;i+=512){float* ptr=x.data()+i;if(!p.process(&ptr,std::min(512,total-i),ctl,true))return 5;if(i>=warm+delay)gr=std::max(gr,double(p.readMeters().gainReductionDb));}
  std::array<std::complex<double>,20> bins{}; double energy=0,mean=0;
  for(int i=0;i<count;++i){double y=x[warm+delay+i],phase=2*std::numbers::pi*hz*i/rate;energy+=y*y;mean+=y;auto z=std::polar(1.,-phase),v=z;for(auto& b:bins){b+=y*v;v*=z;}}
  double fundamental=std::norm(bins[0]),harm=0;
  for(int k=1;k<20;++k)harm+=std::norm(bins[k]);
  auto db=[](double x){return 10*std::log10(std::max(x,1e-300));};
  double rms=std::sqrt(2*fundamental)/count*mkii::fullScalePeakVolts;
  double residual=std::max(0.,energy/count-std::pow(mean/count,2)-2*fundamental/(double(count)*count));
  std::cout<<hz<<","<<slider<<",4,-10,"<<20*std::log10(rms/.775)<<","<<gr<<","<<100*std::sqrt(harm/fundamental)<<","<<db(harm/fundamental)<<","<<db(residual/(2*fundamental/(double(count)*count)));
  for(int k=1;k<20;++k)std::cout<<","<<db(std::norm(bins[k])/fundamental);
  auto failures=p.failedSolves();std::cout<<","<<failures<<std::endl;pass=pass&&!failures&&fundamental>0&&std::isfinite(energy);p.stop();
 }
 return pass?0:6;
}
