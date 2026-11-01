<#
Preview by default. -Execute permanently removes this project's consultation
records, working evidence copies, exports inside its stores and synthetic test
backups. Original attachments, the standards library, Documents deliverables,
source code and Codex chat history are outside the allowed target roots.
#>
[CmdletBinding()]
param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$taskLocal = [IO.Path]::GetFullPath($env:LOCALAPPDATA)
$taskPackageLocal = Join-Path $taskLocal 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local'
$taskRecordParents = @(
    (Join-Path $taskLocal 'RoadMaintenanceExpert'),
    (Join-Path $taskPackageLocal 'RoadMaintenanceExpert')
)
$taskTempParents = @((Join-Path $taskLocal 'Temp'), (Join-Path $taskPackageLocal 'Temp'))
$taskTargets = @()
foreach ($taskParent in $taskRecordParents) {
    if (Test-Path -LiteralPath $taskParent) {
        $taskTargets += Get-ChildItem -LiteralPath $taskParent -Directory -Force |
            Where-Object { $_.Name -eq '2f50959555be' -or
                $_.Name -eq 'stone-divider-review-20261021' -or
                $_.Name -match '^synthetic-trial-[A-Za-z0-9_-]+$' } |
            ForEach-Object { [pscustomobject]@{ Path = $_.FullName; Parent = $taskParent } }
    }
}
foreach ($taskParent in $taskTempParents) {
    if (Test-Path -LiteralPath $taskParent) {
        $taskTargets += Get-ChildItem -LiteralPath $taskParent -Directory -Force |
            Where-Object { $_.Name -match '^roadexpert-functional-[A-Za-z0-9_-]+$' } |
            ForEach-Object { [pscustomobject]@{ Path = $_.FullName; Parent = $taskParent } }
    }
}

function Test-TaskTarget($Entry) {
    $taskFull = [IO.Path]::GetFullPath($Entry.Path)
    $taskParentFull = [IO.Path]::GetFullPath($Entry.Parent)
    if ($taskParentFull -notin ($taskRecordParents + $taskTempParents) -or
        [IO.Directory]::GetParent($taskFull).FullName -ne $taskParentFull) {
        throw "Target is outside an allowed direct child directory: $taskFull"
    }
    if (!(Test-Path -LiteralPath $taskFull)) { return }
    $taskResolved = (Resolve-Path -LiteralPath $taskFull).ProviderPath
    if ([IO.Path]::GetFullPath($taskResolved) -ne $taskFull) {
        throw "Unexpected path resolution: $taskFull"
    }
    $taskRootItem = Get-Item -LiteralPath $taskFull -Force
    $taskChildren = @(Get-ChildItem -LiteralPath $taskFull -Recurse -Force)
    if (($taskRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        @($taskChildren | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw "Refusing a symbolic link or junction: $taskFull"
    }
    if (@($taskChildren | Where-Object { !$_.PSIsContainer -and $_.Extension -eq '.lock' }).Count) {
        throw "An active or unresolved write lock exists: $taskFull"
    }
}

# Preflight every target before performing any removal, then recheck each target.
foreach ($taskEntry in $taskTargets) { Test-TaskTarget $taskEntry }
if (!$Execute) {
    [pscustomobject]@{
        Mode = 'preview_only'
        TargetPaths = @($taskTargets.Path)
        LogicalPathCount = $taskTargets.Count
        Note = 'Windows aliases may refer to the same files. Nothing has been deleted. Run with -Execute only to clear all listed project stores.'
    } | ConvertTo-Json -Depth 4
    return
}

$taskRemoved = @()
$taskAlreadyAbsent = @()
foreach ($taskEntry in ($taskTargets | Sort-Object { $_.Path.Length } -Descending)) {
    Test-TaskTarget $taskEntry
    if (!(Test-Path -LiteralPath $taskEntry.Path)) {
        $taskAlreadyAbsent += $taskEntry.Path
        continue
    }
    Remove-Item -LiteralPath $taskEntry.Path -Recurse -Force
    if (Test-Path -LiteralPath $taskEntry.Path) { throw "Removal incomplete: $($taskEntry.Path)" }
    $taskRemoved += $taskEntry.Path
}
$taskRemaining = @($taskTargets | Where-Object { Test-Path -LiteralPath $_.Path })
[pscustomobject]@{
    Mode = 'executed'
    RemovedPaths = $taskRemoved.Count
    AlreadyAbsentOrAliasRemoved = $taskAlreadyAbsent.Count
    RemainingPaths = @($taskRemaining.Path)
} | ConvertTo-Json -Depth 4
if ($taskRemaining.Count) { throw 'Some records remain.' }
