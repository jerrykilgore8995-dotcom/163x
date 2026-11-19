#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <complex>
#include <vector>
namespace mkii {
constexpr double modPi=3.14159265358979323846;
struct ModFilter {
 double b0=1,b1=0,b2=0,a1=0,a2=0,z1=0,z2=0;
 void prepare(double fs,double hz,int type,double q){
  double w=2*modPi*hz/fs,c=std::cos(w),a=std::sin(w)/(2*q),d=1+a;
  if(type==0){b0=(1-c)/(2*d);b1=2*b0;b2=b0;}
  else if(type==1){b0=(1+c)/(2*d);b1=-2*b0;b2=b0;}
  else {b0=a/d;b1=0;b2=-b0;}
  a1=-2*c/d;a2=(1-a)/d;z1=z2=0;
 }
 double step(double x){double y=b0*x+z1;z1=b1*x-a1*y+z2;z2=b2*x-a2*y;return y;}
};
struct LowBypass {
 struct Split {std::array<ModFilter,2> lo,hi;};
 std::array<std::array<Split,3>,2> filters;
 std::array<std::vector<float>,2> delay;
 std::array<double,4> weights{};double alpha=1;int pos=0,size=1;
 void prepare(double fs,int latency,int mode){
  size=std::max(1,latency);pos=0;alpha=1-std::exp(-1/(.015*fs));weights.fill(0);weights[std::clamp(mode,0,3)]=1;
  for(int c=0;c<2;++c){delay[c].assign(size,0);for(int j=0;j<3;++j){double hz=std::array<double,3>{60,120,250}[j];for(auto& f:filters[c][j].lo)f.prepare(fs,hz,0,.7071067811865475);for(auto& f:filters[c][j].hi)f.prepare(fs,hz,1,.7071067811865475);}}
 }
 void update(int mode){for(int j=0;j<4;++j){double target=j==mode?1:0;weights[j]+=alpha*(target-weights[j]);if(std::abs(weights[j]-target)<1e-10)weights[j]=target;}}
 float split(int c,float x,float& oldLow){
  double lo=0,hi=weights[0]*x;
  for(int j=0;j<3;++j){auto& f=filters[c][j];lo+=weights[j+1]*f.lo[1].step(f.lo[0].step(x));hi+=weights[j+1]*f.hi[1].step(f.hi[0].step(x));}
  oldLow=delay[c][pos];delay[c][pos]=float(lo);return float(hi);
 }
 void advance(){if(++pos==size)pos=0;}
};
struct TurboBand {
 std::array<ModFilter,3> filters;double previous=0,cs=0,sn=1;
 std::array<double,4> gains{};
 void prepare(double fs,double hz,std::array<double,4> db){
  double w=2*modPi*hz/fs;cs=std::cos(w);sn=std::sin(w);previous=0;
  for(auto& f:filters)f.prepare(fs,hz,2,4.);
  for(int j=0;j<4;++j)gains[j]=db[j]<-200?0:std::pow(10.,db[j]/20);
 }
 double step(double x){
  for(auto& f:filters)x=f.step(x);
  std::complex<double> z(x,(previous-cs*x)/sn);previous=x;
  double a=std::abs(z);if(a<1e-12)return 0;
  z/=a;auto power=z;double y=0;for(int j=0;j<4;++j){power*=z;y+=gains[j]*power.real();}
  return a*y;
 }
};
struct Turbo {
 std::array<std::array<TurboBand,2>,2> channels;double amount=0,alpha=1;
 void prepare(double fs,bool enabled){amount=enabled?1:0;alpha=1-std::exp(-1/(.01*fs));for(auto& c:channels){c[0].prepare(fs,100,{-82,-74,-98,-85});c[1].prepare(fs,1000,{-80,-72,-300,-86});}}
 void update(bool enabled){double t=enabled?1:0;amount+=alpha*(t-amount);if(std::abs(amount-t)<1e-10)amount=t;}
 float step(int c,float x){double y=0;for(auto& b:channels[c])y+=b.step(x);return float(x+amount*y);}
};
}
