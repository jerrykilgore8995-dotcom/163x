#pragma once
#include <array>
#include <cmath>
#include <numbers>
namespace mkii::native {
// 2x linear-phase halfband, Blackman window. Two 80-high-rate-sample
// group delays give 80 host samples end to end.
class Halfband {
public:
 static constexpr int taps=161, center=80;
 void reset(){
  history.fill(0); pos=0;
  double sum=0;
  for(int i=0;i<taps;++i){
   int n=i-center;
   double w=.42-.5*std::cos(2*std::numbers::pi*i/(taps-1))+.08*std::cos(4*std::numbers::pi*i/(taps-1));
   coefficients[i]=n==0?.5:(n%2==0?0:std::sin(std::numbers::pi*n/2)/(std::numbers::pi*n)*w);
   sum+=coefficients[i];
  }
  for(auto& c:coefficients)c/=sum;
 }
 double step(double x){
  history[pos]=history[pos+taps]=x;
  const double* current=history.data()+pos+taps;
  double y=coefficients[center]*current[-center];
  for(int i=1;i<taps;i+=2)y+=coefficients[i]*current[-i];
  if(++pos==taps)pos=0;
  return y;
 }
private:
 std::array<double,taps> coefficients{};
 std::array<double,2*taps> history{};
 int pos=0;
};
}
