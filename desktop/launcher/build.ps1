$ErrorActionPreference = "Stop"

$project = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$icon = Join-Path $project "desktop\assets\icon.ico"
$appName = -join (0x041E, 0x043C, 0x0435, 0x0433, 0x0430 | ForEach-Object { [char]$_ })
$target = Join-Path $project ($appName + ".exe")

if (-not (Test-Path $csc)) {
    throw "Не найден csc.exe из .NET Framework 4."
}

if (-not (Test-Path $icon)) {
    Write-Host "Рисую иконку..."
    & py -3.14 (Join-Path $PSScriptRoot "make_icon.py")
}

$temp = Join-Path $env:TEMP ("omega_launcher_" + [guid]::NewGuid().ToString("N") + ".exe")
$arguments = @(
    "/nologo",
    "/target:winexe",
    "/platform:anycpu",
    "/optimize+",
    "/codepage:65001",
    "/r:System.dll",
    "/r:System.Windows.Forms.dll",
    "/win32icon:$icon",
    "/out:$temp",
    (Join-Path $PSScriptRoot "Launcher.cs"),
    (Join-Path $PSScriptRoot "AssemblyInfo.cs")
)

Write-Host "Собираю лаунчер..."
& $csc $arguments
if ($LASTEXITCODE -ne 0) {
    throw "csc.exe завершился с кодом $LASTEXITCODE"
}

try {
    Move-Item -LiteralPath $temp -Destination $target -Force
} catch {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    throw "Не удалось записать $target. Закрой запущенный лаунчер и повтори."
}

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcutPath = Join-Path $startMenu ($appName + ".lnk")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $project
$shortcut.IconLocation = "$target,0"
$shortcut.Description = "Omega - local personal assistant"
$shortcut.Save()

Write-Host ""
Write-Host "Готово:"
Write-Host "  $target"
Write-Host "  $shortcutPath"
Write-Host ""
Write-Host "Ярлык появился в Пуске, раздел «Все приложения»."
Write-Host "Чтобы закрепить его в сетке, нажми на ярлык правой кнопкой -> «Закрепить в начальном экране»."
