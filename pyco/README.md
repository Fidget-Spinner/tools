New PYC Format
==============

Blah, blah.  (TODO: Copy from Mark's proto-PEP.)


Provisional Format Specification
================================

This is embedded in the existing PYC format, which is marshal-based.

PYC header
----------

16 bytes.

- First 16 bytes, unchanged (non-marshal PYC header; **INCLUDED IN OFFSETS**)

Marshal header
--------------

16 bytes.

- First marshal byte must be 'P' (new marshal opcode)
- Next three bytes: 'YC.' (filler)
- version: u2 = 0
- n_code_objs: u2
- _: u4 = 0 (reserved for meta_offset)
- total_size: u4 (== length of file)

Offset arrays
-------------

Variable size.

Question: Why put n_code_objs in the header?

- code_offsets: u4 * n_code_objs

- n_consts: u4
- const_offsets: u4 * n_consts

- n_string_offsets: u4
- string_offsets: u4 * n_string_offsets

- n_blob_offsets: u4
- blob_offsets: u4 * n_blob_offsets

Binary data
-----------

Variable size, unstructured; offsets point into this area.

Metadata
--------

Zero bytes (currently not used).

End of data
-----------

Total_size points here.


Things To Do
============

Bytecode Rewriting
------------------

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

Complete Code Loading
---------------------

Without round-tripping the Python code we can't trust anything.

Constant Construction Execution
-------------------------------

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
