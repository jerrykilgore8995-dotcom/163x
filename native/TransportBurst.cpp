#include "Client.hpp"
#include <iostream>
#include <vector>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <thread>
using namespace mkii::native;
int main(){
 constexpr int rate=44100,N=24576; bool pass=true;
 for(int B:{256,512}) for(int channels:{1,2}) for(int lead:{0,512,2048}) for(int burst:{1,3,5}) {
  Client p;
  wchar_t path[32768]{};
  if(!GetFullPathNameW(L"build/163x-native.dll",32768,path,nullptr)){std::cerr<<"GetFullPathName failed "<<GetLastError()<<std::endl;return 2;}
  if(!p.open(path)){std::wcerr<<L"DLL open failed: "<<path<<L" error "<<GetLastError()<<std::endl;return 2;}
  if(!p.prepare(rate,channels,B)){std::cerr<<"DLL prepare failed B="<<B<<" channels="<<channels<<std::endl;return 2;}
  const int D=p.latency();
  std::vector<float> in[2],ref[2],actual[2];
  for(int c=0;c<channels;c++){
   in[c].resize(N);
   for(int i=lead;i<N;i++){double t=double(i-lead)/rate;in[c][i]=float(.8*std::exp(-t/.04)*std::cos(6.283185307*(110+c*37)*t));}
   ref[c]=in[c];actual[c]=in[c];
  }
  float* a[2]={ref[0].data(),ref[1].data()};if(!p.process(a,N,{},true)||p.failedSolves())return 3;
  p.stop();if(!p.prepare(rate,channels,B))return 4;
  std::this_thread::sleep_for(std::chrono::seconds(1));
  auto start=std::chrono::steady_clock::now();double maxMs=0;unsigned misses=0;
  for(int i=0;i<N;i+=B){
   auto due=start+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(double(std::max(0,i-(burst-1)*B))/rate));
   std::this_thread::sleep_until(due);
   float* x[2]={actual[0].data()+i,channels==2?actual[1].data()+i:nullptr};
   auto begin=std::chrono::steady_clock::now();
   if(!p.process(x,B,{},false))++misses;
   maxMs=std::max(maxMs,std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count());
  }
  unsigned errors=0;double peak=0;
  for(int c=0;c<channels;c++)for(int i=0;i<N;i++){double e=std::abs(actual[c][i]-ref[c][i]);peak=std::max(peak,e);if(!std::isfinite(e)||e>2e-5)++errors;}
  bool ok=!errors&&!misses&&!p.failedSolves()&&maxMs<B*1000.0/rate;
  pass &=ok;
  std::cout<<"block="<<B<<" channels="<<channels<<" lead="<<lead<<" burst="<<burst<<" latency="<<D<<" missedCallbacks="<<misses<<" errors="<<errors<<" peak="<<peak<<" maxCallbackMs="<<maxMs<<" failed="<<p.failedSolves()<<" pass="<<ok<<std::endl;
 }
 return pass?0:1;
}
