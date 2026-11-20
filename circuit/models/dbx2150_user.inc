* User-supplied experimental core. Not a vendor-validated 2150 model.
.subckt DBX2150_CORE 1 2 3 4 5 6 7 8
E_servo srv 0 VALUE = { -V(1) * 5000 }
R_in_lim 1 0 100k
Q_b1 5 5 6 NPN_2150
Q_b2 b_n 5 6 NPN_2150
Q_b3 b_p b_p 8 PNP_2150
R_bm b_p b_n 10
Q1 8 srv e_up NPN_2150
Q2 e_up 0 1 PNP_2150
Q3 6 srv e_dn PNP_2150
Q4 e_dn 0 1 NPN_2150
Q5 7 3 e_up NPN_2150_MIS
Q6 e_up 2 8 PNP_2150
Q7 7 3 e_dn PNP_2150_MIS
Q8 e_dn 2 6 NPN_2150
R_sym_up 4 e_up 220
R_sym_dn 4 e_dn 220
I_q_up 8 e_up 1.2m
I_q_dn e_dn 6 1.2m
.model NPN_2150 NPN(IS=1.00e-14 BF=250 VAF=80 RB=15 RE=0.8 CJE=2p CJC=1.5p TF=0.3n)
.model PNP_2150 PNP(IS=1.00e-14 BF=200 VAF=65 RB=18 RE=0.9 CJE=2.5p CJC=1.8p TF=0.4n)
.model NPN_2150_MIS NPN(IS=1.015e-14 BF=245 VAF=78 RB=15 RE=0.8 CJE=2p CJC=1.5p TF=0.3n)
.model PNP_2150_MIS PNP(IS=0.985e-14 BF=205 VAF=67 RB=18 RE=0.9 CJE=2.5p CJC=1.8p TF=0.4n)
.ends DBX2150_CORE
