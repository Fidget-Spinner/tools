"""Compiler to create new-style PYC files

See https://github.com/faster-cpython/ideas/issues/32
and https://github.com/python/peps/compare/master...markshannon:pep-mappable-pyc-file
"""

from __future__ import annotations

import dis
import struct
from typing import TypeVar

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
RETURN_CONSTANT = def_op("RETURN_CONSTANT", 179)
LAZY_LOAD_CONSTANT = def_op("LAZY_LOAD_CONSTANT", 180)


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

    def get_bytes(self) -> bytes:
        return encode_varint(self.value)


class Float:
    def __init__(self, value: float):
        self.value = value

    def get_bytes(self) -> bytes:
        return encode_float(self.value)


class String:
    def __init__(self, value: str):
        self.value = value

    def get_bytes(self) -> bytes:
        # Ecode number of bytes, not code points or characters
        b = self.value.encode("utf-8")
        return encode_varint(len(b)) + b


BlobConstant = LongInt | Float


class ComplexConstant:
    """Constant represented by code."""

    def __init__(self, value: object, builder: Builder):
        self.value = value
        self.builder = builder
        self.instructions: list[tuple[int, int]] = []
        self.stacksize = 0
        self.max_stacksize = 0
        self.index = -1

    def set_index(self, index: int) -> None:
        self.index = index

    def emit(self, opcode: int, oparg: int, stackeffect: int):
        self.instructions.append((opcode, oparg))
        self.stacksize += stackeffect  # Maybe a decrease
        self.max_stacksize = max(self.max_stacksize, self.stacksize)

    def generate(self, value: object):
        match value:
            case int(i) if 0 <= i < 1<<16:
                self.emit(MAKE_INT, i, 1)
            case int(i) if -256 <= i < 0:
                self.emit(MAKE_INT, -i, 1)
                self.emit(UNARY_NEGATIVE, 0, 0)
            case int(i):
                self.emit(MAKE_LONG, self.builder.add_long(i), 1)
            case float(x):
                self.emit(MAKE_FLOAT, self.builder.add_float(x), 1)
            # TODO: complex, bool, None
            case str(s):
                self.emit(MAKE_STRING, self.builder.add_string(s), 1)
            # TODO: bytes
            case tuple(t):
                # TODO: Avoid needing a really big stack for large tuples
                old_stacksize = self.stacksize
                for item in t:
                    # TODO: But sometimes just
                    # self.generate(item)
                    oparg = self.builder.add_constant(item)
                    self.emit(LAZY_LOAD_CONSTANT, oparg, 1)
                self.emit(BUILD_TUPLE, len(t), 1 - len(t))
                assert self.stacksize == old_stacksize + 1, \
                    (self.stacksize, old_stacksize)
            case _:
                raise TypeError(
                        f"Cannot generate code for "
                        f"{type(value).__name__} -- {value!r}")
                assert False, repr(value)
        self.emit(RETURN_CONSTANT, self.index, 0)

    def get_bytes(self):
        self.generate(self.value)
        data = bytearray()
        for opcode, oparg in self.instructions:
            assert isinstance(oparg, int)
            if oparg >= 256:
                # Emit a sequence of EXTENDED_ARG prefix opcodes
                opargs: list[int] = []
                while oparg:
                    opargs.append(oparg & 0xFF)
                    oparg >>= 8
                opargs.reverse()
                for i in opargs[:-1]:
                    data.extend((EXTENDED_ARG, i))
                oparg = opargs[-1]
            data.extend((opcode, oparg))
        prefix = struct.pack("<LL", self.max_stacksize, len(data) // 2)
        return prefix + bytes(data)


AnyConstant = String | BlobConstant | ComplexConstant


T = TypeVar("T")


class Builder:
    # TODO: Intern duplicates

    def __init__(self):
        self.strings: list[String] = []
        self.blobs: list[BlobConstant] = []
        self.constants: list[ComplexConstant] = []

    def add(self, where: list[T], thing: T) -> int:
        index = len(where)
        where.append(thing)
        return index

    def add_string(self, value: str) -> int:
        return self.add(self.strings, String(value))

    def add_long(self, value: int) -> int:
        return self.add(self.blobs, LongInt(value))

    def add_float(self, value: float) -> int:
        return self.add(self.blobs, Float(value))

    def add_constant(self, value: object) -> int:
        cc = ComplexConstant(value, self)
        index = self.add(self.constants, cc)
        cc.set_index(index)
        return index


def main():
    builder = Builder()
    builder.add_constant((0, 1000, -1, "Hello world", "你好", 3.14, 0.5))
    for i, constant in enumerate(builder.constants):
        b = constant.get_bytes()
        print(f"Code for constant {i} (prefix {b[:8].hex(' ')})")
        dis.dis(b[8:])
    print("String table:")
    for i, string in enumerate(builder.strings):
        b = string.get_bytes()
        print(f"{i:4d}: {b.hex(' ')} ({b!r})")
    print("Blob table:")
    for i, blob in enumerate(builder.blobs):
        b = blob.get_bytes()
        print(f"{i:4d}: {b.hex(' ')}")


if __name__ == "__main__":
    main()
