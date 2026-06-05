#!/usr/bin/env python3
import os, sys

here = os.path.dirname(os.path.abspath(__file__))
app  = os.path.join(here, "usb_assistant", "assistent.py")

os.execv(sys.executable, [sys.executable, app])
