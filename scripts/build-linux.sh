#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v pyinstaller >/dev/null 2>&1 || { echo "PyInstaller is required: python -m pip install pyinstaller" >&2; exit 1; }
rm -rf "$ROOT/build/pyinstaller" "$ROOT/dist/CrewListrPro"
export PYINSTALLER_CONFIG_DIR="$ROOT/build/pyinstaller-cache"
python -m PyInstaller --noconfirm --windowed --name CrewListrPro --paths "$ROOT" \
  --collect-all pypdfium2 --collect-all sqlcipher3 \
  --distpath "$ROOT/dist" --workpath "$ROOT/build/pyinstaller" --specpath "$ROOT/build/pyinstaller" \
  "$ROOT/launcher.py"
if command -v appimagetool >/dev/null 2>&1; then
  APPDIR="$ROOT/build/AppDir"
  rm -rf "$APPDIR"
  mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications"
  cp -R "$ROOT/dist/CrewListrPro/." "$APPDIR/usr/bin/"
  cp "$ROOT/packaging/CrewListrPro.desktop" "$APPDIR/CrewListrPro.desktop"
  cp "$ROOT/packaging/CrewListrPro.desktop" "$APPDIR/usr/share/applications/CrewListrPro.desktop"
  cp "$ROOT/packaging/CrewListrPro.svg" "$APPDIR/.DirIcon"
  cp "$ROOT/packaging/CrewListrPro.svg" "$APPDIR/CrewListrPro.svg"
  cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env sh
exec "$(dirname "$0")/usr/bin/CrewListrPro" "$@"
EOF
  chmod +x "$APPDIR/AppRun"
  ARCH=x86_64 appimagetool "$APPDIR" "$ROOT/dist/CrewListrPro-x86_64.AppImage"
else
  echo "Standalone Linux bundle created in dist/CrewListrPro. Install appimagetool to also create an AppImage." >&2
fi
