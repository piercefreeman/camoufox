"""
Generates per-context + global fingerprint configs using the Camoufox Python API.
Called by the camoufox-tester to get realistic fingerprint data.

Output: JSON object to stdout with macPerContext, linuxPerContext, macGlobal, linuxGlobal
"""
import json
import sys

from presets import generate_presets


def main():
    json.dump(generate_presets(), sys.stdout)


if __name__ == '__main__':
    main()
