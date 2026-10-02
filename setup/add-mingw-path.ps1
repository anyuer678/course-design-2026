# 将 WinLibs MinGW-w64 的 bin 目录加入用户 PATH（幂等）
$mingw = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin'
$p = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($p -notlike "*$mingw*") {
    [Environment]::SetEnvironmentVariable('Path', "$p;$mingw", 'User')
    Write-Output "PATH updated: $mingw"
} else {
    Write-Output "already in PATH"
}
