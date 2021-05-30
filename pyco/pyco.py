"""Compiler to create new-style PYC files

See https://github.com/faster-cpython/ideas/issues/32
and https://github.com/python/peps/compare/master...markshannon:pep-mappable-pyc-file
"""

import dis
import struct

UNARY_NEGATIVE = dis.opmap["UNARY_NEGATIVE"]
BUILD_TUPLE = dis.opmap["BUILD_TUPLE"]
EXTENDED_ARG = dis.opmap["EXTENDED_ARG"]

MAKE_INT = 170
MAKE_LONG = 171
MAKE_FLOAT = 172
MAKE_STRING = 173
# Etc.
dis.opmap["MAKE_INT"] = MAKE_INT
dis.opmap["MAKE_LONG"] = MAKE_LONG
dis.opmap["MAKE_FLOAT"] = MAKE_FLOAT
dis.opmap["MAKE_STRING"] = MAKE_STRING
dis.opname[MAKE_INT] = "MAKE_INT"
dis.opname[MAKE_LONG] = "MAKE_LONG"
dis.opname[MAKE_FLOAT] = "MAKE_FLOAT"
dis.opname[MAKE_STRING] = "MAKE_STRING"



def encode_varint(i):
    """LEB128 encoding (https://en.wikipedia.org/wiki/LEB128)"""
    if i == 0:
        return b"\x00"
    assert i > 0
    b = bytearray()
    while i:
        bits = i & 127
        i = i>>7
        if i:
            bits |= 128  # All but the final byte have the high bit set
        b.append(bits)
    return bytes(b)


def encode_signed_varint(i):
    """Not LEB128; instead we put the sign bit in the lowest bit"""
    sign_bit = i < 0
    return encode_varint(abs(i)<<1 | sign_bit)


def encode_float(x):
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
    def __init__(self):
        self.constants: list[SomeConstant] = []

    def add(self, thing: SomeConstant):
        if thing.index < 0:
            thing.index = len(self.constants)
            self.constants.append(thing)
        assert thing.index >= 0
        return thing.index


class CodeGenerator:
    # TODO: Intern constants

    def __init__(self):
        self.instructions: list[tuple[int, int | SomeConstant]] = []
    
    def emit(self, opcode: int, oparg: int | SomeConstant = 0):
        self.instructions.append((opcode, oparg))

    def generate(self, value):
        match value:
            case int():
                if 0 <= value < 1<<16:
                    self.emit(MAKE_INT, value)
                elif -256 <= value < 0:
                    self.emit(MAKE_INT, -value)
                    self.emit(UNARY_NEGATIVE)
                else:
                    self.emit(MAKE_LONG, LongInt(value))
            case float():
                self.emit(MAKE_FLOAT, Float(value))
            case str():
                self.emit(MAKE_STRING, String(value))
            case tuple():
                # TODO: Avoid needing a really big stack for large tuples
                for item in value:
                    self.generate(item)
                self.emit(BUILD_TUPLE, len(value))

    def fixup(self, builder):
        # Replace non-int opargs with appropriate index values
        for i, (opcode, oparg) in enumerate(self.instructions):
            index = getattr(oparg, "index", oparg)
            assert isinstance(index, int)
            if index < 0:
                index = builder.add(oparg)
                assert index >= 0
                oparg = index
            self.instructions[i] = opcode, oparg
            oparg = index

    def get_bytes(self, builder):
        self.fixup(builder)
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
    cg = CodeGenerator()
    builder = Builder()
    cg.generate((1000, -1, "Hi"))
    dis.dis(cg.get_bytes(builder))


if __name__ == "__main__":
    main()
