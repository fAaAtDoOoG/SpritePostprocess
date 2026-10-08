[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$Python,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONUTF8 = '1'

function Resolve-PythonCommand {
    param([string]$RequestedPython)

    function Resolve-RequiredPython {
        param(
            [string]$Value,
            [string]$Source
        )

        $expanded = [Environment]::ExpandEnvironmentVariables($Value)
        if ([System.IO.Path]::IsPathRooted($expanded)) {
            if (Test-Path -LiteralPath $expanded -PathType Leaf) {
                return ,@($expanded)
            }
        }
        elseif (Get-Command $expanded -ErrorAction SilentlyContinue) {
            return ,@($expanded)
        }
        throw "$Source does not resolve to a Python executable: $Value"
    }

    if (-not [string]::IsNullOrWhiteSpace($RequestedPython)) {
        return Resolve-RequiredPython -Value $RequestedPython -Source '-Python'
    }
    if (-not [string]::IsNullOrWhiteSpace($env:SPRITEPOST_PYTHON)) {
        return Resolve-RequiredPython -Value $env:SPRITEPOST_PYTHON -Source 'SPRITEPOST_PYTHON'
    }

    $runtimeConfigPath = Join-Path $toolRoot 'runtime.local.json'
    if (Test-Path -LiteralPath $runtimeConfigPath -PathType Leaf) {
        try {
            $runtimeConfig = Get-Content -LiteralPath $runtimeConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            throw "Invalid runtime.local.json: $($_.Exception.Message)"
        }
        if ($null -eq $runtimeConfig -or [string]::IsNullOrWhiteSpace([string]$runtimeConfig.python)) {
            throw 'runtime.local.json must contain a non-empty "python" string.'
        }
        $configuredPython = [Environment]::ExpandEnvironmentVariables([string]$runtimeConfig.python)
        if (-not [System.IO.Path]::IsPathRooted($configuredPython)) {
            throw 'runtime.local.json "python" must be an absolute path.'
        }
        return Resolve-RequiredPython -Value $configuredPython -Source 'runtime.local.json python'
    }

    $candidates = [System.Collections.Generic.List[object]]::new()
    $candidates.Add(@((Join-Path $toolRoot '.venv\Scripts\python.exe')))
    $candidates.Add(@((Join-Path $toolRoot '.venv\bin\python')))
    $candidates.Add(@('python'))
    $candidates.Add(@('py', '-3'))

    foreach ($candidate in $candidates) {
        $executable = [string]$candidate[0]
        if ([string]::IsNullOrWhiteSpace($executable)) {
            continue
        }
        if ([System.IO.Path]::IsPathRooted($executable)) {
            if (Test-Path -LiteralPath $executable -PathType Leaf) {
                return ,$candidate
            }
            continue
        }
        if (Get-Command $executable -ErrorAction SilentlyContinue) {
            return ,$candidate
        }
    }

    throw 'Python 3 was not found. Use -Python, set SPRITEPOST_PYTHON, create .venv, or add python/py to PATH.'
}

$pythonCommand = Resolve-PythonCommand -RequestedPython $Python
$pythonExe = [string]$pythonCommand[0]
$pythonPrefix = @()
if ($pythonCommand.Count -gt 1) {
    $pythonPrefix = @($pythonCommand[1..($pythonCommand.Count - 1)])
}

if ($Arguments.Count -gt 0) {
    $entryPoint = Join-Path $toolRoot 'spritepost.py'
    $entryArguments = @($pythonPrefix) + @('-u', $entryPoint) + @($Arguments)
}
else {
    $entryPoint = Join-Path $toolRoot 'gui.py'
    $entryArguments = @($pythonPrefix) + @($entryPoint)
}

if (-not (Test-Path -LiteralPath $entryPoint -PathType Leaf)) {
    throw "Tool entry point not found: $entryPoint"
}

& $pythonExe @entryArguments
exit $LASTEXITCODE
