"""Decode RPGOne script bytes: python tools/txt.py ROM SNESADDR LEN"""
import sys


def snes2off(a):
    """LoROM, headerless: SNES bank/address to file offset."""
    bank = (a >> 16) & 0x7F
    addr = a & 0xFFFF
    if addr < 0x8000:
        raise ValueError('not a ROM address: %06X' % a)
    return bank * 0x8000 + (addr - 0x8000)

def dec(b):
    s=[]; i=0
    while i<len(b):
        x=b[i]
        if 0x10<=x<=0x29: s.append(chr(65+x-0x10))
        elif 0x30<=x<=0x49: s.append(chr(97+x-0x30))
        elif x==0: s.append(' ')
        elif x==0xfe: s.append('\n')
        elif x==0xff: s.append('<END>\n')
        elif x==0xf1 and i+2<len(b): s.append('<NAME@%02X%02X>'%(b[i+2],b[i+1])); i+=2
        elif x==0xf4: s.append('<HERO>')
        else: s.append('{%02x}'%x)
        i+=1
    return ''.join(s)
if __name__=='__main__':
    d=open(sys.argv[1],'rb').read()
    o=snes2off(int(sys.argv[2],16)); n=int(sys.argv[3],16)
    sys.stdout.reconfigure(encoding='utf-8')
    print(dec(d[o:o+n]))
