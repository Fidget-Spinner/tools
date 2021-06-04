import dis
import sys


from pyco import Builder, add_everything
from unpyc import PycFile


def main():
    for filename in sys.argv[1:]:
        ## print()
        print("=====", filename, "=====")
        with open(filename, "rb") as f:
            try:
                code = compile(f.read(), filename, "exec")
            except SyntaxError:
                continue
        builder = Builder()
        add_everything(builder, code)
        builder.lock()
        try:
            data = builder.get_bytes()
        except RuntimeError as err:
            print(f"{filename}: {err}")
            continue
        pyc = PycFile(data)
        pyc.load()
        ## pyc.report()
        ## for i in range(len(pyc.code_offsets)):
        ##     print("Code object", i)
        ##     code = pyc.get_code(i)
        ##     dis.dis(code)


if __name__ == "__main__":
    main()
