$ErrorActionPreference = 'Stop'
$arcRoot = Split-Path -Parent $PSScriptRoot
$target = Join-Path $arcRoot 'upstream'
if (-not (Test-Path -LiteralPath $target)) {
    git clone https://github.com/code-philia/agentic-requirement-compiler.git $target
    if ($LASTEXITCODE -ne 0) { throw 'ARC clone failed' }
}
git -C $target checkout --detach 5a02a173d33ebd9251b28d97c70f6a0cb5b20deb
if ($LASTEXITCODE -ne 0) { throw 'ARC pinned checkout failed; preserve local upstream changes' }
