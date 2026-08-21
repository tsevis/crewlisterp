$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
if ($null -eq $pyinstaller) { throw "PyInstaller is required: python -m pip install pyinstaller" }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$root\build\pyinstaller", "$root\dist\CrewListrPro"
$env:PYINSTALLER_CONFIG_DIR = "$root\build\pyinstaller-cache"
python -m PyInstaller --noconfirm --windowed --name CrewListrPro --paths $root --collect-all pypdfium2 --collect-all sqlcipher3 --distpath "$root\dist" --workpath "$root\build\pyinstaller" --specpath "$root\build\pyinstaller" "$root\launcher.py"
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($null -eq $iscc) {
    Write-Warning "Inno Setup was not found; standalone bundle is available in dist\\CrewListrPro."
} else {
    & $iscc.Source "$root\packaging\CrewListrPro.iss"
}
