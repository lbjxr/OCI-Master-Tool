import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEPS_DIR = os.path.join(BASE_DIR, ".deps")

if os.path.isdir(DEPS_DIR) and DEPS_DIR not in sys.path:
    sys.path.insert(0, DEPS_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from oci_master.app import main


if __name__ == "__main__":
    try:
        os.system("cls" if os.name == "nt" else "clear")
        main()
    except KeyboardInterrupt:
        print("\n\n👋 程序已被手动中止，再见！\n")
