* XNOR2 — coincidência DTL (XOR2 + INV; 5 transistores NPN)
.subckt XNOR2 A B Y VDD GND
X1 A  B xr VDD GND XOR2
X2 xr Y    VDD GND INV
.ends XNOR2
