import time as _t
import peepypoo as ppp

asm = ppp.Process("ASM1", name="asm1", temperature=20.0)
od = asm.states()
init = {"S_I":5,"S_S":50,"X_I":80,"X_S":60,"X_BH":2200,"X_BA":80,"X_P":0,"S_O":0,
        "S_NO":0,"S_NH":25,"S_ND":3,"X_ND":60,"S_ALK":5200,"S_N2":0}

# Operator-set: recycle ratio (RAS as multiple of effluent) + a small WAS.
Q_in   = 2000.0
Q_eff  = 1900.0   # effluent (most of the flow)
Q_ras  = 1200.0   # recycler return (internal loop) -> holds solids
# WAS is then the balance remainder on the sludge separator, kept small by low Q_ras fraction of solids? No:
#   net water: Q_in = Q_eff + Q_was  -> Q_was = 100
#   solids balance sets how much biomass leaves with WAS; recycle keeps SRT high.
comp = {"S_I":30,"S_S":69.5,"X_I":51.2,"X_S":202.32,"X_BH":28.17,"X_BA":0,"X_P":0,
        "S_O":0,"S_NO":0,"S_NH":31.56,"S_ND":6.95,"X_ND":10.59,"S_ALK":7.0,"S_N2":0}

m = ppp.SystemConnection(name="plant")
m.start_building()
inf  = ppp.Influent(comp, od, flowrate=Q_in, name="inf")
r_an = ppp.CSTR(275.0, [asm], initial_states=init, name="anoxic")
r_ox = ppp.CSTR(450.0, [asm, ppp.Aeration(name="aerO")], initial_states=init, name="oxic")
clar = ppp.IdealClarifier(od, f_ns=0.02, name="clar")  # small non-settleable fraction

p_eff = ppp.FlowPump(od, flowrate=Q_eff, name="p_eff")
sep   = ppp.FlowSeparator(od, n_out=2, name="sep")
p_ras = ppp.FlowPump(od, flowrate=Q_ras, name="p_ras")
uni   = ppp.FlowUnifier(od, n_in=2, name="uni")

m.connect(inf.outflows(0),       uni.inflows(0))
m.connect(uni.outflows(0),       r_an.inflows(0))
m.connect(r_an.outflows(0),      r_ox.inflows(0))
m.connect(r_ox.outflows(0),      clar.inflows(0))
m.connect(clar.effluent,         p_eff.inflows(0))       # effluent (fixed)
m.connect(clar.sludge,           sep.inflows(0))         # sludge -> split
m.connect(sep.outflows(0),       p_ras.inflows(0))       # RAS (fixed) -> back
m.connect(p_ras.outflows(0),     uni.inflows(1))
# sep.outflows(1) = WAS, free remainder (waste)
kla = ppp.Constant(k=300.0, name="kla")
m.connect(kla.output, r_ox.exogenous_inputs(r_ox.exogenous_input_names[0]))
m.end_building()

t0=_t.time()
prob = ppp.ODEProblem(m, (0.0, 30.0))
sol = prob.solve()
print("solved in", round(_t.time()-t0,1),"s")

def g(blk,n):
    for u in blk.outflows(0).unknowns:
        if str(u).split("₊")[-1].split("(")[0]==n:
            return [float(v) for v in sol[u]]
    return None

x_ox = g(r_ox,"X_BH"); x_oxba = g(r_ox,"X_BA")
ne = g(clar,"S_NH"); no = g(clar,"S_NO")
# WAS solids
def gwas():
    for u in sep.outflows(1).unknowns:
        if str(u).split("₊")[-1].split("(")[0]=="X_BH":
            return [float(v) for v in sol[u]]
    return None
x_was = gwas()

print("oxic X_BH   :", round(min(x_ox),0),"->",round(x_ox[-1],0), "(last)")
print("oxic X_BA   :", round(min(x_oxba),1),"(min)")
print("eff  S_NH   :", round(min(ne),2),"-",round(ne[-1],2))
print("eff  S_NO   :", round(min(no),2),"-",round(no[-1],2))
if x_was: print("WAS  X_BH   :", round(min(x_was),1),"-",round(x_was[-1],1))
print("washout?", "YES" if x_ox[-1] < 200 else "NO — biomass retained")
