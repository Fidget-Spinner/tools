# New PYC Format

Blah, blah. (TODO: Copy from Mark's proto-PEP.)

# Provisional Format Specification

This is embedded in the existing PYC format, which is marshal-based.

Numbers (u2 and u4) are little-endian, and aligned on their size.

Variable-length unsigned integers are encoded using
[LEB128](https://en.wikipedia.org/wiki/LEB128).
However, variable-length signed integers are not encoded
using the algorithm described there; instead, they are
encoded as `sign_bit(i) | (abs(i) << 1)`.
(This format is only used for long integers.)

Strings are encoded using UTF-8 with `errors='surrogatepass'`,
preceded by the number of bytes in varint encoding.

Bytes are similarly preceded with their length in varint.

## Overview of segments

Apart from the PYC file header, the format has the following segments:

- header
- offset arrays
- binary data
- metadata

We describe these segments in more detail below, after the file header
(which during the transition is identical to the existing PYC header).

### File header

16 bytes. This is just the existing PYC file header, unchanged
except for bumping the magic number.
This header is not included in offset calculations,
as it is not included in the data given to marshal.
(A future version of the format may change this.)

### Marshal header

16 bytes. All offsets count from the start of this header.
(But an offset of 0 means "no object".)

This is cleverly designed so that the first character is a
new marshal type code, 'P', which initiates recognition.

- magic_word: str4 = 'PYC.' (filler, magic word)
- version: u2 = 0 (format version)
- flags: u2 = 0 (reserved for future flags)
- metadata_offset: u4 = 0 (reserved for offset to metadata segment)
- total_size: u4 (offset of end of binary/metadata segment)

### Offset arrays

Several variable length arrays of offsets into the binary data,
each preceded by its leghth.
The format of the data referenced is described in a later section.

- n_code_objs: u4
- code_offsets: u4 \* n_code_objs

- n_consts: u4
- const_offsets: u4 \* n_consts

- n_strings: u4
- string_offsets: u4 \* n_strings

- n_blobs: u4
- blob_offsets: u4 \* n_blobs

### Binary data

Variable size, unstructured; offsets point into this area.
It's the wild west, but offsets must not point outside this area,
and the data read must lie wholly inside this area.

### Metadata

Zero bytes (reserved for future use).

### End of data

Total_size points here. (It would be the size of the file minus 16
for the file header.)

## Layout of specific objects

### Code objects

A code object contains a bunch of fixed-width integers
(`co_flags` etc.), a few individual strings (`co_name`,
`co_filename`, perhaps we should add `co_docstring`),
and some arrays of strings (`co_names`, `co_varnames`,
`co_freevars`, `co_cellvars`). It is serialized as a
bunch of u4 integers, using indexes into `string_offsets`
for the individual strings, and arrays of such indexes
for the arrays of strings, each array preceded by its
length (same format as the offset arrays section above).

In addition, a code objects may contain references to constants.
These are serialized as an array of indexes into const_offsets.

- TODO: exact specification
- TODO: can `co_varnames`,`co_freevars`, `co_cellvars`
  be combined in a single array, `co_fastlocals`?
- TODO: we also need a byte array for the "kinds"

### Constant objects

"Constant objects" are constructed upon first use.
They are represented by a small amount of bytecode
that is executed exactly once, upon first use.
Each offset in the const_offsets array points into
the binary data segment where the code is encoded
as follows:

- stack_size: u4
- num_instrs: u4
- instructions: u2 \* num_instrs

The final instruction must be `RETURN_CONSTANT n`
where `n` is the index in const_offsets
(which is also used as the index into `co_consts`).

### String objects

String (unicode) objects are represented as a varint-encoded
byte count followed by bytes representing the original string
encoded with UTF-8 and `errors='surrogatepass'`.

This representation favors compactness over speed
(but it is assumed that decoding UTF-8 is very fast).

### Blob objects

These are used by new instructions `MAKE_LONG`, `MAKE_FLOAT`,
and `MAKE_BYTES`.
The `oparg` represents an index into the blobs array,
which contains an offset into the binary data segment.

- Long integers: varint-encoded `signbit(i) | (abs(i)<<1)`
- Floating point numbers: 8 bytes of IEEE double
- Binary strings: LEB128-encoded size, followed by that many bytes

## Runtime suppport

At runtime, a code object is in one of several states:

- **dehydrated**: there's just a pointer to the serialized code object
  in the binary segment, and a pointer to the PYC segment to keep it alive.

- **partially hydrated**: most fields (e.g. `co_flags`) have been filled in,
  except for some constants in `co_consts` and some names in `co_names`,
  and except for the variable names in `co_varnames`, `co_freecvars`,
  and `co_cellvars`. (Note that `co_varnames` may be used for keyword args.)

- **fully hydrated**: all constants, names and variable names are filled in.

- **compiled**: everything is filled in,
  and there's no pointer to a PYC segment.

# Things To Do

## Bytecode Rewriting

When writing code to PYC, change bytecode to use the new format, e.g.:

- Replace `LOAD_CONST i` with `LAZY_LOAD_CONSTANT j`
  (map local indexes in `co_const` to global constant indices)

- But replace certain `LOAD_CONST i` with `MAKE_INT j`,
  when the constant happens to be an int in [0, 255].

- Do a similar thing with `LOAD_NAME`, `STORE_NAME`, `DELETE_NAME`,
  these should use the strings table.

- Maybe we shouldn't worry about running out of shared constants
  (i.e. indexes >= 256 can't be patched into the bytecode).
  We're just doing an experiment,
  and the real approach must be different.

## Complete Code Loading

Without round-tripping the Python code we can't trust anything.

## Constant Construction Execution

There's bytecode with a stack need, but it won't use any variables.
It ends with a special return opcode, `RETURN_CONSTANT`.

To execute it, we can have a structure like this:

```
struct _constant_invocation_record {
    u64 last_bytecode_array;
    u64 last_program_counter;
    u64 last_stack_pointer;
    struct _constant_invocation_record *last_record;
    PyObject *stack[];
};
```

When executing a `LAZY_LOAD_CONSTANT` instruction,
we allocate a new record like this,
save the current bytecode array, current program counter,
current stack pointer, and current constant invocation record in the record,
and then set all those to point to the new bytecode array etc.

The "current code object" is unchanged, since that is how we get the
strings, blobs and constants referenced by the bytecode for the constant.

Once the new record is fully initialized and the locals updated,
we continue executing the next opcode (which will be in the new bytecode).

When the `RETURN_CONSTANT` opcode is executed,
we capture the final value from the top of the stack
(which should then be empty),
restore everything from the current record, and deallocate the record.
Then we continue execution at the instruction after the
`LAZY_LOAD_CONSTANT` that started this.

The only new local variable to be added to ceval is the pointer to the
current constant invocation record (initialized to NULL).
This is only used when entering and exiting constant construction code.

Note that constant construction does not invoke a C function
to execute its bytecode, so it doesn't add to the C stack
(except by having an extra local variable).
