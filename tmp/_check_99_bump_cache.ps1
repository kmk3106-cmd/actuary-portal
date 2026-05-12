$dir = "C:\Users\USER\actuary potal"
$files = Get-ChildItem -Path $dir -Filter "*.html"
foreach ($f in $files) {
    $content = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
    $updated = $content -replace 'main\.css\?v=1[12]', 'main.css?v=13' `
                        -replace 'portal\.js\?v=1[12]', 'portal.js?v=13'
    if ($updated -ne $content) {
        [System.IO.File]::WriteAllText($f.FullName, $updated, [System.Text.UTF8Encoding]::new($false))
        Write-Host "Updated: $($f.Name)"
    }
}
Write-Host "Done."
