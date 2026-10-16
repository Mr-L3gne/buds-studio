import re,sys
src=open(sys.argv[1]).read()
table=[int(x) for x in re.search(r'f19608a = \{([^}]*)\}',src).group(1).split(',')]
def crc_bitwise(data):
    c=0
    for b in data:
        c^=b<<8
        for _ in range(8):
            c=((c<<1)^0x1021) if c&0x8000 else c<<1
            c&=0xFFFF
    return c
gen=[crc_bitwise(bytes([i]))for i in range(256)]
print("table == CRC16/XMODEM(poly 0x1021, init 0):", gen==table, "check('123456789')=%04X"%crc_bitwise(b"123456789"))
def frame(mid,payload=b"",resp=False):
    body=bytes([mid])+payload
    ln=len(body)+2
    hdr=ln&0x3FF | (0x1000 if resp else 0)
    c=crc_bitwise(body)
    return bytes([0xFD,hdr&0xFF,hdr>>8])+body+bytes([c&0xFF,c>>8,0xDD])
def hx(b): return ' '.join('%02X'%x for x in b)
for i,n in enumerate(["Normal/Balanced","Bass boost","Soft/Smooth","Dynamic","Clear","Treble boost"]):
    print("EQ",i,n,hx(frame(0x86,bytes([i]))))
for i,n in enumerate(["Off","ANC","Ambient"]):
    print("NC",i,n,hx(frame(0x78,bytes([i]))))
print("BAL16",hx(frame(0x8F,bytes([16]))))
print("EXT_ACK",hx(frame(0x61,bytes([0]),resp=True)))
# verify decoder rule: crc over msgid..crc(swapped) == 0
f=frame(0x86,bytes([1])); inner=bytearray(f[3:-1]); inner[-1],inner[-2]=inner[-2],inner[-1]
print("decoder check zero:", crc_bitwise(bytes(inner))==0)
