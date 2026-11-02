#!/usr/bin/env python3
"""List classes an APK references that neither the APK nor the given boot jars define.

Finds NoClassDefFoundError candidates without running the app, one crash at a time.
usage: dex-missing-classes.py app.apk boot1.jar boot2.jar ...
"""
import struct
import sys
import zipfile


def read_uleb(data, off):
    result = shift = 0
    while True:
        byte = data[off]
        off += 1
        result |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return result, off
        shift += 7


def parse_dex(data):
    string_ids_size, string_ids_off = struct.unpack_from("<II", data, 0x38)
    type_ids_size, type_ids_off = struct.unpack_from("<II", data, 0x40)
    class_defs_size, class_defs_off = struct.unpack_from("<II", data, 0x60)

    def type_name(index):
        string_index = struct.unpack_from("<I", data, type_ids_off + index * 4)[0]
        off = struct.unpack_from("<I", data, string_ids_off + string_index * 4)[0]
        _, off = read_uleb(data, off)
        return data[off:data.index(b"\0", off)].decode("utf-8", "replace")

    referenced = {type_name(i) for i in range(type_ids_size)}
    defined = {
        type_name(struct.unpack_from("<I", data, class_defs_off + i * 32)[0])
        for i in range(class_defs_size)
    }
    return referenced, defined


def read_jar(path):
    referenced, defined = set(), set()
    with zipfile.ZipFile(path) as jar:
        for name in jar.namelist():
            if name.startswith("classes") and name.endswith(".dex"):
                r, d = parse_dex(jar.read(name))
                referenced |= r
                defined |= d
    return referenced, defined


def main():
    referenced, defined = read_jar(sys.argv[1])
    for boot in sys.argv[2:]:
        defined |= read_jar(boot)[1]
    for name in sorted(referenced - defined):
        if name.startswith("L"):
            print(name[1:-1].replace("/", "."))


if __name__ == "__main__":
    main()
