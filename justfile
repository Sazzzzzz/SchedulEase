# Build commands for SchedulEase

# Build for the current platform
run:
    schedulease

build:
    @just build-{{os()}}

# Build for macOS (M1/ARM64)
build-macos:
    nuitka --standalone --onefile --output-dir=dist --output-filename=schedulease_macos_m1 --include-data-file=python/tests/test_data.json=tests/test_data.json --follow-imports python/launcher.py

# Build for Windows x64
build-windows:
    nuitka --standalone --onefile --output-dir=dist --output-filename=schedulease_windows_x64.exe --include-data-file=python/tests/test_data.json=tests/test_data.json --follow-imports --msvc=latest python/launcher.py

# Clean build artifacts
clean:
    rm -rf dist/
    rm -rf build/
    rm -rf *.build/