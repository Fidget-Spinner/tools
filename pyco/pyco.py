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
        return encode_varint(len(self.value)) + self.value.encode("utf-8")


BlobConstant = LongInt | Float


class ComplexConstant:
    """Constant represented by code."""

    def __init__(self, value: object, builder: Builder):
        self.value = value
        self.builder = builder
        self.instructions: list[tuple[int, int]] = []
        self.index = -1

    def set_index(self, index: int) -> None:
        self.index = index

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
                    # TODO: But sometimes just self.generate(item)
                    oparg = self.builder.add_constant(item)
                    self.emit(LAZY_LOAD_CONSTANT, oparg)
                self.emit(BUILD_TUPLE, len(t))
            case _:
                raise TypeError(
                        f"Cannot generate code for "
                        f"{type(value).__name__} -- {value!r}")
                assert False, repr(value)
        self.emit(RETURN_CONSTANT, self.index)

    def get_bytes(self):
        self.generate(self.value)
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
    builder.add_constant((0, 1000, -1, "Hi", 3.14))
    for i, constant in enumerate(builder.constants):
        print(f"Code for constant {i}")
        dis.dis(constant.get_bytes())
    for i, string in enumerate(builder.strings):
        print(f"String {i} = {string.get_bytes()!r}")
    for i, blob in enumerate(builder.blobs):
        print(f"Blob {i} = {blob.get_bytes()!r}")


if __name__ == "__main__":
    main()
