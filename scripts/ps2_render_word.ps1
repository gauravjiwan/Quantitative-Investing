param([Parameter(Mandatory=$true)][string]$Docx,[Parameter(Mandatory=$true)][string]$OutputPdf,[Parameter(Mandatory=$true)][string]$Report)
$ErrorActionPreference='Stop'
$taskWord=$null;$taskDocument=$null
$inputPath=(Resolve-Path -LiteralPath $Docx).Path
$pdfPath=[System.IO.Path]::GetFullPath($OutputPdf)
$reportPath=[System.IO.Path]::GetFullPath($Report)
if ((Test-Path -LiteralPath $pdfPath) -or (Test-Path -LiteralPath $reportPath)) {throw 'Output exists; refusing overwrite.'}
try {
 $taskWord=New-Object -ComObject Word.Application
 $taskWord.Visible=$false;$taskWord.DisplayAlerts=0
 $taskWord.AutomationSecurity=3
 $taskDocument=$taskWord.Documents.Open($inputPath,$false,$true)
 [void]$taskDocument.Fields.Update()
 $taskDocument.Repaginate()
 $mainPages=$taskDocument.Bookmarks.Item('MainEnd').Range.Information(3)
 $totalPages=$taskDocument.ComputeStatistics(2)
 $tablePages=@()
 for ($i=1;$i -le $taskDocument.Tables.Count;$i++) {
   $tablePages+=@{table=$i;page=$taskDocument.Tables.Item($i).Range.Information(3);rows=$taskDocument.Tables.Item($i).Rows.Count}
 }
 $equations=@()
 for ($i=1;$i -le $taskDocument.OMaths.Count;$i++) {
   $math=$taskDocument.OMaths.Item($i)
   $equations+=@{index=$i;type=[int]$math.Type;functions=[int]$math.Functions.Count;text=$math.Range.Text;page=$math.Range.Information(3)}
 }
 $taskDocument.ExportAsFixedFormat($pdfPath,17)
 $record=@{word_version=$taskWord.Version;total_pages=$totalPages;main_pages=$mainPages;native_tables=$taskDocument.Tables.Count;native_equations=$taskDocument.OMaths.Count;table_pages=$tablePages;equations=$equations;input=$inputPath;pdf=$pdfPath;docx_opened_read_only=$true}
 [System.IO.File]::WriteAllText($reportPath,($record|ConvertTo-Json -Depth 8),(New-Object System.Text.UTF8Encoding($false)))
 Write-Output ([pscustomobject]$record|Select-Object total_pages,main_pages,native_tables,native_equations|ConvertTo-Json)
} finally {
 if ($null -ne $taskDocument) {$taskDocument.Close(0);[void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($taskDocument)}
 if ($null -ne $taskWord) {$taskWord.Quit();[void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($taskWord)}
}
