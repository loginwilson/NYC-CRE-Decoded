# Push the repo's migrations to the NYC CRE Decoded project with the Supabase CLI.
# Reads C:\dev\nyc-cre-decoded.env (never printed), builds the pooler URL with the password, runs
#   npx --yes supabase@latest db push --db-url <url> [extra args, e.g. --dry-run]
# and redacts the password from everything it prints.
param([string[]]$Extra = @())
$envPath = "C:\dev\nyc-cre-decoded.env"
$kv = @{}
foreach ($line in Get-Content $envPath) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#") -or -not $t.Contains("=")) { continue }
    $i = $t.IndexOf("="); $kv[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim().Trim('"').Trim("'")
}
$pw = $kv["SUPABASE_DB_PASSWORD"]
$enc = [uri]::EscapeDataString($pw)
$url = $kv["SUPABASE_DB_URL"].Replace("[YOUR-PASSWORD]", $enc)
if ($enc.Contains("%")) { Write-Output "note: password needed percent-encoding; if npx mangles it, apply with supabase/decoded_sql.py -f instead" }
Set-Location "C:\dev\nyc-cre-decoded\Reproduction"
$out = & cmd.exe /c "echo y | npx --yes supabase@latest db push --db-url ""$url"" $($Extra -join ' ') 2>&1"
$out -join "`n" | ForEach-Object { $_.Replace($pw, "***").Replace($enc, "***") }
