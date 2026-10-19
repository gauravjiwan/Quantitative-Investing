param([Parameter(Mandatory=$true)][string]$Pdf,[Parameter(Mandatory=$true)][string]$OutputDirectory,[int]$Width=1530)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Pdf.PdfDocument,Windows.Data.Pdf,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Pdf.PdfPageRenderOptions,Windows.Data.Pdf,ContentType=WindowsRuntime] | Out-Null
function Await-Operation($Operation,[Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
    $task.Wait()
    return $task.Result
}
function Await-Action($Operation) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
    $task = $method.Invoke($null,@($Operation))
    $task.Wait()
}
$resolvedPdf = (Resolve-Path -LiteralPath $Pdf).Path
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Render output directory already exists; refusing overwrite.' }
$destination = New-Item -ItemType Directory -Path $OutputDirectory
$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolvedPdf)) ([Windows.Storage.StorageFile])
$document = Await-Operation ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
for ($number=0; $number -lt $document.PageCount; $number++) {
    $page = $document.GetPage($number)
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $options.DestinationWidth = $Width
    Await-Action ($page.RenderToStreamAsync($stream,$options))
    $stream.Seek(0)
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $loaded = Await-Operation ($reader.LoadAsync([uint32]$stream.Size)) ([uint32])
    $bytes = New-Object byte[] $loaded
    $reader.ReadBytes($bytes)
    $target = Join-Path $destination.FullName ('page-{0:D2}.png' -f ($number+1))
    [System.IO.File]::WriteAllBytes($target,$bytes)
    $reader.Dispose();$stream.Dispose();$page.Dispose()
    Write-Output ('Rendered page {0}/{1}: {2}' -f ($number+1),$document.PageCount,$target)
}
