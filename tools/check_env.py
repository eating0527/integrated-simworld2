#!/usr/bin/env python
"""
Environment version check script.
Verifies Python 3.12+, PyTorch 2.9+, and Sionna 2.x.x are installed with correct versions.
"""

import sys
import importlib.metadata


def parse_version(version_string):
    """Parse a version string into a tuple of integers for comparison."""
    parts = []
    for part in version_string.split('.'):
        try:
            parts.append(int(part))
        except ValueError:
            break
    return tuple(parts)


def check_package_version(name, min_version_str):
    """Check if a package is installed and meets the minimum version requirement."""
    try:
        version = importlib.metadata.version(name)
        min_version = parse_version(min_version_str)
        curr_version = parse_version(version)

        if curr_version >= min_version:
            return True, version
        else:
            return False, f"{version} (required: {min_version_str}+)"
    except importlib.metadata.PackageNotFoundError:
        return False, "not installed"


def main():
    """Perform environment checks."""
    errors = []

    # Check Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info < (3, 12):
        errors.append(f"Python 3.12+ required (found {py_version})")
    else:
        print(f"[OK] Python {py_version}")

    # Check PyTorch
    success, info = check_package_version("torch", "2.9.0")
    if success:
        print(f"[OK] PyTorch {info}")
    else:
        errors.append(f"PyTorch 2.9.0+ required ({info})")

    # Check Sionna
    success, info = check_package_version("sionna", "2.0.0")
    if success:
        print(f"[OK] Sionna {info}")
    else:
        errors.append(f"Sionna 2.0.0+ required ({info})")

    # Report results
    if errors:
        print("\n[FAIL] Environment check failed:")
        for error in errors:
            print(f"   - {error}")
        print("\nTo fix, update your dependencies:")
        print("   cd backend")
        print("   .venv\\Scripts\\python -m pip install -r requirements.txt  # Windows")
        print("   # or")
        print("   .venv/bin/python -m pip install -r requirements.txt       # Linux/macOS")
        return 1

    print("\n[OK] All environment checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
