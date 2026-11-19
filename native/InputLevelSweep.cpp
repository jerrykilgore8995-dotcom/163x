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
 constexpr int rate=192000,warm=rate*2,count=rate;
 
 wchar_t path[32768]{};
 if(!GetFullPathNameW(L"build/163x-native.dll",32768,path,nullptr))return 2;
 Client p;if(!p.open(path))return 3;
 std::cout<<std::fixed<<std::setprecision(12)<<"Hz,slider_pct,input_dBu,level_set_dBV,output_dBu,GR_peak_dB,THD_pct,THD_dBc,residual_THDN_dBc";
 for(int k=2;k<=20;++k)std::cout<<",K"<<k<<"_dBc";
 for(int k:{2,3,5})std::cout<<",K"<<k<<"_real,K"<<k<<"_imag";
 std::cout<<",fundamental_peak,other_harmonic_power,failed_solves"<<std::endl;
 bool pass=true;
 for(int hz:{1000,100,40,20,5000,10000,20000})for(int dbu:{4,8,12,16}){
  constexpr int slider=100;
  const double amp=.775*std::sqrt(2.)*std::pow(10.,dbu/20.)/mkii::fullScalePeakVolts;
  if(!p.prepare(rate,1,512))return 4;
  int delay=p.latency(),total=warm+count+delay;
  std::vector<float> x(total);
  for(int i=0;i<total;++i)x[i]=float(amp*std::sin(2*std::numbers::pi*hz*i/rate)*std::min(1.,i/1300.));
  double gr=0;Controls ctl{slider/100.f,.5f};
  for(int i=0;i<total;i+=512){float* ptr=x.data()+i;if(!p.process(&ptr,std::min(512,total-i),ctl,true))return 5;if(i>=warm+delay)gr=std::max(gr,double(p.readMeters().gainReductionDb));}
  std::array<std::complex<double>,20> bins{}; double energy=0,mean=0;
  for(int i=0;i<count;++i){double y=x[warm+delay+i],phase=2*std::numbers::pi*hz*i/rate;energy+=y*y;mean+=y;auto z=std::polar(1.,-phase),v=z;for(auto& b:bins){b+=y*v;v*=z;}}
  double fundamental=std::norm(bins[0]),harm=0;
  for(int k=1;k<20 && (k+1)*hz<rate/2;++k)harm+=std::norm(bins[k]);
  auto db=[](double x){return 10*std::log10(std::max(x,1e-300));};
  double rms=std::sqrt(2*fundamental)/count*mkii::fullScalePeakVolts;
  double residual=std::max(0.,energy/count-std::pow(mean/count,2)-2*fundamental/(double(count)*count));
  std::cout<<hz<<","<<slider<<","<<dbu<<",-10,"<<20*std::log10(rms/.775)<<","<<gr<<","<<100*std::sqrt(harm/fundamental)<<","<<db(harm/fundamental)<<","<<db(residual/(2*fundamental/(double(count)*count)));
  for(int k=1;k<20;++k)std::cout<<","<<db(std::norm(bins[k])/fundamental);
  for(int k:{2,3,5})std::cout<<","<<2*bins[k-1].real()/count<<","<<2*bins[k-1].imag()/count;
  double other=0;for(int k=2;k<=20 && k*hz<rate/2;++k)if(k!=2&&k!=3&&k!=5)other+=4*std::norm(bins[k-1])/(double(count)*count);
  std::cout<<","<<2*std::abs(bins[0])/count<<","<<other;
  auto failures=p.failedSolves();std::cout<<","<<failures<<std::endl;pass=pass&&!failures&&fundamental>0&&std::isfinite(energy);p.stop();
 }
 return pass?0:6;
}
