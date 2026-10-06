# Gera zip de release para o usuário final (sem testes nem arquivos de dev).
# Uso:  .\build_release.ps1            -> dist/regulatory-pipeline-<hash>.zip
#       .\build_release.ps1 -Nome v1   -> dist/regulatory-pipeline-v1.zip
param(
    [string]$Nome = "",
    [string]$Saida = "dist"
)

$ErrorActionPreference = "Stop"
$raiz = $PSScriptRoot

$commit = (git -C $raiz rev-parse --short HEAD).Trim()
if (-not $Nome) { $Nome = "regulatory-pipeline-$commit" }

# Arquivos de desenvolvimento que NÃO vão para o usuário final
$excluir = @(
    ':(exclude)tests'
    ':(exclude).github'
    ':(exclude).pre-commit-config.yaml'
    ':(exclude)codecov.yml'
    ':(exclude)pyproject.toml'
)

$pasta = Join-Path $raiz $Saida
New-Item -ItemType Directory -Force -Path $pasta | Out-Null
$zip = Join-Path $pasta "$Nome.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

git -C $raiz archive --format=zip "--prefix=$Nome/" -o $zip HEAD -- @excluir
if ($LASTEXITCODE -ne 0) { throw "git archive falhou (codigo $LASTEXITCODE)" }

# Verificacao: nada sensivel ou de dev no pacote
python -c @"
import os, sys, zipfile
zp = r'$zip'
cm = r'$commit'
z = zipfile.ZipFile(zp)
names = z.namelist()
checks = {
    'tests/': 'testes',
    '.github/': 'CI',
    'config/secrets.env': 'credenciais reais',
    'data/': 'dados locais',
    'crawler/state/': 'estado de crawl',
    '__pycache__/': 'cache',
}


def bate(n, pat):
    if pat.endswith('/'):
        return pat.rstrip('/') in n.split('/')
    return n == pat or n.endswith('/' + pat)


vazou = [
    rot for pat, rot in checks.items()
    if any(bate(n, pat) for n in names)
]
if vazou:
    print('ERRO: vazou no pacote: ' + ', '.join(vazou))
    sys.exit(1)
print('OK  ' + os.path.basename(zp))
print('    ' + str(len(names)) + ' arquivos, ' + str(os.path.getsize(zp) // 1024) + ' KB')
print('    commit ' + cm)
"@

if ($LASTEXITCODE -ne 0) { throw "verificacao do pacote falhou" }
Write-Host "Release gerada: $zip"
