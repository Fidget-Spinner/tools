"""Companion to pyco, reads the new PYC format.

This exists mostly as a way to validate that the PYC format proposal
has enough imformation to roundtrip.
"""

import struct


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def read_raw_bytes(self, n: int) -> bytes:
        b = self.data[self.pos : self.pos + n]
        assert len(b) == n
        self.pos += n
        return b

    def read_short(self) -> int:
        part = self.data[self.pos : self.pos+2]
        self.pos += 2
        return struct.unpack("<H", part)[0]
    
    def read_long(self) -> int:
        part = self.data[self.pos : self.pos+4]
        self.pos += 4
        return struct.unpack("<L", part)[0]
    
    def read_offsets(self, n: int) -> list[int]:
        return [self.read_long() for _ in range(n)]
    
    def read_varint(self) -> int:
        result = 0
        while True:
            byte = self.data[self.pos]
            self.pos += 1
            result = result<<7 | byte&0x7F
            if not result&0x80:
                break
        return result

    def read_varstring(self) -> str:
        n_bytes = self.read_varint()
        raw = self.read_raw_bytes(n_bytes)
        return raw.decode("utf-8")


def unpyc(data: bytes):
    reader = Reader(data)
    assert reader.read_raw_bytes(4) == b".pyc", data[:4]
    version = reader.read_short()
    assert version == 0
    n_code = reader.read_short()
    meta_start = reader.read_long()
    assert meta_start == 0
    total_size = reader.read_long()
    assert total_size == len(data), (total_size, len(data))
    code_offsets = reader.read_offsets(n_code)
    n_constants = reader.read_long()
    const_offsets = reader.read_offsets(n_constants)
    n_strings = reader.read_long()
    string_offsets = reader.read_offsets(n_strings)
    n_blobs = reader.read_long()
    blob_offsets = reader.read_offsets(n_blobs)
    # Print the strings table, as an example
    for i, so in enumerate(string_offsets):
        r = Reader(data, so)
        s = r.read_varstring()
        print(f"String {i} at {so}: {s!r}")


def main():
    with open("example.pyc", "rb") as f:
        data = f.read()
        unpyc(data)


if __name__ == "__main__":
    main()
