"""Compiler to create new-style PYC files

See https://github.com/faster-cpython/ideas/issues/32
and https://github.com/python/peps/compare/master...markshannon:pep-mappable-pyc-file

This uses match/case (PEP 634) and hence needs Python 3.10.

This doesn't follow the format proposed there exactly; in particular,
I had to add a Blob section so MAKE_LONG, MAKE_FLOAT and MAKE_BYTES (new!)
can use an index instead of having to encode an offset using EXTENDED_ARG.

Also, I gave up on the metadata section for now.
I'm assuming it won't make that much of a difference for a prototype.

BTW, the way I intend to use the prototype is as follows:

- Add the extra fields to PyCode_Object
- Implement the new bytecodes in ceval.c
- Add a hack to the unmarshal code (marshal.loads(), used by importlib)
  to recognize the new format as a new data type and then just stop,
  returning the entire blob.
- *Manually* generate pyc files (essentially using this module) and test.

We can then assess the performance and see where to go from there.
"""

from __future__ import annotations  # I have forward references

import dis  # Where opname/opmap live, according to the docs
import struct
import sys
import types
from typing import Iterator, Protocol, TypeVar

UNARY_NEGATIVE = dis.opmap["UNARY_NEGATIVE"]
BUILD_TUPLE = dis.opmap["BUILD_TUPLE"]
EXTENDED_ARG = dis.opmap["EXTENDED_ARG"]


def def_op(name: str, op: int) -> int:
    dis.opname[op] = name
    dis.opmap[name] = op
    return op


# Extend the set of opcodes
lastop = 169
LAZY_LOAD_CONSTANT = def_op("LAZY_LOAD_CONSTANT", lastop := lastop + 1)
MAKE_STRING = def_op("MAKE_STRING", lastop := lastop + 1)
MAKE_INT = def_op("MAKE_INT", lastop := lastop + 1)
MAKE_LONG = def_op("MAKE_LONG", lastop := lastop + 1)
MAKE_FLOAT = def_op("MAKE_FLOAT", lastop := lastop + 1)
MAKE_COMPLEX = def_op("MAKE_COMPLEX", lastop := lastop + 1)
MAKE_CODE_OBJECT = def_op("MAKE_CODE_OBJECT", lastop := lastop + 1)
MAKE_BYTES = def_op("MAKE_BYTES", lastop := lastop + 1)
LOAD_COMMON_CONSTANT = def_op(
    "LOAD_COMMON_CONSTANT", lastop := lastop + 1
)  # None, False, True
RETURN_CONSTANT = def_op("RETURN_CONSTANT", lastop := lastop + 1)


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


class Bytes:
    def __init__(self, value: bytes):
        self.value = value

    def get_bytes(self) -> bytes:
        return encode_varint(len(self.value)) + self.value


BlobConstant = LongInt | Float | Bytes


class String:
    def __init__(self, value: str):
        assert value is not None
        self.value = value

    def get_bytes(self) -> bytes:
        # Ecode number of bytes, not code points or characters
        b = self.value.encode("utf-8")
        return encode_varint(len(b)) + b


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
        # Needed because RETURN_CONSTANT needs to know its own index
        self.index = index

    def emit(self, opcode: int, oparg: int, stackeffect: int):
        self.instructions.append((opcode, oparg))
        self.stacksize += stackeffect  # Maybe a decrease
        self.max_stacksize = max(self.max_stacksize, self.stacksize)

    def generate(self, value: None | complex | bytes | str | tuple[object]):
        match value:
            case None:
                self.emit(LOAD_COMMON_CONSTANT, 0, 1)
            case False | True as x:
                self.emit(LOAD_COMMON_CONSTANT, int(x) + 1, 1)
            case int(i) if 0 <= i < 1<<16:
                self.emit(MAKE_INT, i, 1)
            case int(i) if -256 <= i < 0:
                self.emit(MAKE_INT, -i, 1)
                self.emit(UNARY_NEGATIVE, 0, 0)
            case int(i):
                self.emit(MAKE_LONG, self.builder.add_long(i), 1)
            case float(x):
                self.emit(MAKE_FLOAT, self.builder.add_float(x), 1)
            case complex(real=re, imag=im):
                self.emit(MAKE_FLOAT, self.builder.add_float(re), 1)
                self.emit(MAKE_FLOAT, self.builder.add_float(im), 1)
                self.emit(MAKE_COMPLEX, 0, -1)
            case bytes(b):
                self.emit(MAKE_BYTES, self.builder.add_bytes(b),1)
            case str(s):
                self.emit(MAKE_STRING, self.builder.add_string(s), 1)
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
            case types.CodeType() as code:
                self.emit(MAKE_CODE_OBJECT, self.builder.add_code(code), 1)
            case _:
                raise TypeError(
                        f"Cannot generate code for "
                        f"{type(value).__name__} -- {value!r}")
                assert False, repr(value)

    def get_bytes(self):
        self.generate(self.value)
        self.emit(RETURN_CONSTANT, self.index, 0)
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


class CodeObject:
    def __init__(self, code: types.CodeType, builder: Builder):
        self.value = code
        self.builder = builder

    def get_bytes(self) -> bytes:
        code = self.value
        exceptiontable = getattr(code, "co_exceptiontable", b"")
        docstring = ""
        if code.co_consts:
            docstring = code.co_consts[0] or ""
        prefix = struct.pack(
            "<12L",
            code.co_flags,
            code.co_argcount,
            code.co_posonlyargcount,
            code.co_kwonlyargcount,
            code.co_nlocals,
            code.co_stacksize,
            self.builder.add_string(code.co_name),
            self.builder.add_bytes(exceptiontable),
            # TODO: The rest should be metadata offsets
            self.builder.add_string(code.co_filename),
            self.builder.add_bytes(b""),  # TODO: location table
            self.builder.add_string(docstring),
            # This logically belongs to the co_code array
            len(code.co_code) // 2,
        )
        co_varnames = bytearray()
        for varname in code.co_varnames:
            index = self.builder.add_string(varname)
            co_varnames += struct.pack("<L", index)
        return (
            prefix
            + code.co_code
            + struct.pack("<L", len(code.co_varnames))
            + co_varnames
        )


class BytesProducer(Protocol):
    def get_bytes(self) -> bytes: ...


class HasValue(Protocol):
    value: object


T = TypeVar("T", bound=HasValue)


class Builder:
    def __init__(self):
        self.codeobjs: list[CodeObject] = []
        self.strings: list[String] = []
        self.blobs: list[BlobConstant] = []
        self.constants: list[ComplexConstant] = []

    def add(self, where: list[T], thing: T) -> int:
        # Look for a match
        for index, it in enumerate(where):
            if type(it) is type(thing) and it.value == thing.value:
                return index
        # Append a new one
        index = len(where)
        where.append(thing)
        return index

    def add_bytes(self, value: bytes) -> int:
        return self.add(self.blobs, Bytes(value))

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

    def add_code(self, code: types.CodeType) -> int:
        return self.add(self.codeobjs, CodeObject(code, self))

    def get_bytes(self) -> bytes:
        code_section_size = 4 * len(self.codeobjs)
        const_section_size = 4 + 4 * len(self.constants)
        string_section_size = 4 + 4 * len(self.strings)
        blob_section_size = 4 + 4 * len(self.blobs)
        binary_section_start = (
            16  # Header size
            + code_section_size
            + const_section_size
            + string_section_size
            + blob_section_size
        )
        binary_data = bytearray()
        def helper(what: list[BytesProducer]) -> bytearray:
            nonlocal binary_data
            offsets = bytearray()
            for i, thing in enumerate(what):
                offsets += struct.pack("<L", binary_section_start + len(binary_data))
                binary_data += thing.get_bytes()
            return offsets

        code_offsets = helper(self.codeobjs)
        const_offsets = helper(self.constants)
        string_offsets = helper(self.strings)
        blob_offsets = helper(self.blobs)
        binary_section_size = len(binary_data)
        prefix_size = (
            16
            + len(code_offsets)
            + 4
            + len(const_offsets)
            + 4
            + len(string_offsets)
            + 4
            + len(blob_offsets)
        )
        header = b".pyc" + struct.pack(
            "<HHLL", 0, len(self.codeobjs), 0, prefix_size + binary_section_size
        )
        assert len(header) == 16
        prefix = (
            header
            + code_offsets
            + struct.pack("<L", len(const_offsets) // 4)
            + const_offsets
            + struct.pack("<L", len(string_offsets) // 4)
            + string_offsets
            + struct.pack("<L", len(blob_offsets) // 4)
            + blob_offsets
        )
        assert len(prefix) == binary_section_start
        return prefix + binary_data


def all_code_objects(code: types.CodeType) -> Iterator[types.CodeType]:
    yield code
    for x in code.co_consts:
        if isinstance(x, types.CodeType):
            yield x


def add_everything(builder: Builder, code: types.CodeType):
    for c in all_code_objects(code):
        builder.add_code(c)
        for x in c.co_consts:
            if not isinstance(x, types.CodeType):
                builder.add_constant(x)


def report(builder: Builder):
    print("Code table:")
    # TODO: Format long byte strings nicer, with ASCII on the side, etc.
    for i, co in enumerate(builder.codeobjs):
        b = co.get_bytes()
        print(f"{i:4d}: {b.hex(' ')}")
    print("Constant table:")
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


def main():
    builder = Builder()
    if not sys.argv[1:]:
        builder.add_constant(
            (0, 1000, -1, "Hello world", "你好", b"hello world", 3.14, 0.5j)
        )
    else:
        filename = sys.argv[1]
        with open(filename, "rb") as f:
            code = compile(f.read(), filename, "exec")
            add_everything(builder, code)
    report(builder)
    pyc_data = builder.get_bytes()
    with open("example.pyc", "wb") as f:
        f.write(pyc_data)
    print(f"Wrote {len(pyc_data)} bytes to example.pyc")


if __name__ == "__main__":
    main()
