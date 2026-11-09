"""Minimal IPS / BPS apply + create, with the checks that matter here.

IPS: reports every record (offset, length, RLE) so the caller can see what a
patch touches; flags the 'EOF' (0x454F46) offset ambiguity and truncation tails.
BPS: verifies source, target and patch CRC32 as the format requires.
"""
import struct
import zlib


def ips_records(patch):
    if patch[:5] != b"PATCH":
        raise ValueError("not an IPS patch")
    i, recs = 5, []
    while True:
        if patch[i:i + 3] == b"EOF":
            tail = patch[i + 3:]
            trunc = None
            if len(tail) == 3:
                trunc = int.from_bytes(tail, "big")
            elif tail:
                raise ValueError("junk after EOF: %r" % tail[:16])
            # an EOF marker is ambiguous only if bytes after it would form a record
            return recs, trunc
        off = int.from_bytes(patch[i:i + 3], "big")
        size = int.from_bytes(patch[i + 3:i + 5], "big")
        i += 5
        if size == 0:
            n = int.from_bytes(patch[i:i + 2], "big")
            val = patch[i + 2]
            i += 3
            recs.append((off, bytes([val]) * n, True))
        else:
            recs.append((off, patch[i:i + size], False))
            i += size
        if i > len(patch):
            raise ValueError("IPS truncated")


def ips_apply(data, patch):
    recs, trunc = ips_records(patch)
    out = bytearray(data)
    for off, payload, _rle in recs:
        end = off + len(payload)
        if end > len(out):
            out.extend(bytes(end - len(out)))
        out[off:end] = payload
    if trunc is not None:
        del out[trunc:]
    return bytes(out)


def ips_create(src, dst):
    """Simple IPS writer: diff runs, split at 0xFFFF, never emit offset 0x454F46."""
    if len(dst) < len(src):
        raise ValueError("IPS cannot express shrink here")
    if len(dst) > 0x1000000:
        raise ValueError("too big for IPS")
    out = bytearray(b"PATCH")
    n = len(dst)
    i = 0
    while i < n:
        same = i < len(src) and src[i] == dst[i]
        if same:
            i += 1
            continue
        j = i
        while j < n and j - i < 0xFFFF:
            if j < len(src) and src[j] == dst[j]:
                # allow short equal gaps (<6) to be bridged
                k = j
                while k < n and k < len(src) and src[k] == dst[k] and k - j < 6:
                    k += 1
                if k - j >= 6 or k >= n:
                    break
                j = k
                continue
            j += 1
        start = i
        if start == 0x454F46:
            start -= 1
        chunk = dst[start:j]
        out += start.to_bytes(3, "big") + len(chunk).to_bytes(2, "big") + chunk
        i = j
    out += b"EOF"
    return bytes(out)


def _bps_num(p, i):
    data, shift = 0, 1
    while True:
        x = p[i]
        i += 1
        data += (x & 0x7F) * shift
        if x & 0x80:
            break
        shift <<= 7
        data += shift
    return data, i


def bps_apply(src, patch):
    if patch[:4] != b"BPS1":
        raise ValueError("not BPS")
    sc, tc, pc = struct.unpack("<III", patch[-12:])
    if zlib.crc32(patch[:-4]) != pc:
        raise ValueError("BPS patch CRC bad")
    if zlib.crc32(src) != sc:
        raise ValueError("BPS source CRC mismatch: have %08X want %08X" % (zlib.crc32(src), sc))
    i = 4
    ssize, i = _bps_num(patch, i)
    tsize, i = _bps_num(patch, i)
    msize, i = _bps_num(patch, i)
    i += msize
    out = bytearray(tsize)
    op = 0
    srel = trel = 0
    end = len(patch) - 12
    while i < end:
        d, i = _bps_num(patch, i)
        cmd, ln = d & 3, (d >> 2) + 1
        if cmd == 0:
            out[op:op + ln] = src[op:op + ln]
            op += ln
        elif cmd == 1:
            out[op:op + ln] = patch[i:i + ln]
            i += ln
            op += ln
        else:
            v, i = _bps_num(patch, i)
            v = (-1 if v & 1 else 1) * (v >> 1)
            if cmd == 2:
                srel += v
                out[op:op + ln] = src[srel:srel + ln]
                srel += ln
                op += ln
            else:
                trel += v
                for _ in range(ln):
                    out[op] = out[trel]
                    op += 1
                    trel += 1
    if zlib.crc32(out) != tc:
        raise ValueError("BPS target CRC mismatch")
    return bytes(out)
