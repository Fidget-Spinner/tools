"""Companion to pyco, reads the new PYC format.

This exists mostly as a way to validate that the PYC format proposal
has enough imformation to roundtrip.
"""

import dis
import struct
import types

import updis  # Update dis with extra opcodes


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    def seek(self, pos: int):
        assert pos >= 0
        self.pos = pos

    def read_raw_bytes(self, n: int) -> bytes:
        b = self.data[self.pos : self.pos + n]
        assert len(b) == n
        self.pos += n
        return b

    def read_short(self) -> int:
        part = self.data[self.pos : self.pos + 2]
        self.pos += 2
        return struct.unpack("<H", part)[0]

    def read_long(self) -> int:
        part = self.data[self.pos : self.pos + 4]
        self.pos += 4
        return struct.unpack("<L", part)[0]

    def read_offsets(self, n: int) -> list[int]:
        return [self.read_long() for _ in range(n)]

    def read_varint(self) -> int:
        result = 0
        while True:
            byte = self.data[self.pos]
            self.pos += 1
            result = result << 7 | byte & 0x7F
            if not result & 0x80:
                break
        return result

    def read_varstring(self) -> str:
        n_bytes = self.read_varint()
        raw = self.read_raw_bytes(n_bytes)
        return raw.decode("utf-8")


def dummy_func():
    pass


dummy_code = dummy_func.__code__

class PycFile:
    def __init__(self, data: bytes):
        self.data = data
        self.code_objects: list[types.CodeType] = []
        self.constants: list[object] = []
        self.strings: list[str] = []

    def load(self):
        reader = Reader(self.data)
        assert reader.read_raw_bytes(4) == b".pyc", data[:4]
        self.version = reader.read_short()
        assert self.version == 0
        self.n_code = reader.read_short()
        meta_start = reader.read_long()
        assert meta_start == 0
        total_size = reader.read_long()
        data_size = len(self.data)
        assert total_size == data_size, (total_size, data_size)
        self.code_offsets = reader.read_offsets(self.n_code)
        self.n_constants = reader.read_long()
        self.const_offsets = reader.read_offsets(self.n_constants)
        self.n_strings = reader.read_long()
        self.string_offsets = reader.read_offsets(self.n_strings)
        self.n_blobs = reader.read_long()
        self.blob_offsets = reader.read_offsets(self.n_blobs)

        self.code_objects = [None] * self.n_code
        self.constants = [None] * self.n_constants
        self.strings = [None] * self.n_strings

    def get_code(self, i: int):
        assert 0 <= i < len(self.code_objects)
        result = self.code_objects[i]
        if result is not None:
            return result
        # Make a new code object (TODO)

    def report(self):
        reader = Reader(self.data)
        # Print the strings table, as an example
        strings = []
        for i, offset in enumerate(self.string_offsets):
            reader.seek(offset)
            s = reader.read_varstring()
            print(f"String {i} at {offset}: {s!r}")
            strings.append(s)
        # Print the constants, as another example
        for i, offset in enumerate(self.const_offsets):
            reader.seek(offset)
            max_stacksize = reader.read_long()
            n_instrs = reader.read_long()
            bytecode = reader.read_raw_bytes(2 * n_instrs)
            print(
                f"Constant {i} at {offset}, stack={max_stacksize}, {n_instrs} opcodes"
            )
            dis.dis(bytecode)
        # We're on a roll! Print the code objects
        for i, offset in enumerate(self.code_offsets):
            reader.seek(offset)
            values = struct.unpack("<12L", reader.read_raw_bytes(12 * 4))
            print(f"Code object {i} at {offset}")
            print(values)
            n_instrs = values[-1]
            bytecode = reader.read_raw_bytes(2 * n_instrs)
            n_varnames = reader.read_long()
            varname_offsets = reader.read_offsets(n_varnames)
            dis.dis(bytecode)
            for j, idx in enumerate(varname_offsets):
                varname = strings[idx]
                print(f"Var {j} at index {idx}: {varname!r}")


def unpyc(data: bytes):
    pyc = PycFile(data)
    pyc.load()
    pyc.report()


def main():
    with open("example.pyc", "rb") as f:
        data = f.read()
        unpyc(data)


if __name__ == "__main__":
    main()
