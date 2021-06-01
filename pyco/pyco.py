"""Compiler to create new-style PYC files

See https://github.com/faster-cpython/ideas/issues/32
and https://github.com/python/peps/compare/master...markshannon:pep-mappable-pyc-file
"""

import dis
import struct

UNARY_NEGATIVE = dis.opmap["UNARY_NEGATIVE"]
BUILD_TUPLE = dis.opmap["BUILD_TUPLE"]
EXTENDED_ARG = dis.opmap["EXTENDED_ARG"]


def def_op(name: str, op: int) -> int:
    dis.opname[op] = name
    dis.opmap[name] = op
    return op


MAKE_INT = def_op("MAKE_INT", 170)
MAKE_LONG = def_op("MAKE_LONG", 171)
MAKE_FLOAT = def_op("MAKE_FLOAT", 172)
MAKE_STRING = def_op("MAKE_STRING", 173)


def encode_varint(i: int) -> bytes:
    """LEB128 encoding (https://en.wikipedia.org/wiki/LEB128)"""
    if i == 0:
        return b"\x00"
    assert i > 0
    b = bytearray()
    while i:
        bits = i & 127
        i = i >> 7
        if i:
            bits |= 128  # All but the final byte have the high bit set
        b.append(bits)
    return bytes(b)


def encode_signed_varint(i: int) -> bytes:
    """Not LEB128; instead we put the sign bit in the lowest bit"""
    sign_bit = i < 0
    return encode_varint(abs(i) << 1 | sign_bit)


def encode_float(x: float) -> bytes:
    return struct.pack("<d", x)


class LongInt:
    def __init__(self, value: int):
        self.value = value
        self.index = -1
        self.bytes = encode_varint(value)


class Float:
    def __init__(self, value: int):
        self.value = value
        self.index = -1
        self.bytes = encode_float(value)


class String:
    def __init__(self, value: str):
        self.value = value
        self.index = -1
        self.bytes = encode_varint(len(value)) + value.encode("utf-8")


SomeConstant = LongInt | Float | String


class Builder:
    # TODO: Intern duplicates

    def __init__(self):
        self.constants: list[SomeConstant] = []

    def add(self, thing: SomeConstant) -> int:
        if thing.index < 0:
            thing.index = len(self.constants)
            self.constants.append(thing)
        assert thing.index >= 0
        return thing.index

    def add_long(self, value: int) -> int:
        return self.add(LongInt(value))

    def add_float(self, value: float) -> int:
        return self.add(Float(value))

    def add_string(self, value: str) -> int:
        return self.add(String(value))

    def add_constant(self, value: object) -> int:
        # TODO: API to add a generalized "Constant"
        # (for which we generate code)
        pass
        


class CodeGenerator:
    """Generate code for a constant."""

    def __init__(self, builder: Builder):
        self.builder = builder
        self.instructions: list[tuple[int, int]] = []

    def emit(self, opcode: int, oparg: int = 0):
        self.instructions.append((opcode, oparg))

    def generate(self, value: object):
        match value:
            case int(i) if 0 <= i < 1<<16:
                self.emit(MAKE_INT, i)
            case int(i) if -256 <= i < 0:
                self.emit(MAKE_INT, -i)
                self.emit(UNARY_NEGATIVE)
            case int(i):
                self.emit(MAKE_LONG, self.builder.add_long(i))
            case float(x):
                self.emit(MAKE_FLOAT, self.builder.add_float(x))
            # TODO: complex, bool, None
            case str(s):
                self.emit(MAKE_STRING, self.builder.add_string(s))
            # TODO: bytes
            case tuple(t):
                # TODO: Avoid needing a really big stack for large tuples
                for item in t:
                    self.generate(item)
                self.emit(BUILD_TUPLE, len(t))
            case _:
                raise TypeError(
                        f"Cannot generate code for "
                        f"{type(value).__name__} -- {value!r}")
                assert False, repr(value)

    def get_bytes(self):
        data = bytearray()
        for opcode, oparg in self.instructions:
            assert isinstance(oparg, int)
            if oparg >= 256:
                # Emit a sequence of EXTENDED_ARG prefix opcodes
                opargs = []
                while oparg:
                    opargs.append(oparg & 0xFF)
                    oparg >>= 8
                opargs.reverse()
                for i in opargs[:-1]:
                    data.extend((EXTENDED_ARG, i))
                oparg = opargs[-1]
            data.extend((opcode, oparg))
        return bytes(data)


def main():
    builder = Builder()
    cg = CodeGenerator(builder)
    cg.generate((0, 1000, -1, "Hi"))
    dis.dis(cg.get_bytes())


if __name__ == "__main__":
    main()
