"""Windows diagnostic for the Elutek MiiCam/ToupCam RGB detector.

Run from the project root:
    python tools/test_miicam.py

It does not modify camera settings. It reports DLL/architecture, enumeration,
resolution list, and basic frame/BGR statistics if a camera is connected.
"""
import os
import platform
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.miicam_wrapper import (
    MiiCamCapture,
    enumerate_miicam_devices,
    is_miicam_available,
    _find_and_load_dll,
)


def main():
    print("=" * 72)
    print("Elutek — MiiCam RGB detector diagnostic")
    print("=" * 72)
    print("Python:", sys.version.split()[0], platform.architecture()[0])
    print("Platform:", platform.platform())
    dll = _find_and_load_dll()
    print("DLL loaded:", bool(dll))
    print("MiiCam available:", is_miicam_available())
    if not dll:
        print("FAIL: miicam.dll could not be loaded.")
        return 2

    devices = enumerate_miicam_devices()
    print("Detected devices:", len(devices))
    for d in devices:
        print(f"  [{d['index']}] {d['name']} id={d['id']}")
        print("      resolutions:", d.get('resolutions', []))

    if not devices:
        print("FAIL: DLL is present, but no MiiCam camera is enumerated.")
        print("Check USB connection, Windows driver, camera power and whether another application owns it.")
        return 3

    cap = MiiCamCapture(f"miicam:{devices[0]['index']}")
    try:
        print("Opened:", cap.isOpened(), "size:", cap._width, "x", cap._height)
        if not cap.isOpened():
            return 4

        good = 0
        for _ in range(30):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                good += 1
                b, g, r = frame.reshape(-1, 3).mean(axis=0)
                print(f"Frame OK: shape={frame.shape}, mean BGR=({b:.1f}, {g:.1f}, {r:.1f})")
                break
            time.sleep(0.05)

        if not good:
            print("FAIL: camera opened but no valid frames arrived.")
            print("Last error:", getattr(cap, "get_last_error", lambda: "")())
            return 5

        print("Color pipeline defaults:")
        print("  saturation:", cap.saturation)
        print("  contrast:", cap.contrast)
        print("  gamma:", cap.gamma)
        print("  WB temp/tint:", cap.wb_temp, cap.wb_tint)
        print("  WB gains:", cap.wb_r, cap.wb_g, cap.wb_b)
        print("  auto exposure:", cap.auto_exposure)
        print("  exposure us:", cap.exposure_us)
        print("  gain %:", cap.gain_percent)
        print("PASS: detector connected and delivering frames.")
        return 0
    finally:
        cap.release()


if __name__ == "__main__":
    raise SystemExit(main())
