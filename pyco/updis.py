"""Add extra opcodes directly to dis/opcode."""

import dis


def def_op(name: str, op: int) -> int:
    dis.opname[op] = name
    dis.opmap[name] = op
    return op


lastop = 169
LAZY_LOAD_CONSTANT = def_op("LAZY_LOAD_CONSTANT", lastop := lastop + 1)
MAKE_STRING = def_op("MAKE_STRING", lastop := lastop + 1)
MAKE_INT = def_op("MAKE_INT", lastop := lastop + 1)
MAKE_LONG = def_op("MAKE_LONG", lastop := lastop + 1)
MAKE_FLOAT = def_op("MAKE_FLOAT", lastop := lastop + 1)
MAKE_COMPLEX = def_op("MAKE_COMPLEX", lastop := lastop + 1)
MAKE_FROZEN_SET = def_op("MAKE_FROZEN_SET", lastop := lastop + 1)
MAKE_CODE_OBJECT = def_op("MAKE_CODE_OBJECT", lastop := lastop + 1)
MAKE_BYTES = def_op("MAKE_BYTES", lastop := lastop + 1)
LOAD_COMMON_CONSTANT = def_op(
    "LOAD_COMMON_CONSTANT", lastop := lastop + 1
)  # None, False, True
RETURN_CONSTANT = def_op("RETURN_CONSTANT", lastop := lastop + 1)

del lastop, def_op

CO_FAST_LOCAL = 0x20
CO_FAST_FREE = 0x80
CO_FAST_CELL = 0x40
